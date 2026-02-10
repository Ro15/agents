"""PostgreSQL data connector."""

from app.connectors.sqlalchemy_connector import SQLAlchemyConnector


class PostgresConnector(SQLAlchemyConnector):
    connector_type = "postgresql"
    _quote_char = '"'
