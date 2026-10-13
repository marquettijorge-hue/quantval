import copy
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
import server
from fetch_financials import ProviderUnavailable, UnsupportedCompany


@pytest.fixture(autouse=True)
def empty_cache():
    server.CACHE.clear()
    server._inflight.clear()


def test_health_identifies_the_deployed_commit(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a"*40)
    data = TestClient(server.app).get("/health").json()
    assert data["version"] == "3.0.0" and data["commit"] == "a"*40


def test_course_cta_matches_its_actual_destination(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.delenv("TALLER_URL", raising=False)
    data = client.get("/api/config").json()
    assert data["taller_label"] == "Pedime información del Taller"
    monkeypatch.setenv("TALLER_URL", "https://example.com/taller")
    assert client.get("/api/config").json()["taller_label"] == "Ver Taller de Inversiones con IA"
    monkeypatch.setenv("TALLER_URL", "javascript:alert(1)")
    assert client.get("/api/config").json()["taller_url"].startswith("https://www.instagram.com/")


def test_cache_does_not_change_source_data_or_confuse_tickers(monkeypatch):
    calls = []
    def fake(symbol):
        calls.append(symbol)
        return {"symbol": symbol, "metrics": [{"value": None}], "retrieved_at": "original"}
    monkeypatch.setattr(server, "analyze_ticker", fake)
    client = TestClient(server.app)
    first = client.get("/api/evaluate/aapl").json()
    first["metrics"][0]["value"] = 99
    second = client.get("/api/evaluate/AAPL").json()
    third = client.get("/api/evaluate/MSFT").json()
    assert calls == ["AAPL", "MSFT"]
    assert second["cache"]["hit"] and second["metrics"][0]["value"] is None
    assert third["symbol"] == "MSFT" and second["retrieved_at"] == "original"


def test_two_identical_queries_share_one_provider_call(monkeypatch):
    calls = []
    def fake(symbol):
        calls.append(symbol)
        time.sleep(.05)
        return {"symbol": symbol}
    monkeypatch.setattr(server, "analyze_ticker", fake)
    def request(_):
        return TestClient(server.app).get("/api/evaluate/AAPL").status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(request, range(2))) == [200, 200]
    assert calls == ["AAPL"]


@pytest.mark.parametrize("error,code", [(UnsupportedCompany("No disponible"),404),(ProviderUnavailable("Fuente no disponible"),503),(RuntimeError("secret debug"),500)])
def test_provider_errors_are_actionable_and_do_not_leak_details(monkeypatch, error, code):
    def fake(_):
        raise error
    monkeypatch.setattr(server, "analyze_ticker", fake)
    response = TestClient(server.app).get("/api/evaluate/AAPL")
    assert response.status_code == code
    assert "secret debug" not in response.text
    assert not server._inflight


def test_bad_ticker_never_calls_provider(monkeypatch):
    monkeypatch.setattr(server,"analyze_ticker",lambda _: pytest.fail("Provider called"))
    assert TestClient(server.app).get("/api/evaluate/XYZ!bad").status_code == 422


def test_frontend_and_source_files_are_served():
    client = TestClient(server.app)
    response = client.get("/")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_manual_price_query_parameter(monkeypatch):
    calls = []
    def fake(symbol, manual_price=None):
        calls.append((symbol, manual_price))
        return {"symbol": symbol, "quote": {"price": manual_price, "is_manual": True}}
    monkeypatch.setattr(server, "analyze_ticker", fake)
    client = TestClient(server.app)
    res = client.get("/api/evaluate/AAPL?manual_price=250.5").json()
    assert calls == [("AAPL", 250.5)]
    assert res["quote"]["price"] == 250.5
    assert res["quote"]["is_manual"] is True

