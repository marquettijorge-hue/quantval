from datetime import datetime, timezone
import pytest
import fetch_financials as f


def test_quote_preserves_its_provider_timestamp_and_currency(monkeypatch):
    stamp = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(f,"request_json",lambda *a,**k:{"chart":{"result":[{"meta":{"regularMarketPrice":12.3,"regularMarketTime":stamp,"currency":"CAD"}}]}})
    result = f.fetch_quote("TEST")
    assert result["price"] == 12.3 and result["currency"] == "CAD"
    assert result["as_of"].startswith("2026-01-01")
    assert result["status"] == "stale"


@pytest.mark.parametrize("price", [None, 0, -1, float("nan")])
def test_unusable_quote_does_not_become_zero(monkeypatch, price):
    monkeypatch.setattr(f,"request_json",lambda *a,**k:{"chart":{"result":[{"meta":{"regularMarketPrice":price,"regularMarketTime":1,"currency":"USD"}}]}})
    result = f.fetch_quote("TEST")
    assert result["status"] == "missing" and result["price"] is None


def test_provider_failure_does_not_fabricate_a_quote(monkeypatch):
    def fail(*a,**k):raise f.ProviderUnavailable("Source unavailable")
    monkeypatch.setattr(f,"request_json",fail)
    assert f.fetch_quote("TEST")["price"] is None


@pytest.mark.parametrize("payload", [[], {"chart":None}, {"chart":{"result":None}}, {"chart":{"result":[None]}}, {"chart":{"result":[{"meta":None}]}}])
def test_malformed_optional_quote_does_not_block_balances(monkeypatch, payload):
    monkeypatch.setattr(f,"request_json",lambda *a,**k:payload)
    assert f.fetch_quote("TEST")["status"] == "missing"
