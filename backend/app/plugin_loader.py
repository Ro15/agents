"""
Plugin Loader: Manages sector-specific configurations.

This module loads and validates plugin configurations (schema, metrics, questions, policies)
enabling sector-agnostic data analysis without code changes.
"""

import os
import json
import yaml
import logging
import re
from typing import Dict, Any, Optional, Set, List
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ColumnDefinition:
    """Represents a database column."""
    name: str
    type: str
    meaning: str
    nullable: bool = True


@dataclass
class TableDefinition:
    """Represents a database table."""
    name: str
    columns: Dict[str, ColumnDefinition]
    primary_time_column: Optional[str] = None
    description: str = ""


@dataclass
class MetricDefinition:
    """Represents a KPI or metric."""
    name: str
    description: str
    sql_template: str  # Can contain {table}, {column}, {time_filter} placeholders
    output_type: str  # "number", "table", "trend"
    aggregation: Optional[str] = None  # "sum", "count", "avg", "min", "max"


@dataclass
class QuestionPattern:
    """Represents a supported question pattern."""
    pattern: str  # Regex or keyword pattern
    required_metrics: List[str]
    constraints: Dict[str, Any]


@dataclass
class QuestionPack:
    """Represents a logical grouping of questions."""
    name: str
    description: str
    patterns: List[QuestionPattern]


@dataclass
class RelationshipDefinition:
    """Represents a foreign key relationship between two tables."""
    name: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship_type: str  # "many_to_one", "one_to_many", "one_to_one"
    description: str = ""


@dataclass
class PolicyConfig:
    """Represents security and behavior policies."""
    allowed_question_types: List[str]
    forbidden_topics: List[str]
    max_date_range_days: Optional[int] = None
    enable_forecasting: bool = False
    enable_predictions: bool = False
    confidence_rules: Dict[str, str] = None


@dataclass
class PluginDefinition:
    """Canonical plugin model used internally and for discovery endpoints."""
    id: str
    name: str
    description: str
    domains: List[str]
    required_columns: List[str]
    sample_csvs: List[str]
    tables: Dict[str, TableDefinition]
    primary_time_column: Optional[str]
    metrics: Dict[str, MetricDefinition]
    question_packs: Dict[str, QuestionPack]
    policy: PolicyConfig


class PluginConfig:
    """Encapsulates all configuration for a sector plugin."""
    
    def __init__(self, plugin_name: str, config_dir: str):
        """
        Args:
            plugin_name: Name of the plugin (e.g., 'retail', 'manufacturing')
            config_dir: Base directory containing plugin configs
        """
        self.plugin_name = plugin_name
        self.config_dir = Path(config_dir) / plugin_name
        
        self.schema: Dict[str, TableDefinition] = {}
        self.relationships: List[RelationshipDefinition] = []
        self.metrics: Dict[str, MetricDefinition] = {}
        self.question_packs: Dict[str, QuestionPack] = {}
        self.policy: PolicyConfig = None
        self.validated: bool = False
        self.validation_errors: List[str] = []
        self.compiled_views: List[str] = []
        
        self._load_all_configs()
        self._validate()
    
    def _load_all_configs(self):
        """Loads all configuration files for the plugin."""
        if not self.config_dir.exists():
            raise ValueError(f"Plugin directory not found: {self.config_dir}")
        
        logger.info(f"Loading plugin configuration from {self.config_dir}")
        
        # Load schema
        schema_file = self.config_dir / "schema.yaml"
        if schema_file.exists():
            self._load_schema(schema_file)
        else:
            raise ValueError(f"schema.yaml not found in {self.config_dir}")
        
        # Load metrics
        metrics_file = self.config_dir / "metrics.yaml"
        if metrics_file.exists():
            self._load_metrics(metrics_file)
        
        # Load question packs
        questions_file = self.config_dir / "questions.yaml"
        if questions_file.exists():
            self._load_questions(questions_file)
        
        # Load policy
        policy_file = self.config_dir / "policy.yaml"
        if policy_file.exists():
            self._load_policy(policy_file)
        else:
            # Use default policy
            self.policy = PolicyConfig(
                allowed_question_types=["aggregation", "trend", "comparison"],
                forbidden_topics=["pii", "personal_data"],
                max_date_range_days=None,
                enable_forecasting=False,
                enable_predictions=False
            )
        
        # Load insights
        insights_file = self.config_dir / "insights.yaml"
        if insights_file.exists():
            self._load_insights(insights_file)
        else:
            self.insights = {}
        
        logger.info(f"Plugin '{self.plugin_name}' loaded successfully")
        logger.info(f"  Tables: {list(self.schema.keys())}")
        logger.info(f"  Metrics: {list(self.metrics.keys())}")
        logger.info(f"  Question packs: {list(self.question_packs.keys())}")
        logger.info(f"  Insights: {list(self.insights.keys())}")

    def _validate(self):
        """Run structural validations; record errors but do not raise."""
        errors: List[str] = []

        if not self.schema:
            errors.append("schema.yaml must define at least one table")

        known_tables = set(self.schema.keys())
        known_columns: Dict[str, set] = {}
        for table_name, table in self.schema.items():
            if not table.columns:
                errors.append(f"schema: table '{table_name}' must define at least one column")
                continue
            known_columns[table_name] = set(table.columns.keys())

        for rel in self.relationships:
            if rel.from_table not in known_tables:
                errors.append(f"relationship '{rel.name}': unknown from_table '{rel.from_table}'")
                continue
            if rel.to_table not in known_tables:
                errors.append(f"relationship '{rel.name}': unknown to_table '{rel.to_table}'")
                continue
            if rel.from_column not in known_columns.get(rel.from_table, set()):
                errors.append(
                    f"relationship '{rel.name}': unknown from_column '{rel.from_table}.{rel.from_column}'"
                )
            if rel.to_column not in known_columns.get(rel.to_table, set()):
                errors.append(
                    f"relationship '{rel.name}': unknown to_column '{rel.to_table}.{rel.to_column}'"
                )
            if rel.relationship_type not in {"many_to_one", "one_to_many", "one_to_one"}:
                errors.append(f"relationship '{rel.name}': invalid type '{rel.relationship_type}'")

        if self.policy:
            if not isinstance(self.policy.allowed_question_types, list):
                errors.append("policy.allowed_question_types must be a list")
            if not isinstance(self.policy.forbidden_topics, list):
                errors.append("policy.forbidden_topics must be a list")

        for metric_name, metric in self.metrics.items():
            sql_template = (metric.sql_template or "").strip()
            if not sql_template:
                errors.append(f"metric '{metric_name}': sql_template is required")
                continue

            render_table = next(iter(known_tables), "missing_table")
            rendered = re.sub(r"\{[^}]+\}", render_table, sql_template)
            if not rendered.lower().lstrip().startswith("select"):
                errors.append(f"metric '{metric_name}': SQL must start with SELECT")
                continue

            metric_tables = self._extract_tables_from_sql(rendered)
            unknown_metric_tables = sorted(t for t in metric_tables if t not in known_tables)
            if unknown_metric_tables:
                errors.append(
                    f"metric '{metric_name}': references unknown table(s): {', '.join(unknown_metric_tables)}"
                )

        self.validation_errors = errors
        self.validated = len(errors) == 0

    @staticmethod
    def _extract_tables_from_sql(sql: str) -> Set[str]:
        """Best-effort table extractor from FROM/JOIN clauses."""
        tables: Set[str] = set()
        for match in re.finditer(r"(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE):
            tables.add(match.group(1))
        return tables
    
    def _load_schema(self, schema_file: Path):
        """Loads schema configuration including table relationships."""
        with open(schema_file, 'r') as f:
            schema_data = yaml.safe_load(f)

        if not schema_data or 'tables' not in schema_data:
            raise ValueError("schema.yaml must contain 'tables' key")

        for table_name, table_data in schema_data['tables'].items():
            columns = {}
            for col_name, col_data in table_data.get('columns', {}).items():
                columns[col_name] = ColumnDefinition(
                    name=col_name,
                    type=col_data.get('type', 'string'),
                    meaning=col_data.get('meaning', ''),
                    nullable=col_data.get('nullable', True)
                )

            self.schema[table_name] = TableDefinition(
                name=table_name,
                columns=columns,
                primary_time_column=table_data.get('primary_time_column'),
                description=table_data.get('description', '')
            )

        # Load relationships
        self.relationships = []
        for rel_data in schema_data.get('relationships', []):
            self.relationships.append(RelationshipDefinition(
                name=rel_data.get('name', ''),
                from_table=rel_data.get('from_table', ''),
                from_column=rel_data.get('from_column', ''),
                to_table=rel_data.get('to_table', ''),
                to_column=rel_data.get('to_column', ''),
                relationship_type=rel_data.get('type', 'many_to_one'),
                description=rel_data.get('description', ''),
            ))

        logger.info(f"Loaded schema with {len(self.schema)} tables and {len(self.relationships)} relationships")
    
    def _load_metrics(self, metrics_file: Path):
        """Loads metrics configuration."""
        with open(metrics_file, 'r') as f:
            metrics_data = yaml.safe_load(f)
        
        if not metrics_data or 'metrics' not in metrics_data:
            logger.warning("metrics.yaml not found or empty")
            return
        
        for metric_name, metric_data in metrics_data['metrics'].items():
            self.metrics[metric_name] = MetricDefinition(
                name=metric_name,
                description=metric_data.get('description', ''),
                sql_template=metric_data.get('sql_template', ''),
                output_type=metric_data.get('output_type', 'number'),
                aggregation=metric_data.get('aggregation')
            )
        
        logger.info(f"Loaded {len(self.metrics)} metrics")
    
    def _load_questions(self, questions_file: Path):
        """Loads question packs configuration."""
        with open(questions_file, 'r') as f:
            questions_data = yaml.safe_load(f)
        
        if not questions_data or 'question_packs' not in questions_data:
            logger.warning("questions.yaml not found or empty")
            return
        
        for pack_name, pack_data in questions_data['question_packs'].items():
            patterns = []
            for pattern_data in pack_data.get('patterns', []):
                patterns.append(QuestionPattern(
                    pattern=pattern_data.get('pattern', ''),
                    required_metrics=pattern_data.get('required_metrics', []),
                    constraints=pattern_data.get('constraints', {})
                ))
            
            self.question_packs[pack_name] = QuestionPack(
                name=pack_name,
                description=pack_data.get('description', ''),
                patterns=patterns
            )
        
        logger.info(f"Loaded {len(self.question_packs)} question packs")
    
    def _load_policy(self, policy_file: Path):
        """Loads policy configuration."""
        with open(policy_file, 'r') as f:
            policy_data = yaml.safe_load(f)
        
        self.policy = PolicyConfig(
            allowed_question_types=policy_data.get('allowed_question_types', []),
            forbidden_topics=policy_data.get('forbidden_topics', []),
            max_date_range_days=policy_data.get('max_date_range_days'),
            enable_forecasting=policy_data.get('enable_forecasting', False),
            enable_predictions=policy_data.get('enable_predictions', False),
            confidence_rules=policy_data.get('confidence_rules', {})
        )
        
        logger.info(f"Loaded policy configuration")
    
    def _load_insights(self, insights_file: Path):
        """Loads insights configuration."""
        with open(insights_file, 'r') as f:
            insights_data = yaml.safe_load(f)
        
        if not insights_data or 'insights' not in insights_data:
            logger.warning("insights.yaml not found or empty")
            self.insights = {}
            return
        
        self.insights = insights_data['insights']
        logger.info(f"Loaded {len(self.insights)} insights")
    
    def get_allowed_tables(self) -> Set[str]:
        """Returns set of allowed table names."""
        return set(self.schema.keys())
    
    def get_allowed_columns(self) -> Set[str]:
        """Returns set of all allowed column names across all tables."""
        columns = set()
        for table in self.schema.values():
            columns.update(table.columns.keys())
        return columns
    
    def get_schema_description(self) -> str:
        """Returns human-readable schema description for LLM prompts."""
        description = f"# {self.plugin_name.upper()} Schema\n\n"

        for table_name, table in self.schema.items():
            description += f"## Table: `{table_name}`\n"
            if table.description:
                description += f"{table.description}\n\n"

            description += "### Columns:\n"
            for col_name, col in table.columns.items():
                description += f"- `{col_name}` ({col.type}): {col.meaning}\n"

            if table.primary_time_column:
                description += f"\n**Primary Time Column**: `{table.primary_time_column}`\n"

            description += "\n"

        if self.relationships:
            description += self.get_relationships_description()

        return description

    def get_relationships_description(self) -> str:
        """Returns human-readable relationship descriptions for LLM prompts."""
        if not self.relationships:
            return ""

        desc = "# Table Relationships (use JOINs when the question spans multiple tables)\n\n"
        for rel in self.relationships:
            join_type = "LEFT JOIN" if rel.relationship_type == "many_to_one" else "JOIN"
            desc += (
                f"- `{rel.from_table}`.`{rel.from_column}` -> "
                f"`{rel.to_table}`.`{rel.to_column}` "
                f"({rel.relationship_type}): {rel.description}\n"
                f"  Example: `{join_type} {rel.to_table} ON {rel.from_table}.{rel.from_column} = {rel.to_table}.{rel.to_column}`\n"
            )
        return desc
    
    def get_metrics_description(self) -> str:
        """Returns human-readable metrics description for LLM prompts."""
        if not self.metrics:
            return ""
        
        description = "# Available Metrics\n\n"
        for metric_name, metric in self.metrics.items():
            description += f"- `{metric_name}`: {metric.description}\n"
            if metric.aggregation:
                description += f"  (Aggregation: {metric.aggregation})\n"
        
        return description
    
    def validate_question(self, question: str) -> tuple[bool, str]:
        """
        Validates a question against policy constraints.
        
        Returns:
            (is_valid, reason)
        """
        question_lower = question.lower()
        
        # Check forbidden topics
        for topic in self.policy.forbidden_topics:
            if topic.lower() in question_lower:
                return False, f"Question contains forbidden topic: {topic}"
        
        return True, ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts plugin config to dictionary."""
        return {
            "plugin_name": self.plugin_name,
            "tables": list(self.schema.keys()),
            "relationships": [asdict(r) for r in self.relationships],
            "metrics": list(self.metrics.keys()),
            "question_packs": list(self.question_packs.keys()),
            "policy": asdict(self.policy) if self.policy else {}
        }

    def required_columns(self) -> List[str]:
        """Return columns marked non-nullable (rough proxy for required inputs)."""
        required = []
        for table in self.schema.values():
            for col in table.columns.values():
                if col.nullable is False:
                    required.append(col.name)
        return sorted(set(required))

    def primary_time_column(self) -> Optional[str]:
        for table in self.schema.values():
            if table.primary_time_column:
                return table.primary_time_column
        return None

    def to_definition(self) -> PluginDefinition:
        name = self.plugin_name.replace("_", " ").title()
        description = f"{name} plugin"
        domains: List[str] = []
        return PluginDefinition(
            id=self.plugin_name,
            name=name,
            description=description,
            domains=domains,
            required_columns=self.required_columns(),
            sample_csvs=[],
            tables=self.schema,
            primary_time_column=self.primary_time_column(),
            metrics=self.metrics,
            question_packs=self.question_packs,
            policy=self.policy,
        )


class PluginManager:
    """Manages multiple plugins and provides plugin switching."""
    
    def __init__(self, plugins_dir: str = "plugins"):
        """
        Args:
            plugins_dir: Base directory containing all plugins
        """
        self.plugins_dir = Path(plugins_dir)
        self.plugins: Dict[str, PluginConfig] = {}
        self.active_plugin: Optional[str] = None
        
        self._discover_plugins()
    
    def _discover_plugins(self):
        """Discovers and loads all available plugins."""
        if not self.plugins_dir.exists():
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")
            return
        
        for plugin_dir in self.plugins_dir.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.name.startswith('_'):
                try:
                    plugin = PluginConfig(plugin_dir.name, str(self.plugins_dir))
                    if plugin.validated:
                        self.plugins[plugin_dir.name] = plugin
                        logger.info(f"Discovered plugin: {plugin_dir.name}")
                    else:
                        logger.error(f"Skipping plugin '{plugin_dir.name}' due to validation errors: {plugin.validation_errors}")
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_dir.name}: {e}")
    
    def get_plugin(self, plugin_name: str) -> Optional[PluginConfig]:
        """Gets a plugin by name."""
        return self.plugins.get(plugin_name)
    
    def set_active_plugin(self, plugin_name: str) -> bool:
        """Sets the active plugin."""
        if plugin_name not in self.plugins:
            logger.error(f"Plugin not found: {plugin_name}")
            return False
        
        self.active_plugin = plugin_name
        logger.info(f"Active plugin set to: {plugin_name}")
        return True
    
    def get_active_plugin(self) -> Optional[PluginConfig]:
        """Gets the currently active plugin."""
        if not self.active_plugin:
            return None
        return self.plugins.get(self.active_plugin)
    
    def list_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Lists all available plugins."""
        return {name: plugin.to_dict() for name, plugin in self.plugins.items()}

    def list_definitions(self) -> Dict[str, PluginDefinition]:
        """Return canonical plugin definitions keyed by id."""
        return {name: plugin.to_definition() for name, plugin in self.plugins.items()}

    def list_summaries(self) -> List[Dict[str, Any]]:
        """Return lightweight metadata for discovery endpoints."""
        summaries = []
        for plugin in self.plugins.values():
            definition = plugin.to_definition()
            summaries.append({
                "id": definition.id,
                "name": definition.name,
                "description": definition.description,
                "domains": definition.domains,
                "required_columns": definition.required_columns,
                "sample_csvs": definition.sample_csvs,
            })
        return summaries
    
    def get_plugin_names(self) -> List[str]:
        """Returns list of available plugin names."""
        return list(self.plugins.keys())
