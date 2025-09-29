import os
import unittest.mock
from collections.abc import AsyncGenerator

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def test_env() -> dict[str, str]:
    return {
        "DEBUG": "true",
        "DATABASE_PATH": ":memory:",
    }


@pytest.fixture()
def client(test_env: dict[str, str]) -> AsyncGenerator[TestClient, None]:
    with unittest.mock.patch.dict(os.environ, test_env, clear=True):
        from simple_web_app.app import app
        with TestClient(app) as client:
            # Application's lifespan is called on entering the block
            yield client

