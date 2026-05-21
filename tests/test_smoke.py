from django.test import Client


def test_home_page_renders():
    response = Client().get("/")
    assert response.status_code == 200
    assert "Plot Portal" in response.content.decode()

