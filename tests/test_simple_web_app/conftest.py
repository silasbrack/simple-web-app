from collections.abc import AsyncGenerator

import pytest
from starlette.testclient import TestClient

from simple_web_app.main import app


@pytest.fixture()
def client() -> AsyncGenerator[TestClient, None]:
    with TestClient(app) as client:
        # Application's lifespan is called on entering the block
        yield client
