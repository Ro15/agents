"""
SQL Guard: Security and validation layer for SQL queries.

This module enforces guardrails to ensure only safe, read-only queries
are executed against the database.
"""

import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)


class SQLGuardError(Exception):
    """Raised when SQL validation fails."""
    pass


class SQLGuard:
    """Validates SQL queries against security guardrails."""
    
    # Forbidden SQL keywords (write operations)
    FORBIDDEN_KEYWORDS = {
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'TRUNCATE', 'ALTER',
        'GRANT', 'REVOKE', 'PRAGMA', 'VACUUM', 'ANALYZE', 'REINDEX'
    }
    
    # Allowed keywords for read-only operations
    ALLOWED_KEYWORDS = {
        'SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'LIMIT', 'OFFSET',
        'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'ON', 'USING',
        'UNION', 'INTERSECT', 'EXCEPT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
        'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE', 'IS', 'NULL',
        'DISTINCT', 'AS', 'WITH', 'RECURSIVE', 'HAVING', 'CROSS'
    }
    
    # Allowed aggregate functions
    ALLOWED_FUNCTIONS = {
        'SUM', 'COUNT', 'AVG', 'MIN', 'MAX', 'STDDEV', 'VARIANCE',
        'DATE', 'EXTRACT', 'CURRENT_DATE', 'CURRENT_TIMESTAMP', 'NOW',
        'UPPER', 'LOWER', 'CONCAT', 'SUBSTRING', 'LENGTH', 'TRIM',
        'ROUND', 'ABS', 'CEIL', 'FLOOR', 'COALESCE', 'NULLIF',
        'CAST', 'TO_CHAR', 'TO_DATE', 'INTERVAL'
    }

    # Extra identifiers we allow even if not in schema (common derived aliases)
    EXTRA_ALLOWED_IDENTIFIERS = {
        'day', 'date', 'sale_date', 'order_date', 'timestamp', 'total_sales'
    }
    
    def __init__(self, allowed_tables: Set[str], allowed_columns: Set[str]):
        """
        Args:
            allowed_tables: Set of table names that can be queried
            allowed_columns: Set of column names that can be accessed
        """
        self.allowed_tables = allowed_tables
        self.allowed_columns = allowed_columns
    
    def validate(self, sql: str) -> bool:
        """
        Validates a SQL query against all guardrails.
        
        Args:
            sql: SQL query string to validate
        
        Returns:
            True if valid
        
        Raises:
            SQLGuardError: If validation fails
        """
        sql = sql.strip()
        
        # 1. Must be a SELECT statement
        if not sql.upper().lstrip().startswith("SELECT"):
            raise SQLGuardError("Query must be a SELECT statement.")
        
        # 2. Check for forbidden keywords
        self._check_forbidden_keywords(sql)
        
        # 3. Check for allowed tables and columns
        self._check_schema_allowlist(sql)
        
        # 4. Check for SQL injection patterns
        self._check_injection_patterns(sql)

        # 5. Block risky functions
        self._check_risky_functions(sql)
        
        logger.info(f"SQL validation passed: {sql[:100]}...")
        return True
    
    def _check_forbidden_keywords(self, sql: str) -> None:
        """Checks for forbidden SQL keywords."""
        sql_upper = sql.upper()
        
        for keyword in self.FORBIDDEN_KEYWORDS:
            # Use word boundaries to avoid false positives
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, sql_upper):
                raise SQLGuardError(f"Query contains forbidden keyword: {keyword}")
    
    def _check_schema_allowlist(self, sql: str) -> None:
        """Checks that query only references allowed tables and columns."""
        # Extract identifiers (table/column names)
        # This regex matches quoted and unquoted identifiers
        identifiers = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', sql.lower()))
        # remove aliases (anything following AS)
        alias_matches = re.findall(r'\bas\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, flags=re.IGNORECASE)
        alias_matches += re.findall(r'\)\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql)  # function aliases without AS
        identifiers = identifiers - {a.lower() for a in alias_matches}

        # Remove SQL keywords from identifiers
        keywords = self.ALLOWED_KEYWORDS | self.FORBIDDEN_KEYWORDS | self.ALLOWED_FUNCTIONS
        identifiers = identifiers - {kw.lower() for kw in keywords}

        disallowed = identifiers - self.allowed_tables - self.allowed_columns
        disallowed = disallowed - {'as', 'on', 'and', 'or', 'not', 'in', 'is', 'null'}
        disallowed = disallowed - {x.lower() for x in self.EXTRA_ALLOWED_IDENTIFIERS}
        if disallowed:
            raise SQLGuardError(f"Query references identifiers not in allowlist: {', '.join(sorted(disallowed))}")
    
    def _check_injection_patterns(self, sql: str) -> None:
        """Checks for common SQL injection patterns."""
        # Check for suspicious patterns
        suspicious_patterns = [
            r"--\s*$",  # SQL comments at end
            r"/\*.*\*/",  # Block comments
            r";\s*\w+",  # Multiple statements
            r"'\s*OR\s*'",  # Classic OR injection
            r"'\s*;\s*DROP",  # DROP injection
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                raise SQLGuardError(f"Query contains suspicious pattern: {pattern}")

    def _check_risky_functions(self, sql: str) -> None:
        risky = {"pg_sleep", "pg_stat_activity", "pg_catalog", "set_config"}
        for fn in risky:
            if re.search(rf"\b{fn}\b", sql, re.IGNORECASE):
                raise SQLGuardError(f"Query uses disallowed function {fn}")

    def enforce_dataset_filter(self, sql: str, dataset_param: str = "dataset_id") -> str:
        """
        Ensures the SQL has a dataset filter; injects if missing.
        Blocks literal dataset_id usage.
        """
        if re.search(rf"\b{dataset_param}\s*=\s*['\"]", sql, re.IGNORECASE):
            raise SQLGuardError("Dataset filter must be parameterized, not literal.")

        if re.search(rf"\b{dataset_param}\b", sql, re.IGNORECASE):
            return sql  # already present (assumed parameterized)

        # Find main table alias from first FROM
        from_match = re.search(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)(\s+as\s+([a-zA-Z_][a-zA-Z0-9_]*))?", sql, re.IGNORECASE)
        alias = None
        if from_match:
            alias = from_match.group(3) or from_match.group(1)

        predicate = f"{alias}.{dataset_param} = :{dataset_param}" if alias else f"{dataset_param} = :{dataset_param}"

        # inject before LIMIT if present
        lower_sql = sql.lower()
        limit_idx = lower_sql.rfind("limit")
        if limit_idx != -1:
            before = sql[:limit_idx].rstrip()
            after = sql[limit_idx:]
        else:
            before, after = sql, ""

        if " where " in lower_sql or lower_sql.startswith("where "):
            scoped = f"{before} AND {predicate} {after}".strip()
        else:
            scoped = f"{before} WHERE {predicate} {after}".strip()
        return scoped
    
    def extract_tables_and_columns(self, sql: str) -> Tuple[Set[str], Set[str]]:
        """
        Extracts table and column names from a SQL query.
        
        Args:
            sql: SQL query string
        
        Returns:
            Tuple of (tables, columns) sets
        """
        identifiers = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', sql.lower()))
        
        tables = identifiers.intersection(self.allowed_tables)
        columns = identifiers.intersection(self.allowed_columns)
        
        return tables, columns
