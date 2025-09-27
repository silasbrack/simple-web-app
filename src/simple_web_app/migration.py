import logging
import sqlite3

logger = logging.getLogger(__name__)


def create_migrations_table_if_not_exists(conn: sqlite3.Connection) -> None:
    migrations_table_exists = (
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migration_version';").fetchone()
        is not None
    )
    if not migrations_table_exists:
        logger.info("Creating migrations table migration_version.")
        conn.execute("CREATE TABLE migration_version (version INTEGER)")
        conn.execute("INSERT INTO migration_version (version) VALUES (0)")
        conn.commit()


def apply_migrations(conn: sqlite3.Connection, migration_queries: list[str]) -> None:
    (db_version,) = conn.execute("SELECT version FROM migration_version").fetchone()
    num_migrations = len(migration_queries)
    for i in range(db_version, num_migrations):
        query = migration_queries[i]
        logger.info(f"Running migration {i}: {query}")
        conn.execute("BEGIN")
        try:
            _ = conn.executescript(query)
            conn.commit()
        except Exception as e:
            logger.error(f"Encountered the following error while running the migration: {e}")
            conn.rollback()
            raise
        _ = conn.execute("UPDATE migration_version SET version = ?", [i + 1])
        conn.commit()
