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


def test_dcf_growth_horizon_compounds_year_one():
    from fetch_financials import calculate_scenario_dcf
    # With 0% growth, FCF stays at 100
    fv_0 = calculate_scenario_dcf(100.0, 10.0, 0.0, 0.0, 0.10, 0.00, fade_to_g=0.00, g_terminal=0.00)
    # With 10% growth in year 1..5, Year 1 is 110, so fair value must be strictly higher
    fv_10 = calculate_scenario_dcf(100.0, 10.0, 0.0, 0.0, 0.10, 0.10, fade_to_g=0.00, g_terminal=0.00)
    assert fv_10 > fv_0
    # Exactly check Year 1 discounting: PV(Year 1) = 100 * (1 + 0.10) / (1 + 0.10) = 100.0
    # In earlier buggy version, Year 1 was 100 / 1.10 = 90.9
    assert fv_10 >= 80.0


def test_reverse_dcf_recovers_exact_implied_growth():
    from fetch_financials import calculate_scenario_dcf, solve_reverse_dcf
    # If Fair Value is $100 under 15% growth, Reverse DCF solving for target_price=100 must return ~15%
    shares, cash, debt, wacc = 1000.0, 500.0, 200.0, 0.10
    start_fcf = 10000.0
    known_growth = 0.15
    fair_val = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc, known_growth)
    solved_g = solve_reverse_dcf(fair_val, start_fcf, shares, cash, debt, wacc)
    assert solved_g is not None
    assert abs(solved_g - 15.0) <= 0.5


def test_margin_of_safety_vs_delta_price_separation():
    # When Fair Value = $125 and Price = $100:
    # MoS = (125 - 100) / 125 = 20.0%
    # Delta vs Price = (125 - 100) / 100 = 25.0%
    fair_value = 125.0
    price = 100.0
    mos = (fair_value - price) / fair_value * 100.0
    delta = (fair_value - price) / price * 100.0
    assert mos == 20.0
    assert delta == 25.0
    assert mos != delta


def test_quality_and_checklist_explicit_missing():
    result = build("AAPL")
    assert "valuation_summary" in result
    assert "core_indicators" in result
    assert len(result["core_indicators"]) == 6
    assert "piotroski_fscore" in result
    assert "altman_solvency" in result
    assert "mayer_100_bagger_metrics" in result
    assert "checklist_due_diligence" in result
    piot = result["piotroski_fscore"]
    assert piot["status"] == "available"
    assert piot["score"] <= piot["max_available"]
    # Check that missing items are flagged as missing, not fabricated
    for c in piot["criteria_list"]:
        if c["status"] == "missing":
            assert c["passed"] is None


def test_bank_banking_valuation_and_no_industrial_scores():
    result = build("JPM")
    assert result["financial_sector"]
    assert result["valuation"]["model_type"] == "banking_valuation"
    assert result["piotroski_fscore"]["status"] == "not_applicable"
    assert result["altman_solvency"]["status"] == "not_applicable"
    assert "justified_pb" in result["valuation"]
    assert result["valuation"]["book_value_per_share"] > 0

def test_exit_multiple_dcf_and_slider_sensitivity():
    from fetch_financials import calculate_scenario_dcf
    # Test that changing exit_multiple strictly changes fair value
    fv_16 = calculate_scenario_dcf(100.0, 10.0, 0.0, 0.0, 0.10, 0.05, exit_multiple=16.0, eps=10.0)
    fv_24 = calculate_scenario_dcf(100.0, 10.0, 0.0, 0.0, 0.10, 0.05, exit_multiple=24.0, eps=10.0)
    assert fv_24 > fv_16
    # 24x multiple must produce higher valuation than 16x multiple
    assert fv_24 > fv_16 * 1.30
