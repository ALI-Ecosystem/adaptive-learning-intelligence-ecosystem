"""Postgres connection, schema and the sender registry.

Settings come from the environment or from the git-ignored postgres.env that
start-postgres.sh creates (same pattern as neo4j.env)."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from placement import config  # loads .env / neo4j.env

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
config._load_env_file(config.SERVICE_DIR / "postgres.env")


def dsn(dbname: str | None = None) -> str:
    if os.environ.get("LG_DATABASE_URL") and not dbname:
        return os.environ["LG_DATABASE_URL"]
    pw = os.environ.get("POSTGRES_PASSWORD")
    if not pw:
        raise SystemExit(f"POSTGRES_PASSWORD is not set. Run ./start-postgres.sh, which creates "
                         f"{config.SERVICE_DIR}/postgres.env")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5433")
    user = os.environ.get("POSTGRES_USER", "ali")
    return f"postgresql://{user}:{pw}@{host}:{port}/{dbname or os.environ.get('POSTGRES_DB', 'learner_graph')}"


def connect(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or dsn(), row_factory=dict_row, autocommit=True)
    conn.execute("SET search_path = learner_graph")
    return conn


def migrate(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL.read_text())
    conn.execute("SET search_path = learner_graph")


def register_sender(conn, sender_id: str, public_key: bytes, operations: list[str],
                    can_correct_others: bool = False) -> None:
    """Add a sender, or rotate its key / change its rights (an admin action)."""
    conn.execute(
        """INSERT INTO sender (sender_id, public_key, operations, can_correct_others)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (sender_id) DO UPDATE SET public_key = EXCLUDED.public_key,
               operations = EXCLUDED.operations, can_correct_others = EXCLUDED.can_correct_others,
               active = true""",
        (sender_id, public_key, operations, can_correct_others))


def deactivate_sender(conn, sender_id: str) -> None:
    conn.execute("UPDATE sender SET active = false WHERE sender_id = %s", (sender_id,))
