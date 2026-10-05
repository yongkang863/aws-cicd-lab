from app import app


def test_homepage():
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert "My CI/CD Lab" in response.text
    assert "Version: 1.0.1" in response.text


def test_health():
    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "version": "1.0.1",
    }


def test_unknown_page():
    response = app.test_client().get("/does-not-exist")

    assert response.status_code == 404
