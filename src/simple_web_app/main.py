import contextlib
import logging
import os
import sqlite3
from pathlib import Path

import aiosql
import aiosqlite
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from simple_web_app.migration import (
    apply_migrations,
    create_migrations_table_if_not_exists,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SQLITE_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = 1000000000;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA busy_timeout = 5000;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA synchronous = NORMAL;",
]
MIGRATION_FOLDER = Path("./migrations")

DATABASE_PATH = os.getenv("DATABASE_PATH", default="./db.sqlite3")

templates = Jinja2Templates(directory="./templates")
queries_basic = aiosql.from_path("./queries/basic.sql", "aiosqlite")
# queries_auth = aiosql.from_path("./queries/auth.sql", "aiosqlite")


def is_htmx_request(request: Request) -> bool:
    is_hx_request = request.headers.get("HX-Request") is not None
    is_hx_history_restore = (
        request.headers.get("HX-History-Restore-Request") is not None
    )
    return is_hx_request or is_hx_history_restore


def render(
    request: Request, partial_template: str, include_oob: str | None = None, **kwargs
):
    ctx = kwargs.get("context", {})
    is_authenticated = False  # request.user.is_authenticated if request.user else False
    ctx = ctx | {"is_authenticated": is_authenticated}
    headers = kwargs.get("headers", {})
    if is_htmx_request(request):
        if include_oob:
            ctx = ctx | {
                "context_partial": partial_template,
                "oob_template": include_oob,
            }
        return templates.TemplateResponse(
            request, partial_template, ctx, headers=headers
        )
    return templates.TemplateResponse(
        request,
        "application.html",
        ctx | {"content": partial_template},
        headers=headers,
    )


async def show_home_page(request: Request):
    return render(request, "index.html")


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    conn = sqlite3.connect(DATABASE_PATH)
    create_migrations_table_if_not_exists(conn)
    migration_files = sorted(MIGRATION_FOLDER.glob("*.sql"))
    migration_queries = [p.read_text() for p in migration_files]
    apply_migrations(conn, migration_queries)

    async with aiosqlite.connect(DATABASE_PATH, autocommit=True) as conn:
        conn.row_factory = aiosqlite.Row
        cursors = [conn.execute(query) for query in SQLITE_PRAGMAS]
        [await c for c in cursors]
        yield {"conn": conn}


routes = [
    Route("/", methods=["GET"], endpoint=show_home_page),
    Mount("/static", StaticFiles(directory="static"), name="static"),
]
app = Starlette(debug=False, routes=routes, lifespan=lifespan)
