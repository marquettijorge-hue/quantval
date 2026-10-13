import copy
import json
from datetime import date
from pathlib import Path

import pytest

from fetch_financials import UnsupportedCompany, build_financials, metric, normalize_ticker, number

CASES = json.loads((Path(__file__).parent / "fixtures/annual_cases.json").read_text())
TODAY = date(2026, 10, 13)


def build(symbol, data=None):
    case = copy.deepcopy(data or CASES[symbol])
    return build_financials(symbol, case["cik"], case["companyfacts"], case["submissions"], today=TODAY)


def by_id(result, key):
    return next(m for m in result["metrics"] if m["id"] == key)


@pytest.mark.parametrize("symbol,revenues,growth,end", [
    ("AAPL", 416161e6, 416161/391035-1, "2025-09-27"),
    ("MSFT", 331839e6, 331839/281724-1, "2026-06-30"),
    ("NVDA", 215938e6, 215938/130497-1, "2026-01-25"),
    ("JPM", 182447e6, 182447/177556-1, "2025-12-31"),
    ("NFLX", 45183036e3, 45183036/39000966-1, "2025-12-31"),
])
def test_frozen_official_annual_facts(symbol, revenues, growth, end):
    result = build(symbol)
    assert result["period"]["end"] == end
    assert by_id(result, "revenue")["value"] == revenues
    assert by_id(result, "revenue_growth")["value"] == pytest.approx(growth)
    assert by_id(result, "revenue_growth")["kind"] == "calculated"
    assert len(result["metrics"]) == 6
    for m in result["metrics"]:
        assert m["status"] == "available"
        assert m["sources"]
        for source in m["sources"]:
            assert source["url"].startswith("https://www.sec.gov/Archives/edgar/data/")
            assert source["accession"].replace("-", "") in source["url"]
            assert source["filed_at"] <= TODAY.isoformat()
            assert isinstance(source["value"], float)


@pytest.mark.parametrize("symbol,cfo,capex,operating", [
    ("AAPL", 111482e6, 12715e6, 133050/416161),
    ("MSFT", 182935e6, 115948e6, 155237/331839),
    ("NVDA", 102718e6, 6042e6, 130387/215938),
    ("NFLX", 10149273e3, 688220e3, 13326603/45183036),
])
def test_cash_flow_and_operating_margin(symbol, cfo, capex, operating):
    result = build(symbol)
    assert by_id(result, "fcf")["value"] == cfo - capex
    assert by_id(result, "fcf_margin")["value"] == pytest.approx((cfo-capex)/by_id(result, "revenue")["value"])
    assert by_id(result, "operating_margin")["value"] == pytest.approx(operating)


def test_bank_never_gets_industrial_cash_flow_or_valuation():
    result = build("JPM")
    ids = {m["id"] for m in result["metrics"]}
    assert result["financial_sector"]
    assert {"roe", "equity_assets", "net_margin"} <= ids
    assert "fcf" not in ids and "operating_margin" not in ids
    assert result["valuation"]["status"] == "not_available"
    assert by_id(result, "roe")["value"] == pytest.approx(57048/((362438+344758)/2))
    assert "CET1" in by_id(result, "equity_assets")["formula"]


def test_missing_capex_is_not_zero():
    case = copy.deepcopy(CASES["AAPL"])
    del case["companyfacts"]["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
    result = build("AAPL", case)
    assert by_id(result, "fcf")["value"] is None
    assert by_id(result, "fcf_margin")["status"] == "missing"


def test_real_zero_and_negative_cash_flow_are_preserved():
    case = copy.deepcopy(CASES["AAPL"])
    values = case["companyfacts"]["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"]
    for value in values:
        if value.get("start") == "2024-09-29" and value["end"] == "2025-09-27":
            value["val"] = 0
    assert by_id(build("AAPL", case), "fcf")["value"] == -12715e6
    assert metric("cash", "Cash", 0, "USD", "", [], kind="reported")["status"] == "available"


def test_future_and_quarterly_facts_do_not_replace_annuals():
    case = copy.deepcopy(CASES["MSFT"])
    values = case["companyfacts"]["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    base = copy.deepcopy(values[-1])
    values.append({**base, "start": "2026-07-01", "end": "2027-06-30", "filed": "2027-07-29", "val": 999999})
    values.append({**base, "start": "2026-07-01", "end": "2026-09-30", "filed": "2026-10-12", "form": "10-Q", "val": 123})
    assert by_id(build("MSFT", case), "revenue")["value"] == 331839e6


def test_missing_annuals_stop_analysis():
    with pytest.raises(UnsupportedCompany):
        build_financials("TEST", 1, {"facts": {}}, {}, today=TODAY)


def test_absent_comparative_never_uses_a_projection_or_current_value():
    case = copy.deepcopy(CASES["AAPL"])
    facts = case["companyfacts"]["facts"]["us-gaap"]
    for tag in ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]:
        if tag in facts:
            facts[tag]["units"]["USD"] = [r for r in facts[tag]["units"]["USD"] if r.get("start") == "2024-09-29" and r["end"] == "2025-09-27"]
    result = build("AAPL", case)
    assert by_id(result, "revenue")["status"] == "available"
    assert by_id(result, "revenue_growth")["value"] is None
    assert by_id(result, "revenue_growth")["status"] == "missing"


@pytest.mark.parametrize("value", [None, True, "wrong", float("nan"), float("inf")])
def test_nonfinancial_numbers_never_become_zero(value):
    assert number(value) is None


@pytest.mark.parametrize("value", ["", "AAPL/../", "AAPL vs MSFT", "<script>", "MSFT?x=1"])
def test_invalid_ticker_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_ticker(value)


def test_share_class_symbol_normalization():
    assert normalize_ticker(" brk.b ") == "BRK-B"
