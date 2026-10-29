from app.db import make_database_url


def test_neon_url_uses_asyncpg_and_ssl():
    url, connect_args = make_database_url(
        "postgresql://user:pass@ep-example-pooler.eu-central-1.aws.neon.tech/app?sslmode=require&channel_binding=require"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    assert connect_args == {"ssl": "require"}


def test_postgres_scheme_is_normalized():
    url, _ = make_database_url("postgres://user:pass@localhost/app")
    assert url.drivername == "postgresql+asyncpg"
