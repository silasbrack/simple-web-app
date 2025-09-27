from starlette.testclient import TestClient


def test_home_page(client: TestClient):
    """Full home page render."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.template.name == "application.html"


def test_home_htmx(client: TestClient):
    """Partial home template render for HTMX."""
    response = client.get("/", headers={"HX-Request": "asdf"})
    assert response.status_code == 200
    assert response.template.name == "index.html"
