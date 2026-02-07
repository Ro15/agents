"""
Insight Engine: Automated, plugin-aware business insights generation.

This module generates structured business insights from data without user questions.
Insights are defined in configuration (insights.yaml) and executed on-demand or scheduled.
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import asdict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from app import nl_to_sql

from app.insight_models import InsightMetric, InsightDefinition, GeneratedInsight

logger = logging.getLogger(__name__)


class InsightEngine:
    """Generates business insights from plugin-defined rules."""
    
    def __init__(self, plugin_config):
        """
        Args:
            plugin_config: PluginConfig instance with loaded insights.yaml
        """
        self.plugin_config = plugin_config
        self.insights: Dict[str, InsightDefinition] = {}
        # Determine default tables for placeholder replacement
        self.default_table = next(iter(plugin_config.schema.keys()), "sales_transactions")
        self.production_table = "production_runs" if "production_runs" in plugin_config.schema else self.default_table
        self._load_insights()
    
    def _load_insights(self):
        """Loads insight definitions from plugin configuration."""
        if not hasattr(self.plugin_config, 'insights') or not self.plugin_config.insights:
            logger.warning(f"No insights defined for plugin '{self.plugin_config.plugin_name}'")
            return
        
        for insight_id, insight_data in self.plugin_config.insights.items():
            self.insights[insight_id] = InsightDefinition(
                insight_id=insight_id,
                title=insight_data.get('title', ''),
                description=insight_data.get('description', ''),
                required_metrics=insight_data.get('required_metrics', []),
                sql_queries=insight_data.get('sql_queries') or insight_data.get('queries', {}),
                trigger_condition=insight_data.get('trigger_condition', {}),
                severity=insight_data.get('severity', 'info'),
                explanation_template=insight_data.get('explanation_template', ''),
                data_window=insight_data.get('data_window', ''),
                required_columns=insight_data.get('required_columns', []),
            )
        
        logger.info(f"Loaded {len(self.insights)} insights for plugin '{self.plugin_config.plugin_name}'")
    
    def run_all_insights(self, db: Session, dataset_id: str) -> List[GeneratedInsight]:
        """
        Runs all insights for the active plugin.
        
        Args:
            db: Database session
        
        Returns:
            List of generated insights
        """
        generated_insights = []
        
        for insight_id, insight_def in self.insights.items():
            try:
                insight = self.run_insight(insight_id, db, dataset_id)
                if insight:
                    generated_insights.append(insight)
            except Exception as e:
                logger.error(f"Error running insight '{insight_id}': {e}")
        
        logger.info(f"Generated {len(generated_insights)} insights for plugin '{self.plugin_config.plugin_name}'")
        return generated_insights
    
    def run_insight(self, insight_id: str, db: Session, dataset_id: str) -> Optional[GeneratedInsight]:
        """
        Runs a specific insight.
        
        Args:
            insight_id: ID of the insight to run
            db: Database session
        
        Returns:
            GeneratedInsight if triggered, None otherwise
        """
        if insight_id not in self.insights:
            logger.error(f"Insight '{insight_id}' not found")
            return None
        
        insight_def = self.insights[insight_id]
        
        try:
            # Execute SQL queries
            query_results, executed_sql = self._execute_queries(insight_def, db, dataset_id)
            
            if not query_results:
                logger.warning(f"No data for insight '{insight_id}'")
                return None
            
            # Evaluate trigger condition
            is_triggered, confidence, derived_metrics = self._evaluate_trigger(insight_def, query_results)
            
            if not is_triggered:
                logger.debug(f"Insight '{insight_id}' not triggered")
                return None
            
            # Generate insight
            insight = self._generate_insight(insight_def, query_results, executed_sql, derived_metrics, confidence)
            
            logger.info(f"Generated insight '{insight_id}' with severity '{insight.severity}'")
            return insight
            
        except ValueError as e:
            logger.warning(f"Insight '{insight_id}' skipped: {e}")
            return None
        except Exception as e:
            logger.error(f"Error generating insight '{insight_id}': {e}")
            return None
    
    def _execute_queries(self, insight_def: InsightDefinition, db: Session, dataset_id: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """
        Executes SQL queries for an insight.
        
        Args:
            insight_def: Insight definition
            db: Database session
        
        Returns:
            (Dictionary of query results, mapping query_id -> executed SQL)
        """
        results: Dict[str, Any] = {}
        executed_sql: Dict[str, str] = {}

        # Validate required columns if specified
        if insight_def.required_columns:
            missing_cols = [c for c in insight_def.required_columns if c not in self.plugin_config.get_allowed_columns()]
            if missing_cols:
                raise ValueError(f"Required columns missing: {missing_cols}")
        
        for query_id, sql_block in insight_def.sql_queries.items():
            try:
                sql_template = sql_block.get("query") if isinstance(sql_block, dict) else sql_block
                if not sql_template:
                    logger.warning(f"Query block '{query_id}' missing 'query' for insight '{insight_def.insight_id}'")
                    continue

                # Replace placeholders
                sql = self._prepare_sql(sql_template)
                sql = nl_to_sql.SQL_GUARD.enforce_dataset_filter(sql, "dataset_id")
                executed_sql[query_id] = sql
                
                # Execute query
                conn = db.connection()
                conn.execute(text("SET statement_timeout = '5s';"))
                result = conn.execute(text(sql), {"dataset_id": dataset_id}).mappings().all()
                
                # Convert to dict
                results[query_id] = [dict(row) for row in result]
                
                logger.debug(f"Executed query '{query_id}' for insight '{insight_def.insight_id}'")
                
            except Exception as e:
                logger.error(f"Error executing query '{query_id}': {e}")
                return {}, []
        
        return results, executed_sql
    
    def _prepare_sql(self, sql_template: str) -> str:
        """
        Prepares SQL by replacing placeholders.
        
        Args:
            sql_template: SQL template with placeholders
        
        Returns:
            Prepared SQL
        """
        # Replace common placeholders
        sql = sql_template.replace('{table}', self.default_table)
        sql = sql.replace('{production_table}', self.production_table)
        
        # Replace time placeholders
        now = datetime.now()
        sql = sql.replace('{current_date}', f"'{now.date()}'")
        sql = sql.replace('{yesterday}', f"'{(now - timedelta(days=1)).date()}'")
        sql = sql.replace('{7_days_ago}', f"'{(now - timedelta(days=7)).date()}'")
        sql = sql.replace('{14_days_ago}', f"'{(now - timedelta(days=14)).date()}'")
        
        return sql
    
    def _evaluate_trigger(self, insight_def: InsightDefinition, query_results: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Evaluates trigger condition for an insight.
        
        Args:
            insight_def: Insight definition
            query_results: Query results
        
        Returns:
            (is_triggered, confidence, derived_metrics)
        """
        condition = insight_def.trigger_condition
        
        if not condition:
            return False, "low", {}
        
        condition_type = condition.get('type', '')
        
        if condition_type == 'threshold':
            return self._evaluate_threshold(condition, query_results)
        elif condition_type == 'comparison':
            return self._evaluate_comparison(condition, query_results)
        elif condition_type == 'anomaly':
            return self._evaluate_anomaly(condition, query_results)
        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return False, "low", {}
    
    def _evaluate_threshold(self, condition: Dict[str, Any], query_results: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluates threshold-based trigger."""
        query_id = condition.get('query_id', '')
        metric_path = condition.get('metric_path', '')
        operator = condition.get('operator', '')
        threshold = condition.get('threshold', 0)
        
        if query_id not in query_results or not query_results[query_id]:
            return False, "low", {}
        
        result = query_results[query_id][0]
        value = self._get_nested_value(result, metric_path)
        
        if value is None:
            return False, "low", {}
        
        triggered = self._compare_values(value, operator, threshold)
        confidence = "high" if triggered else "low"
        
        return triggered, confidence, {"threshold_value": threshold, "observed_value": value}
    
    def _evaluate_comparison(self, condition: Dict[str, Any], query_results: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluates comparison-based trigger (e.g., week-over-week)."""
        current_query = condition.get('current_query_id', '')
        previous_query = condition.get('previous_query_id', '')
        metric_path = condition.get('metric_path', '')
        previous_metric_path = condition.get('previous_metric_path', metric_path)
        operator = condition.get('operator', '')
        threshold_percent = condition.get('threshold_percent', 0)
        
        if current_query not in query_results or previous_query not in query_results:
            return False, "low", {}
        
        if not query_results[current_query] or not query_results[previous_query]:
            return False, "low", {}
        
        current_value = self._get_nested_value(query_results[current_query][0], metric_path)
        previous_value = self._get_nested_value(query_results[previous_query][0], previous_metric_path)
        
        if current_value is None or previous_value is None or previous_value == 0:
            return False, "low", {}
        
        change_percent = ((current_value - previous_value) / previous_value) * 100
        
        triggered = self._compare_values(change_percent, operator, threshold_percent)
        confidence = "high" if abs(change_percent) > 5 else "medium"
        
        derived = {
            "current_value": current_value,
            "previous_value": previous_value,
            "change_percent": round(change_percent, 2)
        }
        return triggered, confidence, derived
    
    def _evaluate_anomaly(self, condition: Dict[str, Any], query_results: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluates anomaly-based trigger (baseline comparison)."""
        current_query = condition.get('current_query_id', '')
        baseline_query = condition.get('baseline_query_id', '')
        metric_path = condition.get('metric_path', '')
        std_dev_threshold = condition.get('std_dev_threshold', 2.0)
        
        if current_query not in query_results or baseline_query not in query_results:
            return False, "low", {}
        
        if not query_results[current_query] or not query_results[baseline_query]:
            return False, "low", {}
        
        current_value = self._get_nested_value(query_results[current_query][0], metric_path)
        baseline_values = [self._get_nested_value(row, metric_path) for row in query_results[baseline_query]]
        baseline_values = [v for v in baseline_values if v is not None]
        
        if not baseline_values or current_value is None:
            return False, "low", {}
        
        # Simple anomaly detection
        baseline_mean = sum(baseline_values) / len(baseline_values)
        baseline_std = (sum((v - baseline_mean) ** 2 for v in baseline_values) / len(baseline_values)) ** 0.5
        
        if baseline_std == 0:
            return False, "low", {}
        
        z_score = abs((current_value - baseline_mean) / baseline_std)
        triggered = z_score > std_dev_threshold
        confidence = "high" if z_score > 3 else "medium" if z_score > 2 else "low"
        
        derived = {
            "current_value": current_value,
            "baseline_mean": round(baseline_mean, 2),
            "baseline_std": round(baseline_std, 2),
            "z_score": round(z_score, 2),
            "std_dev_threshold": std_dev_threshold
        }
        return triggered, confidence, derived
    
    def _get_nested_value(self, obj: Dict[str, Any], path: str) -> Any:
        """Gets nested value from dict using dot notation."""
        keys = path.split('.')
        value = obj
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    
    def _compare_values(self, value: Any, operator: str, threshold: Any) -> bool:
        """Compares values using operator."""
        try:
            if operator == '>':
                return value > threshold
            elif operator == '<':
                return value < threshold
            elif operator == '>=':
                return value >= threshold
            elif operator == '<=':
                return value <= threshold
            elif operator == '==':
                return value == threshold
            elif operator == '!=':
                return value != threshold
            else:
                return False
        except Exception as e:
            logger.error(f"Error comparing values: {e}")
            return False
    
    def _generate_insight(self, insight_def: InsightDefinition, query_results: Dict[str, Any],
                          executed_sql: Dict[str, str], derived_metrics: Dict[str, Any],
                          confidence: str) -> GeneratedInsight:
        """
        Generates a structured insight.
        
        Args:
            insight_def: Insight definition
            query_results: Query results
            confidence: Confidence level
            db: Database session
        
        Returns:
            GeneratedInsight object
        """
        # Extract metrics from query results
        metrics = self._extract_metrics(insight_def, query_results, derived_metrics)
        if not self._has_numeric_evidence(metrics):
            raise ValueError("Insufficient numeric evidence")
        
        # Generate summary
        summary = self._generate_summary(insight_def, metrics)
        
        # Generate detailed explanation (LLM-assisted)
        details = self._generate_details(insight_def, metrics, summary)
        
        return GeneratedInsight(
            insight_id=insight_def.insight_id,
            title=insight_def.title,
            severity=insight_def.severity,
            summary=summary,
            details=details,
            metrics=metrics,
            sql=executed_sql,
            data_window=insight_def.data_window,
            confidence=confidence,
            plugin=self.plugin_config.plugin_name,
            generated_at=datetime.now().isoformat()
        )
    
    def _extract_metrics(self, insight_def: InsightDefinition, query_results: Dict[str, Any],
                         derived_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts metrics from query results."""
        metrics = {}
        
        for query_id, results in query_results.items():
            if results:
                metrics[query_id] = results[0]
                metrics[f"{query_id}_rows"] = results

        # Include derived metrics (e.g., change_percent) so templates can use them
        for key, value in derived_metrics.items():
            metrics[key] = value
        
        return metrics
    
    def _generate_summary(self, insight_def: InsightDefinition, metrics: Dict[str, Any]) -> str:
        """Generates a 1-2 line summary."""
        # Use template if available
        if insight_def.explanation_template:
            summary = insight_def.explanation_template
            # Replace placeholders with actual values (supports {key.metric} and {metric})
            flat_metrics = self._flatten_metrics(metrics)
            for placeholder, metric_value in flat_metrics.items():
                summary = summary.replace(f"{{{placeholder}}}", str(metric_value))
            return summary
        
        # Default summary
        return f"{insight_def.title}: {insight_def.description}"
    
    def _generate_details(self, insight_def: InsightDefinition, metrics: Dict[str, Any], summary: str) -> str:
        """Generates detailed explanation."""
        details = f"{summary}\n\n"
        details += f"Data Window: {insight_def.data_window}\n"
        details += f"Severity: {insight_def.severity}\n\n"
        details += "Metrics:\n"
        
        for query_id, result in metrics.items():
            if isinstance(result, dict):
                details += f"  {query_id}:\n"
                for key, value in result.items():
                    details += f"    {key}: {value}\n"
            else:
                details += f"  {query_id}: {result}\n"
        
        return details

    def _has_numeric_evidence(self, metrics: Dict[str, Any]) -> bool:
        """Ensures at least one numeric metric exists before generating insight."""
        for value in metrics.values():
            if isinstance(value, dict):
                if any(isinstance(v, (int, float)) for v in value.values()):
                    return True
            elif isinstance(value, (int, float)):
                return True
        return False

    def _flatten_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Flattens metrics for placeholder replacement."""
        flat = {}
        for key, value in metrics.items():
            if isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    flat[f"{key}.{inner_key}"] = inner_value
                    flat[inner_key] = inner_value  # allow {metric} shortcuts
            else:
                flat[key] = value
        return flat


def generate_insight_narration(insight_structured: Dict[str, Any], plugin_context: Optional[str] = None) -> Dict[str, str]:
    """
    Returns narration for an already-computed insight.
    LLM hook placeholder: numbers must already exist inside `insight_structured`.
    Currently deterministic to avoid fabrication; integrate LLM here if available.
    """
    summary = insight_structured.get("summary") or f"{insight_structured.get('title', 'Insight')}"
    details = insight_structured.get("details") or summary
    if plugin_context:
        details = f"[{plugin_context}] {details}"
    return {"summary": summary, "details": details}
    
    def to_dict(self, insight: GeneratedInsight) -> Dict[str, Any]:
        """Converts insight to dictionary."""
        return asdict(insight)
