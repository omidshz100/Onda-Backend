from app.db.alembic import escape_alembic_url


def test_escape_alembic_url_handles_encoded_password_characters() -> None:
    url = "postgresql+asyncpg://user:p%2Bass@database.example/onda?ssl=require"

    assert escape_alembic_url(url) == (
        "postgresql+asyncpg://user:p%%2Bass@database.example/onda?ssl=require"
    )
