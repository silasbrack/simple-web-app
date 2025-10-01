import datetime
import logging
import sqlite3
from pathlib import Path

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
        print(f"Running migration {i}: {query}")
        conn.execute("BEGIN TRANSACTION")
        try:
            _ = conn.executescript(query)
            _ = conn.execute("UPDATE migration_version SET version = ?", [i + 1])
            conn.execute("COMMIT TRANSACTION")
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.exception(f"Encountered the following error while running the migration: {e}")
            raise



def create_migration(name: str, migrations_dir: Path):
    current_timestamp = datetime.datetime.now(tz=datetime.UTC)
    file_name = f"{current_timestamp.strftime('%Y%m%d%H%M%S')}_{name}.sql"
    file_path = migrations_dir / file_name
    file_path.touch()
    return file_path


def run_create_migration():
    import argparse
    import importlib.resources

    default_migrations_dir = importlib.resources.files("simple_web_app").joinpath("migrations")
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("-d", "--dir", default=default_migrations_dir)
    args = parser.parse_args()

    path = create_migration(args.name, Path(args.dir))
    print(str(path))


if __name__ == "__main__":
    run_create_migration()

