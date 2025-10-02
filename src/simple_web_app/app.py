import contextlib
import importlib.resources
import logging
import time
import os
import random
import sqlite3
import datetime
from pathlib import Path

import aiosql
import aiosqlite
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware import Middleware
# from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from simple_web_app.migration import apply_migrations, create_migrations_table_if_not_exists

logger = logging.getLogger(__name__)

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

config = Config()
DEBUG = config("DEBUG", cast=bool, default=True)
DATABASE_PATH = config("DATABASE_PATH", default="./db.sqlite3")
# SECRET_KEY = config("SECRET_KEY", default="asdf")

DATABASE_PATH = Path(DATABASE_PATH)
MIGRATION_DIR = importlib.resources.files("simple_web_app").joinpath("migrations")
TEMPLATE_DIR = importlib.resources.files("simple_web_app").joinpath("templates")
QUERY_DIR = importlib.resources.files("simple_web_app").joinpath("queries")
STATIC_DIR = importlib.resources.files("simple_web_app").joinpath("static")

templates = Jinja2Templates(directory=TEMPLATE_DIR)
queries_basic = aiosql.from_path(QUERY_DIR / "basic.sql", "aiosqlite")


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


def format_timedelta(tdelta, fmt):
    d = {"days": tdelta.days}
    d["hours"], rem = divmod(tdelta.seconds, 3600)
    d["minutes"], d["seconds"] = divmod(rem, 60)
    return fmt.format(**d)


async def show_home_page(request: Request):
    page = request.query_params.get("page", default=0)
    page = int(page) if page is not None else page
    current_time = request.query_params.get("current_time", default=datetime.datetime.now(tz=datetime.UTC))

    limit = 5
    offset = page * limit

    t0 = time.time()
    rows = await queries_basic.get_categories(request.state.conn, limit=20)
    all_categories = [row["category"] for row in rows]

    rows = await queries_basic.get_news(request.state.conn, limit=limit, offset=offset, max_published_time=current_time)
    news = [dict(row) for row in rows]
    for new in news:
        rows = await queries_basic.get_categories_for_news(request.state.conn, news_item_id=new["id"])
        categories = [row["category"] for row in rows]
        new["categories"] = categories
        published = datetime.datetime.strptime(new["published"], "%Y-%m-%dT%H:%M:%S.%f%z")
        new["time_since_published"] = format_timedelta(datetime.datetime.now(tz=datetime.UTC) - published, "{days} days, {hours} hours ago")
    elapsed = time.time() - t0
    logger.info({"event": "load_page", "page": "/home", "time_s": elapsed})

    context = {"news": news, "categories": all_categories, "page": page, "current_time": current_time}
    if is_htmx_request(request):
        context = context | {"oob": True}
    template_name = "oob_swap.html" if is_htmx_request(request) else "index.html"
    return render(request, template_name, context=context)


async def open_search(request: Request):
    return render(request, "search.html")


async def search(request: Request):
    async with request.form() as form:
        query = form["search"]
    rows = await queries_basic.search_news(request.state.conn, query=query, limit=10) if query else []
    return render(request, "search_results.html", context={"news": rows})


async def open_settings(request: Request):
    tab = request.query_params.get("tab", default=None)
    if tab:
        return render(request, "settings_tab.html", context={"tab": tab})
    return render(request, "settings.html", context={"tab": "general"})


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.autocommit = True
    create_migrations_table_if_not_exists(conn)
    migration_files = sorted(MIGRATION_DIR.glob("*.sql"))
    migration_queries = [p.read_text() for p in migration_files]
    apply_migrations(conn, migration_queries)

    async with aiosqlite.connect(DATABASE_PATH, autocommit=True) as conn:
        conn.row_factory = aiosqlite.Row
        cursors = [conn.execute(query) for query in SQLITE_PRAGMAS]
        [await c for c in cursors]
        yield {"conn": conn}


routes = [
    Route("/", methods=["GET"], endpoint=show_home_page),
    Route("/search", methods=["GET"], endpoint=open_search),
    Route("/search", methods=["POST"], endpoint=search),
    Route("/settings", methods=["GET"], endpoint=open_settings),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]
middleware = [
    # Middleware(SessionMiddleware, secret_key=SECRET_KEY),
]
app = Starlette(
    debug=DEBUG,
    routes=routes,
    middleware=middleware,
    lifespan=lifespan,
)
