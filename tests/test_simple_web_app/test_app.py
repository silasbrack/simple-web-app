import os
import unittest
import datetime
import collections
from pprint import pprint

import aiosqlite
import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from starlette.testclient import TestClient


DummyData = collections.namedtuple("DummyData", ["table", "cols", "rows"])


async def insert_dummy_data(conn: aiosqlite.Connection, data: DummyData):
    await conn.executemany(f"INSERT INTO {data.table} ({', '.join(data.cols)}) VALUES ({', '.join(['?'] * len(data.cols))});", data.rows)


@pytest.fixture()
def test_news_item() -> DummyData:
    return DummyData(
        table="news_item",
        cols=["id", "url", "title", "text", "published", "author", "language"],
        rows=[
            (1, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
            (2, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
            (3, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
            (4, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
            (5, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
            (6, "https://example.com", "Test Title", "Asdf.", datetime.datetime(2025, 8, 1, 20, 42, 35, 123, tzinfo=datetime.UTC).isoformat(), "Silas", "english"),
        ]
    )


@pytest.fixture()
def test_category() -> DummyData:
    return DummyData(
        table="category",
        cols=["id", "name"],
        rows=[(1, "Category 1")]
    )


@pytest.fixture()
def test_news_item_category() -> DummyData:
    return DummyData(
        table="news_item_category",
        cols=["id", "news_item_id", "category_id"],
        rows=[
            (1, 1, 1),
            (2, 2, 1),
            (3, 3, 1),
            (4, 4, 1),
            (5, 5, 1),
            (6, 6, 1),
        ]
    )


@pytest.fixture()
def test_data(test_news_item, test_category, test_news_item_category) -> tuple[DummyData, ...]:
    return (test_news_item, test_category, test_news_item_category)


async def test_home_page(async_test_client, test_data):
    """Full home page render."""
    async with async_test_client as client:
        conn = client.app_state["conn"]
        for d in test_data:
            await insert_dummy_data(conn, d)
        response = await client.get("/")

    assert response.status_code == 200
    assert response.template.name == "application.html"
    assert len(response.context["news"]) > 0


async def test_home_htmx(async_test_client, test_data):
    """Partial home template render for HTMX."""
    async with async_test_client as client:
        conn = client.app_state["conn"]
        for d in test_data:
            await insert_dummy_data(conn, d)
        response = await client.get("/", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert response.template.name == "oob_swap.html"


async def test_select_chain(async_test_client, test_data):
    """"""
    async with async_test_client as client:
        conn = client.app_state["conn"]
        for d in test_data:
            await insert_dummy_data(conn, d)

        # Open the home page
        response = await client.get("/")
        assert response.status_code == 200
        assert response.template.name == "application.html"
        assert len(response.context["news"]) > 0
        soup = BeautifulSoup(response.text, features="html.parser")
        load_more_button = soup.find("button", {"id": "load-more-btn"})
        assert "page=1" in load_more_button.attrs["hx-get"]
        assert "category_id" not in load_more_button.attrs["hx-get"]

        # Load more data
        path = load_more_button["hx-get"]
        response = await client.get(path, headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert len(response.context["news"]) > 0

        # Filter for category 2, which doesn't exist
        # TODO: should this instead throw an error?
        response = await client.get("/?category_id=2", headers={"HX-Request": "true"})
        assert response.template.name == "oob_swap.html"
        assert len(response.context["news"]) == 0
        assert response.context["category_id"] == 2
        soup = BeautifulSoup(response.text, features="html.parser")
        load_more_button = soup.find("button", {"id": "load-more-btn"})
        assert "page=1" in load_more_button.attrs["hx-get"]
        assert "category_id=2" in load_more_button.attrs["hx-get"]

        # Filter for category 1, show only news with that category
        response = await client.get("/?category_id=1", headers={"HX-Request": "true"})
        assert response.template.name == "oob_swap.html"
        assert len(response.context["news"]) > 0
        assert response.context["category_id"] == 1
        assert all(any(c["id"] == 1 for c in n["categories"]) for n in response.context["news"])  # Every row contains the category we filtered by
        soup = BeautifulSoup(response.text, features="html.parser")
        load_more_button = soup.find("button", {"id": "load-more-btn"})
        assert "disabled" not in load_more_button.attrs
        assert "page=1" in load_more_button.attrs["hx-get"]
        assert "category_id=1" in load_more_button.attrs["hx-get"]

        # Load more news, should all still be category one; we only have 1 left so the load more button should be disabled
        path = load_more_button["hx-get"]
        response = await client.get(path, headers={"HX-Request": "true"})
        assert response.template.name == "oob_swap.html"
        assert len(response.context["news"]) > 0
        assert response.context["category_id"] == 1
        assert all(any(c["id"] == 1 for c in n["categories"]) for n in response.context["news"])  # Every row contains the category we filtered by
        soup = BeautifulSoup(response.text, features="html.parser")
        load_more_button = soup.find("button", {"id": "load-more-btn"})
        assert "disabled" in load_more_button.attrs
        assert "page=2" in load_more_button.attrs["hx-get"]
        assert "category_id=1" in load_more_button.attrs["hx-get"]


async def test_settings(async_test_client, test_data):
    async with async_test_client as client:
        # Open the home page
        response = await client.get("/")
        soup = BeautifulSoup(response.text, features="html.parser")
        modal_placeholder = soup.find("div", {"id": "modal-placeholder"})
        assert len(list(modal_placeholder.children)) == 0

        # Open the settings modal
        settings_button = soup.find("a", {"id": "settings-btn"})
        path = settings_button["hx-get"]
        response = await client.get(path, headers={"HX-Request": "true"})
        assert response.template.name == "settings.html"
        soup = BeautifulSoup(response.text, features="html.parser")
        assert soup.find("h4").text == "Appearance"
        # TODO: check that the modal_placeholder has an element

        # Open the sync tab within the settings
        sync_tab = soup.find("div", {"id": "syncing-tab"})
        path = sync_tab["hx-get"]
        response = await client.get(path, headers={"HX-Request": "true"})
        assert response.template.name == "settings_tab.html"
        soup = BeautifulSoup(response.text, features="html.parser")
        assert soup.find("h4").text == "Sync Preferences"


async def test_preload():
    pass

