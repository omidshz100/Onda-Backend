def escape_alembic_url(database_url: str) -> str:
    """Escape ConfigParser interpolation markers in a runtime database URL."""
    return database_url.replace("%", "%%")
