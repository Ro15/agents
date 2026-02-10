"""MySQL data connector."""

from app.connectors.sqlalchemy_connector import SQLAlchemyConnector


class MySQLConnector(SQLAlchemyConnector):
    connector_type = "mysql"
    _quote_char = "`"

    def _fix_url(self, url: str) -> str:
        """Ensure pymysql driver is specified."""
        if url.startswith("mysql://"):
            return url.replace("mysql://", "mysql+pymysql://", 1)
        return url
