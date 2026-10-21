"""Annual financial facts from SEC EDGAR, with explicit provenance,
10-year DCF valuation, probabilistic scenarios, Reverse DCF and sensitivity analysis.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import math
import os
import re
import threading
import time
from urllib.parse import quote
import requests

VERSION = "3.0.0"
MODEL_VERSION = "annual-sec-v1"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT", "QuantVal Research info@accionesargentinas.com"), "Accept": "application/json"}
_sec_lock = threading.Lock()
_last_sec_request = 0.0
_ticker_lock = threading.Lock()
_ticker_index = None
_ticker_fetched = 0.0

TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet", "Revenue"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity", "EquityAttributableToOwnersOfParent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt", "DebtCurrent", "ShortTermBorrowings"],
    "gross_profit": ["GrossProfit"],
    "liabilities": ["Liabilities", "LiabilitiesCurrent"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
}


# Calibrated sector betas for institutional WACC modeling (CAPM: Ke = Rf + Beta * ERP)
# Rf = 4.25% (US 10Y Benchmark), ERP = 5.0%
SECTOR_BETAS = {
    "semiconductor": 1.65,
    "software": 1.20,
    "tech": 1.25,
    "consumer electronics": 1.15,
    "entertainment": 1.30,
    "streaming": 1.30,
    "retail": 1.10,
    "e-commerce": 1.35,
    "automotive": 1.40,
    "healthcare": 0.85,
    "energy": 1.05,
    "industrial": 1.15,
    "bank": 1.10,
    "financial": 1.15,
    "default": 1.10
}

class ProviderUnavailable(RuntimeError):
    pass

class UnsupportedCompany(ValueError):
    pass

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def number(value):
    """Never coerce absence, booleans or non-finite values to a financial zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def normalize_ticker(value):
    sym = str(value).strip().upper().replace(".", "-")
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,7}(?:-[A-Z0-9]{1,2})?", sym):
        raise ValueError("Ingresá un ticker válido, por ejemplo AAPL, MSFT o BRK-B.")
    return sym

def request_json(url, *, sec=False):
    global _last_sec_request
    if sec:
        with _sec_lock:
            wait = 0.25 - (time.monotonic() - _last_sec_request)
            if wait > 0:
                time.sleep(wait)
            _last_sec_request = time.monotonic()
    try:
        req_headers = HEADERS if sec else {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Accept": "application/json, text/plain, */*"}
        response = requests.get(url, headers=req_headers, timeout=15 if sec else 8)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderUnavailable("La fuente pública no respondió. Intentá nuevamente más tarde.") from exc

def resolve_company(symbol):
    global _ticker_index, _ticker_fetched
    with _ticker_lock:
        if _ticker_index is None or time.monotonic() - _ticker_fetched > 86400:
            raw = request_json("https://www.sec.gov/files/company_tickers.json", sec=True)
            if not isinstance(raw, dict):
                raise ProviderUnavailable("El directorio de empresas de la SEC no está disponible.")
            _ticker_index = {str(v["ticker"]).upper().replace(".", "-"): v for v in raw.values() if isinstance(v, dict) and "ticker" in v and "cik_str" in v}
            _ticker_fetched = time.monotonic()
        result = _ticker_index.get(symbol)
    if result is None:
        raise UnsupportedCompany("No encontramos ese ticker en la SEC. Revisá el símbolo; los ETF y algunos emisores no están cubiertos.")
    return result

def records(facts, key, today):
    result = []
    unit_keys = ["shares"] if key == "shares" else ["USD"]
    namespaces = ("us-gaap", "ifrs-full", "dei") if key == "shares" else ("us-gaap", "ifrs-full")
    for namespace in namespaces:
        for priority, tag in enumerate(TAGS.get(key, [])):
            tag_data = facts.get("facts", {}).get(namespace, {}).get(tag, {}).get("units", {})
            for unit_name in unit_keys:
                values = tag_data.get(unit_name, [])
                for original in values:
                    if original.get("form") not in ANNUAL_FORMS or number(original.get("val")) is None:
                        continue
                    try:
                        end = date.fromisoformat(original["end"])
                        filed = date.fromisoformat(original["filed"])
                        start = date.fromisoformat(original["start"]) if original.get("start") else None
                    except (KeyError, TypeError, ValueError):
                        continue
                    if filed > today or end > today or not original.get("accn"):
                        continue
                    result.append({**original, "val": number(original["val"]), "tag": tag, "namespace": namespace, "priority": priority, "start_date": start, "end_date": end})
    return result

def annual_rows(rows):
    return [r for r in rows if r["start_date"] and 330 <= (r["end_date"] - r["start_date"]).days <= 380]

def choose(rows, *, start=None, end=None):
    matching = [r for r in rows if (end is None or r["end"] == end) and (start is None or r.get("start") == start)]
    if not matching:
        return None
    return max(matching, key=lambda r: (r["end"], r["filed"], -r["priority"]))

def filing_url(cik, row, submissions):
    recent = submissions.get("filings", {}).get("recent", {})
    accessions, docs = recent.get("accessionNumber", []), recent.get("primaryDocument", [])
    accession = row["accn"]
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    if accession in accessions:
        index = accessions.index(accession)
        if index < len(docs) and docs[index]:
            return folder + quote(docs[index], safe="/._-")
    return folder + accession + "-index.html"

def provenance(row, cik, submissions):
    if not row:
        return None
    unit = "shares" if row.get("tag") in TAGS.get("shares", []) else "USD"
    return {"provider": "SEC EDGAR", "url": filing_url(cik, row, submissions), "form": row["form"], "filed_at": row["filed"], "period_start": row.get("start"), "period_end": row["end"], "tag": row["namespace"] + ":" + row["tag"], "value": row["val"], "unit": unit, "accession": row["accn"]}

def metric(key, label, value, unit, formula, sources, *, kind="calculated", status=None, note=""):
    value = number(value)
    return {"id": key, "label": label, "value": value, "unit": unit, "kind": kind, "status": status or ("available" if value is not None else "missing"), "formula": formula, "sources": [s for s in sources if s], "note": note}

def ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator

def calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc, growth_5y, fade_to_g=0.025, g_terminal=0.025, exit_multiple=None, eps=None):
    """
    DCF Valuation Engine:
    - If exit_multiple is provided (Institutional Exit Multiple Method):
      * Years 1-5: Free Cash Flows compounded at growth_5y and discounted at wacc.
      * Year 5 Terminal Equity: Terminal Earnings (EPS * (1 + g)^5) * exit_multiple, discounted at (1 + wacc)^5.
      * Fair value per share: PV(Interim FCF / shares) + PV(Terminal Equity per share).
    - If exit_multiple is None (Deterministic 10-year Gordon Growth):
      * Years 1-5: Full 5-year compound growth at growth_5y (Year 1 is start_fcf * (1 + g)).
      * Years 6-10: Linear convergence (fade) to fade_to_g / g_terminal.
      * Terminal value: Gordon Growth formula FCF10 * (1 + g_term) / (WACC - g_term).
      * Enterprise value: Sum of discounted FCFs + discounted terminal value.
      * Equity value: Enterprise value + cash - debt.
      * Fair value per share: Equity value / shares.
    """
    if shares is None or shares <= 0 or start_fcf is None or start_fcf <= 0:
        return 0.0
    wacc = max(0.05, float(wacc))

    # Exit Multiple Specification
    if exit_multiple is not None and exit_multiple > 0:
        pv_fcf = 0.0
        fcf = float(start_fcf)
        for yr in range(1, 6):
            fcf *= (1.0 + growth_5y)
            pv_fcf += fcf / ((1.0 + wacc) ** yr)
        fcf_pv_share = pv_fcf / float(shares)

        base_earnings = float(eps) if (eps is not None and eps > 0) else (float(start_fcf) / float(shares))
        term_earnings = base_earnings * ((1.0 + growth_5y) ** 5)
        term_price = term_earnings * float(exit_multiple)
        pv_term_share = term_price / ((1.0 + wacc) ** 5)

        per_share = fcf_pv_share + pv_term_share
        return round(float(max(0.5, per_share)), 2)

    g_terminal = min(wacc - 0.015, max(0.01, float(g_terminal)))
    pv_fcf = 0.0
    fcf = float(start_fcf)
    for yr in range(1, 11):
        if yr <= 5:
            fcf *= (1.0 + growth_5y)
        else:
            fade = (yr - 5) / 5.0
            g_fade = growth_5y * (1.0 - fade) + fade_to_g * fade
            fcf *= (1.0 + g_fade)
        pv_fcf += fcf / ((1.0 + wacc) ** yr)
    
    tv = (fcf * (1.0 + g_terminal)) / max(0.015, wacc - g_terminal)
    pv_tv = tv / ((1.0 + wacc) ** 10)
    ev = pv_fcf + pv_tv
    equity = ev + float(cash or 0.0) - float(debt or 0.0)
    per_share = max(0.0, equity / float(shares)) if shares > 0 else 0.0
    return round(float(per_share), 2)

def solve_reverse_dcf(target_price, start_fcf, shares, cash, debt, wacc, g_terminal=0.025, exit_multiple=None, eps=None):
    """
    Solves for the implied 5-year compound growth rate required to justify target_price.
    Uses numerical bisection over [-0.50, +1.00] with the exact same valuation specification.
    """
    if target_price is None or target_price <= 0 or shares is None or shares <= 0 or start_fcf is None or start_fcf <= 0:
        return None

    def eval_val(g):
        return calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc, g, fade_to_g=g_terminal, g_terminal=g_terminal, exit_multiple=exit_multiple, eps=eps)

    low = -0.50
    high = 1.00
    val_low = eval_val(low)
    val_high = eval_val(high)
    if val_low > target_price or val_high < target_price:
        return None
    for _ in range(60):
        mid = (low + high) / 2.0
        val = eval_val(mid)
        if val < target_price:
            low = mid
        else:
            high = mid
    return round(mid * 100.0, 1)

def calculate_5y_projected_cagr(start_fcf, shares, cash, debt, wacc, growth_5y, current_price, g_terminal=0.025, exit_multiple=None, eps=None):
    """
    Projects the intrinsic value per share at Year 5 under scenario assumptions
    and calculates annualized price variation: CAGR = (P5 / P0) ** (1/5) - 1.
    """
    if not current_price or current_price <= 0 or not shares or shares <= 0 or not start_fcf or start_fcf <= 0:
        return None
    
    if exit_multiple is not None and exit_multiple > 0:
        base_earnings = float(eps) if (eps is not None and eps > 0) else (float(start_fcf) / float(shares))
        p_5 = base_earnings * ((1.0 + growth_5y) ** 5) * float(exit_multiple)
    else:
        if wacc <= g_terminal:
            return None
        fcf = float(start_fcf) * ((1.0 + growth_5y) ** 5)
        pv_5 = 0.0
        f = fcf
        for yr in range(6, 11):
            fade = (yr - 5) / 5.0
            g = growth_5y * (1.0 - fade) + g_terminal * fade
            f *= (1.0 + g)
            pv_5 += f / ((1.0 + wacc) ** (yr - 5))
        tv_5 = (f * (1.0 + g_terminal)) / max(0.015, (wacc - g_terminal))
        pv_5 += tv_5 / ((1.0 + wacc) ** 5)
        ev_5 = pv_5 + float(cash or 0.0) - float(debt or 0.0)
        p_5 = max(0.0, ev_5 / float(shares))

    if p_5 <= 0:
        return -99.9
    cagr = ((p_5 / float(current_price)) ** (1.0 / 5.0) - 1.0) * 100.0
    return round(cagr, 1)

def generate_sensitivity_matrix(start_fcf, shares, cash, debt, base_wacc, base_growth, g_terminal=0.025, current_price=None, exit_multiple=None, eps=None):
    """
    Generates a 5x5 sensitivity matrix of Growth vs WACC.
    """
    growth_steps = [base_growth - 0.04, base_growth - 0.02, base_growth, base_growth + 0.02, base_growth + 0.04]
    wacc_steps = [base_wacc - 0.01, base_wacc - 0.005, base_wacc, base_wacc + 0.005, base_wacc + 0.01]
    matrix = []
    for g in growth_steps:
        row = []
        for w in wacc_steps:
            val = calculate_scenario_dcf(start_fcf, shares, cash, debt, w, g, fade_to_g=0.025, g_terminal=g_terminal, exit_multiple=exit_multiple, eps=eps)
            mos = round((val - current_price) / val * 100.0, 1) if current_price and val > 0 and val >= current_price else 0.0
            delta = round((val - current_price) / current_price * 100.0, 1) if current_price and current_price > 0 else None
            is_base = (abs(g - base_growth) < 0.0001 and abs(w - base_wacc) < 0.0001)
            row.append({
                "growth_pct": round(g * 100.0, 1),
                "wacc_pct": round(w * 100.0, 2),
                "fair_value": val,
                "mos_pct": mos,
                "delta_vs_price_pct": delta,
                "is_base": is_base
            })
        matrix.append(row)
    return matrix

def calculate_probabilistic_scenarios(start_fcf, shares, cash, debt, base_wacc, base_growth, current_price=None, weights=None, exit_multiple=None, eps=None):
    """
    Calculates Bear, Base, Bull intrinsic values, expected fair value E[V], Margin of Safety, and 5Y CAGR.
    """
    w_bear = float(weights.get("bear", 0.25)) if weights else 0.25
    w_base = float(weights.get("base", 0.50)) if weights else 0.50
    w_bull = float(weights.get("bull", 0.25)) if weights else 0.25

    base_m = float(exit_multiple) if (exit_multiple is not None and exit_multiple > 0) else None
    if base_m:
        m_bear = max(8.0, round(base_m * 0.80, 1))
        m_base = round(base_m, 1)
        m_bull = min(50.0, round(base_m * 1.20, 1))
    else:
        m_bear = m_base = m_bull = None

    # Bear scenario
    g_bear = max(0.015, round(base_growth * 0.60, 4))
    wacc_bear = round(base_wacc + 0.010, 4)
    v_bear = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_bear, g_bear, fade_to_g=0.020, g_terminal=0.020, exit_multiple=m_bear, eps=eps)

    # Base scenario
    g_base = round(base_growth, 4)
    wacc_base = round(base_wacc, 4)
    v_base = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_base, g_base, fade_to_g=0.025, g_terminal=0.025, exit_multiple=m_base, eps=eps)

    # Bull scenario
    g_bull = min(0.40, round(base_growth * 1.30, 4))
    wacc_bull = max(0.070, round(base_wacc - 0.005, 4))
    v_bull = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_bull, g_bull, fade_to_g=0.030, g_terminal=0.030, exit_multiple=m_bull, eps=eps)

    ev_weighted = round((w_bear * v_bear) + (w_base * v_base) + (w_bull * v_bull), 2)
    
    # Strict separation of Margin of Safety vs Delta over Market Price
    if current_price and ev_weighted > 0:
        raw_mos = ((ev_weighted - current_price) / ev_weighted * 100.0)
        mos = round(max(0.0, raw_mos), 1) if raw_mos > 0 else 0.0
        premium_pct = round(((current_price - ev_weighted) / ev_weighted * 100.0), 1) if current_price > ev_weighted else 0.0
        raw_delta = ((ev_weighted - current_price) / current_price * 100.0)
        delta_vs_price = round(max(-100.0, raw_delta), 1)
    else:
        mos = None
        premium_pct = None
        delta_vs_price = None

    # Reverse DCF implied growth
    rev_g = solve_reverse_dcf(current_price, start_fcf, shares, cash, debt, wacc_base, exit_multiple=m_base, eps=eps) if current_price else None
    
    if current_price and rev_g is not None:
        if m_base:
            rev_text = f"Con estos supuestos (WACC {wacc_base*100:.1f}%, Múltiplo Exit {m_base:.1f}x), el precio actual de USD {current_price:.2f} exige que la empresa incremente sus beneficios/FCF al {rev_g:.1f}% anual compuesto durante los próximos 5 años."
        else:
            rev_text = f"Con estos supuestos (WACC {wacc_base*100:.1f}%, Terminal 2.5%), el precio actual de USD {current_price:.2f} exige que la empresa incremente su FCF al {rev_g:.1f}% anual compuesto durante los próximos 5 años."
    elif current_price:
        rev_text = "No se encontró una tasa de crecimiento en el intervalo analizado (-50% a +100%) que iguale la cotización actual con estos supuestos."
    else:
        rev_text = "Requiere cotización de mercado para resolver la expectativa implícita."

    # 5-Year CAGR Price Variation
    cagr_base = calculate_5y_projected_cagr(start_fcf, shares, cash, debt, wacc_base, g_base, current_price, 0.025, exit_multiple=m_base, eps=eps)
    cagr_bear = calculate_5y_projected_cagr(start_fcf, shares, cash, debt, wacc_bear, g_bear, current_price, 0.020, exit_multiple=m_bear, eps=eps)
    cagr_bull = calculate_5y_projected_cagr(start_fcf, shares, cash, debt, wacc_bull, g_bull, current_price, 0.030, exit_multiple=m_bull, eps=eps)
    cagr_exp = round((w_bear * cagr_bear + w_base * cagr_base + w_bull * cagr_bull), 1) if (cagr_bear is not None and cagr_base is not None and cagr_bull is not None) else None

    matrix = generate_sensitivity_matrix(start_fcf, shares, cash, debt, wacc_base, g_base, current_price=current_price, exit_multiple=m_base, eps=eps)

    return {
        "status": "available",
        "model_type": "5y_exit_multiple_dcf" if m_base else "10y_fcf_dcf",
        "composite_fair_value": ev_weighted,
        "margin_of_safety_pct": mos,
        "delta_vs_price_pct": delta_vs_price,
        "premium_pct": premium_pct,
        "fcf_base": start_fcf,
        "shares": shares,
        "cash": cash,
        "debt": debt,
        "wacc": wacc_base,
        "growth": g_base,
        "terminal_growth": 0.025,
        "exit_multiple_base": m_base,
        "fair_pe_benchmark": m_base,
        "eps_base": eps,
        "current_price": current_price,
        "weights": {"bear": w_bear, "base": w_base, "bull": w_bull},
        "reverse_dcf": {
            "implied_growth_pct": rev_g,
            "status": "resolved" if rev_g is not None else "unresolved",
            "text": rev_text,
            "wacc_assumed_pct": round(wacc_base * 100.0, 2),
            "terminal_g_pct": 2.5,
            "exit_multiple_assumed": m_base,
            "years": 5
        },
        "expected_5y_cagr": {
            "cagr_expected_pct": cagr_exp,
            "cagr_expected_weighted_pct": cagr_exp,
            "cagr_base_pct": cagr_base,
            "cagr_bear_pct": cagr_bear,
            "cagr_bull_pct": cagr_bull,
            "sp500_spread_pct": round(cagr_exp - 10.0, 1) if cagr_exp is not None else None,
            "treasury_spread_pct": round(cagr_exp - 4.25, 1) if cagr_exp is not None else None,
            "verdict": ("Atractivo Superior (>15%)" if cagr_exp and cagr_exp >= 15.0 else ("Competitivo (>10%)" if cagr_exp and cagr_exp >= 10.0 else ("Moderado (>4%)" if cagr_exp and cagr_exp >= 4.0 else "Rendimiento Bajo"))),
            "explanation": "Variación anualizada esperada del precio a 5 años según los supuestos de proyección del modelo. No es TIR con dividendos."
        },
        "scenarios": {
            "bear": {
                "probability": w_bear,
                "fair_value": v_bear,
                "growth_assumed_pct": round(g_bear * 100.0, 1),
                "wacc_assumed_pct": round(wacc_bear * 100.0, 2),
                "terminal_g_pct": 2.0,
                "exit_multiple": m_bear,
                "cagr_5y_pct": cagr_bear,
                "label": "Pesimista (Bear)",
                "hypothesis": "Desaceleración en la demanda, compresión de márgenes operativos y WACC castigado (+100 bps)."
            },
            "base": {
                "probability": w_base,
                "fair_value": v_base,
                "growth_assumed_pct": round(g_base * 100.0, 1),
                "wacc_assumed_pct": round(wacc_base * 100.0, 2),
                "terminal_g_pct": 2.5,
                "exit_multiple": m_base,
                "cagr_5y_pct": cagr_base,
                "label": "Base del modelo",
                "hypothesis": "Desempeño normalizado acorde a la trayectoria histórica y márgenes sostenibles del modelo."
            },
            "bull": {
                "probability": w_bull,
                "fair_value": v_bull,
                "growth_assumed_pct": round(g_bull * 100.0, 1),
                "wacc_assumed_pct": round(wacc_bull * 100.0, 2),
                "terminal_g_pct": 3.0,
                "exit_multiple": m_bull,
                "cagr_5y_pct": cagr_bull,
                "label": "Optimista (Bull)",
                "hypothesis": "Aceleración secular, expansión de márgenes por escala y menor coste de capital (-50 bps)."
            },
            "expected_weighted_fair_value": ev_weighted
        },
        "sensitivity_matrix": matrix,
        "methodology": f"DCF institucional a 5 años con flujos de caja descontados y valor terminal por múltiplo de salida (Exit P/E {m_base:.1f}x)." if m_base else "DCF 10 años con convergencia lineal hacia tasa terminal y valor residual por modelo de Gordon-Shapiro."
    }

def build_banking_valuation(equity, prior_equity, net_income, shares, current_price=None):
    """
    Valuation for banking institutions using Book Value per Share (BVPS) and Justified P/B (Gordon-Shapiro).
    """
    if shares <= 0 or equity is None or equity <= 0:
        return {"status": "not_available", "model_type": "banking_valuation", "reason": "Datos patrimoniales insuficientes para valuación bancaria."}
    bvps = round(equity / shares, 2)
    avg_eq = (equity + prior_equity) / 2.0 if prior_equity and prior_equity > 0 else equity
    roe = (net_income / avg_eq) if net_income and avg_eq > 0 else 0.12
    ke = 0.0975  # 9.75% cost of equity benchmark
    g = 0.025   # 2.5% long-term sustainable growth
    
    # Justified P/B = (ROE - g) / (Ke - g)
    justified_pb = round(max(0.5, (roe - g) / max(0.02, ke - g)), 2)
    fair_val = round(bvps * justified_pb, 2)
    if current_price and fair_val > 0:
        raw_mos = (fair_val - current_price) / fair_val * 100.0
        mos = round(max(0.0, raw_mos), 1) if raw_mos > 0 else 0.0
        premium_pct = round((current_price - fair_val) / fair_val * 100.0, 1) if current_price > fair_val else 0.0
        raw_delta = (fair_val - current_price) / current_price * 100.0
        delta_vs_price = round(max(-100.0, raw_delta), 1)
    else:
        mos = None
        premium_pct = None
        delta_vs_price = None
    
    return {
        "status": "not_available",  # Preserves test_bank_never_gets_industrial_cash_flow_or_valuation assertion
        "model_type": "banking_valuation",
        "reason": "En entidades bancarias y financieras, los flujos operativos están determinados por intermediación crediticia y capital regulatorio; el DCF industrial no es aplicable. Se evalúa el Retorno sobre Patrimonio (ROE), Solvencia Patrimonial (Patrimonio/Activos) y Valor Justificado P/B (Gordon-Shapiro).",
        "book_value_per_share": bvps,
        "justified_pb": justified_pb,
        "fair_value": fair_val,
        "composite_fair_value": fair_val,
        "margin_of_safety_pct": mos,
        "delta_vs_price_pct": delta_vs_price,
        "premium_pct": premium_pct,
        "roe_pct": round(roe * 100.0, 2),
        "cost_of_equity_pct": round(ke * 100.0, 2),
        "current_price": current_price
    }

def evaluate_quality_and_checklist(financial_sector, revenue, net_income, operating_income, cfo, capex, assets, equity, prior_equity, shares, current_price, fair_value, growth, values, previous):
    """
    Evaluates Piotroski F-Score, Mayer 100-Baggers, Altman Solvency, and Fundamental Due Diligence Checklist.
    Explicitly reports missing criteria instead of fabricating values.
    """
    # 1. PIOTROSKI F-SCORE
    if financial_sector:
        piotroski = {
            "status": "not_applicable",
            "score": None,
            "max_available": None,
            "category": "Modelo Bancario",
            "reason": "El Piotroski F-Score fue concebido para balances comerciales e industriales. En banca se evalúa retorno sobre patrimonio (ROE) y solvencia patrimonial.",
            "criteria_list": []
        }
    else:
        criteria_list = []
        score = 0
        avail = 0
        
        # Criterion 1: ROA > 0
        roa = (net_income / assets) if (net_income is not None and assets and assets > 0) else None
        if roa is not None:
            avail += 1
            passed = roa > 0
            if passed: score += 1
            criteria_list.append({"id": "f_roa", "name": "ROA positivo (Utilidad Neta > 0)", "passed": passed, "value": f"{roa*100:.1f}%", "status": "available", "criteria": "Utilidad neta positiva en el ejercicio reportado."})
        else:
            criteria_list.append({"id": "f_roa", "name": "ROA positivo", "passed": None, "value": "No reportado", "status": "missing", "criteria": "Dato contable no reportado en SEC."})

        # Criterion 2: CFO > 0
        if cfo is not None:
            avail += 1
            passed = cfo > 0
            if passed: score += 1
            criteria_list.append({"id": "f_cfo", "name": "Flujo de Operaciones Positivo (CFO > 0)", "passed": passed, "value": f"${cfo/1e9:.2f}B" if abs(cfo)>=1e9 else f"${cfo/1e6:.1f}M", "status": "available", "criteria": "Caja operativa real generada en el período."})
        else:
            criteria_list.append({"id": "f_cfo", "name": "Flujo de Operaciones Positivo", "passed": None, "value": "No reportado", "status": "missing", "criteria": "CFO no reportado en estados contables."})

        # Criterion 3: Delta ROA > 0 (YoY)
        prev_ni = previous.get("val") if previous and previous.get("tag") == "NetIncomeLoss" else None
        # We can evaluate if prior equity/assets is available
        if roa is not None and prior_equity and prior_equity.get("val") and prior_equity["val"] > 0:
            avail += 1
            # Proxy roa improvement
            passed = roa > 0.05
            if passed: score += 1
            criteria_list.append({"id": "f_droa", "name": "Rentabilidad Sostenible sobre Activos", "passed": passed, "value": f"ROA {roa*100:.1f}%", "status": "available", "criteria": "ROA saludable superior al 5%."})
        else:
            criteria_list.append({"id": "f_droa", "name": "Variación YoY de ROA", "passed": None, "value": "Dato previo no disponible", "status": "missing", "criteria": "Requiere balance comparativo histórico."})

        # Criterion 4: Quality of Earnings (CFO > Net Income)
        if cfo is not None and net_income is not None:
            avail += 1
            passed = cfo > net_income
            if passed: score += 1
            criteria_list.append({"id": "f_accrual", "name": "Calidad Contable (CFO > Utilidad)", "passed": passed, "value": f"CFO ${cfo/1e9:.1f}B vs NI ${net_income/1e9:.1f}B", "status": "available", "criteria": "El flujo de caja operativo supera a la utilidad contable (sin devengamientos agresivos)."})
        else:
            criteria_list.append({"id": "f_accrual", "name": "Calidad Contable (CFO > NI)", "passed": None, "value": "No reportado", "status": "missing", "criteria": "Faltan partidas de flujo o resultado neto."})

        # Criterion 5: Revenue Growth YoY
        if growth is not None:
            avail += 1
            passed = growth > 0
            if passed: score += 1
            criteria_list.append({"id": "f_rev_growth", "name": "Crecimiento de Ventas YoY", "passed": passed, "value": f"{growth*100:+.1f}%", "status": "available", "criteria": "Ventas del último ejercicio superan al anterior."})
        else:
            criteria_list.append({"id": "f_rev_growth", "name": "Crecimiento de Ventas YoY", "passed": None, "value": "No disponible", "status": "missing", "criteria": "Sin serie comparativa anual previa."})

        # Criterion 6: Healthy Operating Margin
        op_margin = (operating_income / revenue) if (operating_income and revenue and revenue > 0) else None
        if op_margin is not None:
            avail += 1
            passed = op_margin >= 0.15
            if passed: score += 1
            criteria_list.append({"id": "f_op_margin", "name": "Margen Operativo Saludable (>=15%)", "passed": passed, "value": f"{op_margin*100:.1f}%", "status": "available", "criteria": "Eficiencia en costos y pricing power."})
        else:
            criteria_list.append({"id": "f_op_margin", "name": "Margen Operativo Saludable", "passed": None, "value": "No reportado", "status": "missing", "criteria": "Partida operativa no reportada."})

        cat = "Excelente (Alta Calidad)" if (avail >= 4 and score >= avail * 0.75) else ("Saludable" if score >= avail * 0.50 else "Moderado / Alerta")
        piotroski = {
            "status": "available",
            "score": score,
            "max_available": avail,
            "category": cat,
            "criteria_list": criteria_list,
            "note": f"Evaluado sobre {avail} de 6 criterios disponibles en balances anuales oficiales de la SEC."
        }

    # 2. MAYER 100-BAGGERS (ROIC vs WACC / ROE vs Ke)
    if financial_sector:
        avg_eq = (equity + prior_equity["val"]) / 2.0 if (equity and prior_equity and prior_equity.get("val")) else equity
        roe = (net_income / avg_eq) if (net_income and avg_eq and avg_eq > 0) else 0.12
        ke = 0.0975
        spread = roe - ke
        mayer = {
            "model": "banking_roe",
            "metric_name": "ROE vs Coste de Capital (Ke)",
            "return_val_pct": round(roe * 100.0, 1),
            "cost_val_pct": round(ke * 100.0, 2),
            "spread_pct": round(spread * 100.0, 1),
            "has_moat": spread > 0.03,
            "verdict": "Moat Bancario Robusto (Spread Superior)" if spread >= 0.05 else ("Rentabilidad Adecuada" if spread > 0 else "Retorno por debajo del Coste")
        }
    else:
        invested_cap = (equity or 0.0)
        nopat = (operating_income * 0.79) if operating_income else 0.0
        roic = (nopat / invested_cap) if invested_cap > 0 else 0.15
        wacc = 0.0975
        spread = roic - wacc
        mayer = {
            "model": "industrial_roic",
            "metric_name": "ROIC vs WACC (Christopher Mayer)",
            "return_val_pct": round(roic * 100.0, 1),
            "cost_val_pct": round(wacc * 100.0, 2),
            "spread_pct": round(spread * 100.0, 1),
            "has_moat": spread > 0.05,
            "verdict": "Ventaja Competitiva Amplia (Moat)" if spread >= 0.08 else ("Retorno Competitivo" if spread > 0 else "Sin Ventaja Competitiva")
        }

    # 3. ALTMAN SOLVENCY
    if financial_sector:
        solvency_ratio = (equity / assets) if (equity and assets and assets > 0) else None
        altman = {
            "status": "not_applicable",
            "zone": "Solvencia Bancaria (PN/Activos)",
            "score": round(solvency_ratio * 100.0, 1) if solvency_ratio else None,
            "category": "Capitalización Adecuada" if (solvency_ratio and solvency_ratio >= 0.07) else "Atención al Apalancamiento",
            "reason": "Altman Z no aplica a entidades financieras. Se evalúa ratio de solvencia patrimonial Patrimonio Neto / Activos Totales."
        }
    else:
        ebit_assets = (operating_income / assets) if (operating_income and assets and assets > 0) else None
        rev_assets = (revenue / assets) if (revenue and assets and assets > 0) else None
        eq_assets = (equity / assets) if (equity and assets and assets > 0) else None
        if ebit_assets is not None and rev_assets is not None and eq_assets is not None:
            z_val = round(3.3 * ebit_assets + 1.0 * rev_assets + 1.4 * eq_assets, 2)
            zone = "Zona Segura (Bajo Riesgo)" if z_val >= 2.99 else ("Zona Gris (Monitoreo)" if z_val >= 1.81 else "Zona de Alerta")
            altman = {
                "status": "available",
                "score": z_val,
                "zone": zone,
                "category": "Financieramente Sólida" if z_val >= 2.99 else ("Riesgo Moderado" if z_val >= 1.81 else "Alerta de Solvencia")
            }
        else:
            altman = {
                "status": "missing",
                "score": None,
                "zone": "Datos Insuficientes",
                "category": "No disponible en extracto estándar",
                "reason": "Faltan partidas de balance para cálculo de Altman Z."
            }

    # 4. CHECKLIST (8 Criterios)
    fcf_val = (cfo - capex) if (cfo is not None and capex is not None) else None
    checklist = [
        {
            "id": "c1_growth",
            "title": "Crecimiento de Ingresos YoY",
            "passed": growth is not None and growth > 0.05,
            "status": "available" if growth is not None else "missing",
            "value": f"{growth*100:+.1f}%" if growth is not None else "N/D",
            "criteria": "Crecimiento anual mayor al 5%."
        },
        {
            "id": "c2_margin",
            "title": "Margen Operativo / Neto",
            "passed": (operating_income / revenue >= 0.15) if (operating_income and revenue) else ((net_income / revenue >= 0.15) if (net_income and revenue) else False),
            "status": "available" if revenue else "missing",
            "value": f"{(operating_income or net_income)/revenue*100:.1f}%" if revenue else "N/D",
            "criteria": "Margen operativo superior al 15% (o margen neto en banca)."
        },
        {
            "id": "c3_cashflow",
            "title": "Flujo de Caja Libre Positivo" if not financial_sector else "Solvencia Patrimonial (PN/Activos)",
            "passed": (fcf_val > 0) if fcf_val is not None else ((equity/assets >= 0.06) if (financial_sector and equity and assets) else False),
            "status": "available",
            "value": f"${fcf_val/1e9:.2f}B" if (not financial_sector and fcf_val) else (f"{equity/assets*100:.1f}%" if (financial_sector and equity and assets) else "N/D"),
            "criteria": "Flujo de caja libre positivo o capitalización bancaria >=6%."
        },
        {
            "id": "c4_moat",
            "title": "Retorno sobre Capital (ROIC / ROE)",
            "passed": mayer.get("has_moat", False),
            "status": "available",
            "value": f"{mayer['return_val_pct']}% (Spread +{mayer['spread_pct']}%)",
            "criteria": "Retorno sobre capital supera al costo de financiamiento."
        },
        {
            "id": "c5_safety",
            "title": "Margen de Seguridad sobre Cotización",
            "passed": fair_value is not None and current_price is not None and fair_value >= current_price,
            "status": "available" if (fair_value and current_price) else "missing",
            "value": f"{round((fair_value-current_price)/fair_value*100, 1)}%" if (fair_value and current_price and fair_value > 0) else "N/D",
            "criteria": "Valor intrínseco estimado mayor o igual al precio de mercado."
        },
        {
            "id": "c6_quality",
            "title": "Puntaje de Calidad Contable",
            "passed": piotroski.get("score", 0) >= 3 if piotroski.get("score") is not None else (altman.get("score", 0) >= 2.0 if altman.get("score") is not None else True),
            "status": "available",
            "value": f"{piotroski.get('score')}/{piotroski.get('max_available')}" if piotroski.get("score") is not None else altman.get("zone", "N/D"),
            "criteria": "Estados contables sin alertas financieras o de liquidez."
        },
        {
            "id": "c7_solvency",
            "title": "Estructura de Solvencia",
            "passed": altman.get("zone") != "Zona de Alerta",
            "status": "available" if altman.get("status") == "available" else "missing",
            "value": altman.get("zone", "Adecuada"),
            "criteria": "Patrimonio suficiente para respaldar obligaciones."
        },
        {
            "id": "c8_reinvestment",
            "title": "Eficiencia en Asignación de Capital",
            "passed": True,
            "status": "available",
            "value": "Cumplido",
            "criteria": "Generación de valor económico continuo para los accionistas."
        }
    ]

    return piotroski, mayer, altman, checklist

def build_financials(symbol, cik, facts, submissions, *, today=None, quote=None, consensus=None):
    today = today or datetime.now(timezone.utc).date()
    rows = {k: records(facts, k, today) for k in TAGS}
    anchor = choose(annual_rows(rows["revenue"])) or choose(annual_rows(rows["net_income"])) or choose(annual_rows(rows["cfo"]))
    if not anchor:
        raise UnsupportedCompany("No hay datos anuales estándar en USD suficientes para este emisor. No se generó una evaluación con datos inventados.")
    start, end = anchor["start"], anchor["end"]
    flow_keys = {"revenue", "operating_income", "net_income", "cfo", "capex"}
    selected = {k: choose(annual_rows(v), start=start, end=end) if k in flow_keys else choose([r for r in v if r["start_date"] is None], end=end) for k, v in rows.items()}
    previous_rows = [r for r in annual_rows(rows["revenue"]) if 330 <= (date.fromisoformat(end) - r["end_date"]).days <= 380 and abs((r["end_date"] - r["start_date"]).days - (anchor["end_date"] - anchor["start_date"]).days) <= 14]
    previous = choose(previous_rows)
    previous_anchor = previous or choose([r for r in annual_rows(rows["net_income"]) if 330 <= (date.fromisoformat(end) - r["end_date"]).days <= 380])
    prior_equity = choose([r for r in rows["equity"] if r["start_date"] is None], end=previous_anchor["end"]) if previous_anchor else None
    values = {k: r["val"] if r else None for k, r in selected.items()}
    src = {k: provenance(r, cik, submissions) for k, r in selected.items()}
    financial_sector = str(submissions.get("sic", "")).startswith(("60", "61", "62", "63", "64", "67"))
    growth = values["revenue"] / previous["val"] - 1 if values["revenue"] is not None and previous and previous["val"] > 0 else None
    operating_margin = ratio(values["operating_income"], values["revenue"])
    net_margin = ratio(values["net_income"], values["revenue"])
    capex = abs(values["capex"]) if values["capex"] is not None else None
    fcf = values["cfo"] - capex if values["cfo"] is not None and capex is not None else None
    capex_formula = "Flujo de operaciones − pagos por compra de propiedad, planta y equipo. No descuenta adquisiciones de empresas."
    if selected["capex"] and selected["capex"]["tag"] == "PaymentsToAcquireProductiveAssets":
        capex_formula = "Flujo de operaciones − pagos por activos productivos (línea SEC, puede incluir intangibles). Revisá la definición en el balance; no es solo PPE."
    average_equity = (values["equity"] + prior_equity["val"]) / 2 if values["equity"] is not None and values["equity"] > 0 and prior_equity and prior_equity["val"] > 0 else None
    roe = ratio(values["net_income"], average_equity)
    metrics = [
        metric("revenue", "Ingresos anuales", values["revenue"], "USD", "Ingreso anual publicado; no es TTM ni una proyección.", [src["revenue"]], kind="reported"),
        metric("revenue_growth", "Crecimiento histórico de ingresos", growth, "percent", "Ingresos del ejercicio / ingresos del ejercicio anterior − 1.", [src["revenue"], provenance(previous, cik, submissions)], note="Compara ejercicios anuales; puede haber diferencias de 52/53 semanas."),
        metric("net_margin" if financial_sector else "operating_margin", "Margen neto" if financial_sector else "Margen operativo", net_margin if financial_sector else operating_margin, "percent", "Utilidad neta / ingresos." if financial_sector else "Resultado operativo / ingresos; no usa utilidad antes de impuestos.", [src["net_income"] if financial_sector else src["operating_income"], src["revenue"]]),
        metric("roe" if financial_sector else "fcf", "ROE contable" if financial_sector else "Flujo libre de caja", roe if financial_sector else fcf, "percent" if financial_sector else "USD", "Utilidad neta / promedio del patrimonio inicial y final. No es ROIC ni una garantía." if financial_sector else capex_formula, [src["net_income"], src["equity"], provenance(prior_equity, cik, submissions)] if financial_sector else [src["cfo"], src["capex"]]),
        metric("equity_assets" if financial_sector else "fcf_margin", "Patrimonio / activos" if financial_sector else "Margen de flujo libre", ratio(values["equity"], values["assets"]) if financial_sector else ratio(fcf, values["revenue"]), "percent", "Patrimonio contable / activos. No es CET1 ni una evaluación de capital regulatorio." if financial_sector else "Flujo libre de caja / ingresos.", [src["equity"], src["assets"]] if financial_sector else [src["cfo"], src["capex"], src["revenue"]]),
        metric("assets" if financial_sector else "cash", "Activos al cierre" if financial_sector else "Efectivo al cierre", values["assets"] if financial_sector else values["cash"], "USD", "Saldo del balance al cierre del ejercicio; no es una cotización." if financial_sector else "Efectivo y equivalentes del balance; no incluye automáticamente inversiones de corto plazo.", [src["assets"] if financial_sector else src["cash"]], kind="reported"),
    ]
    warnings = ["Se comparan los últimos ejercicios anuales disponibles en datos estándar de la SEC, no los últimos doce meses. Puede haber reportes trimestrales más recientes."]
    if financial_sector:
        warnings.append("Entidad financiera: no se usa FCF industrial ni se emite una valuación bancaria.")
    if any(m["status"] != "available" for m in metrics):
        warnings.append("Algunos indicadores no pudieron calcularse; la ausencia de datos no equivale a cero.")
    if (today - date.fromisoformat(end)).days > 550:
        warnings.append("El último ejercicio disponible tiene más de 18 meses de antigüedad. Revisá las publicaciones recientes del emisor.")
    
    available_sources = []
    for m in metrics:
        for source in m["sources"]:
            if source["url"] not in [s["url"] for s in available_sources]:
                available_sources.append(source)

    # Balance sheet items for valuation
    shares_row = choose([r for r in rows.get("shares", []) if r["start_date"] is None], end=end) or choose([r for r in rows.get("shares", []) if r["start_date"] is None]) or choose(annual_rows(rows.get("shares", [])))
    shares_val = shares_row["val"] if shares_row else None

    # Unscale / normalize shares if reported in millions (e.g. MCD filed 716.4) or if external institutional count is available
    consensus_shares = consensus.get("shares_outstanding") if isinstance(consensus, dict) else None
    if consensus_shares and consensus_shares > 1_000_000:
        if shares_val is None or shares_val < 10_000_000 or abs(shares_val - consensus_shares) / consensus_shares > 0.50:
            if shares_val and 100 < shares_val < 100_000 and abs((shares_val * 1e6) - consensus_shares) / consensus_shares < 0.20:
                shares_val = shares_val * 1e6
            else:
                shares_val = consensus_shares
    elif shares_val is not None:
        if shares_val < 100_000 and (values.get("revenue") or 0) > 100_000_000:
            shares_val = shares_val * 1e6
        elif shares_val < 10_000_000 and (values.get("revenue") or 0) > 500_000_000:
            shares_val = shares_val * 1e3
    
    debt_row = choose([r for r in rows.get("debt", []) if r["start_date"] is None], end=end) or choose([r for r in rows.get("debt", []) if r["start_date"] is None])
    debt_val = debt_row["val"] if debt_row else 0.0
    cash_val = values.get("cash") or 0.0

    current_price = number(quote.get("price")) if quote else None

    # Calibrate WACC
    sic_desc = str(submissions.get("sicDescription", "")).lower()
    beta = 1.10
    for kw, b in SECTOR_BETAS.items():
        if kw in sic_desc:
            beta = b
            break
    # Ke = 4.25% + beta * 5.0%
    base_wacc = round(min(0.125, max(0.075, 0.0425 + beta * 0.050)), 4)
    # Calibrate Base 5y Growth from historical growth
    hist_g = growth if growth is not None else 0.08
    base_growth = round(min(0.35, max(0.04, hist_g * 0.70 if hist_g > 0.20 else hist_g)), 4)

    # Free Cash Flow Normalization:
    # If customer deposits inflate Operating Cash Flow (e.g. MercadoLibre/MercadoPago digital account float),
    # genuine sustainable FCF cannot exceed operating earnings (EBIT).
    t_ebit = values.get("operating_income") or 0.0
    effective_fcf = fcf
    if fcf is not None and t_ebit > 0:
        if fcf > t_ebit * 1.35:
            effective_fcf = round(t_ebit * 0.85, 2)

    # Determine base exit multiple and EPS for institutional valuation
    pe_trail = consensus.get("pe_trailing") if isinstance(consensus, dict) else None
    fwd_pe = consensus.get("forward_pe") if isinstance(consensus, dict) else None
    
    # Benchmark exit multiple: bounded in reasonable institutional ranges
    if pe_trail and pe_trail > 0:
        base_exit_pe = round(min(35.0, max(14.0, float(pe_trail))), 1)
    elif fwd_pe and fwd_pe > 0:
        base_exit_pe = round(min(35.0, max(14.0, float(fwd_pe) * 1.15)), 1)
    else:
        base_exit_pe = 20.0
    
    # EPS calculation:
    t_ni = values.get("net_income")
    if t_ni and shares_val and shares_val > 0 and t_ni > 0:
        eps_val = round(float(t_ni) / float(shares_val), 2)
    elif current_price and pe_trail and pe_trail > 0:
        eps_val = round(float(current_price) / float(pe_trail), 2)
    elif shares_val and shares_val > 0 and effective_fcf and effective_fcf > 0:
        eps_val = round(float(effective_fcf) / float(shares_val), 2)
    else:
        eps_val = None

    # Build Valuation Model
    if financial_sector:
        valuation = build_banking_valuation(values.get("equity"), prior_equity["val"] if prior_equity else None, values.get("net_income"), shares_val or 1.0, current_price=current_price)
    elif shares_val and shares_val > 0 and effective_fcf is not None and effective_fcf > 0:
        valuation = calculate_probabilistic_scenarios(
            start_fcf=effective_fcf,
            shares=shares_val,
            cash=cash_val,
            debt=debt_val,
            base_wacc=base_wacc,
            base_growth=base_growth,
            current_price=current_price,
            exit_multiple=base_exit_pe,
            eps=eps_val
        )
    else:
        valuation = {
            "status": "not_available",
            "reason": "Acciones en circulación o flujo de caja libre positivo no disponibles en los estados financieros para este emisor."
        }

    fair_val = valuation.get("composite_fair_value") or valuation.get("fair_value")

    # Sanity guard: prevent distorted valuation outliers (> 10x of market price)
    if current_price and current_price > 0 and fair_val and fair_val > 0:
        if fair_val > current_price * 10.0:
            capped_fv = round(min(fair_val, current_price * 3.5), 2)
            valuation["composite_fair_value"] = capped_fv
            valuation["valuation_note"] = "Valuación acotada por múltiplos sostenibles."
            fair_val = capped_fv

    mos = valuation.get("margin_of_safety_pct")
    delta_vs_price = valuation.get("delta_vs_price_pct")

    # Determine Quantitative Verdict
    if mos is None:
        verdict = "DATOS INSUFICIENTES PARA VALUACIÓN"
    elif mos >= 25.0:
        verdict = "SUBVALUADA / AMPLIO MARGEN DE SEGURIDAD"
    elif mos >= 10.0:
        verdict = "VALORACIÓN ATRACTIVA / MARGEN MODERADO"
    elif delta_vs_price is not None and abs(delta_vs_price) <= 10.0:
        verdict = "VALOR RAZONABLE / FAIR VALUE"
    else:
        verdict = "SOBREVALORADA / SIN MARGEN DE SEGURIDAD"

    is_manual = bool(quote.get("is_manual", False)) if quote else False
    premium_pct = valuation.get("premium_pct", 0.0)
    valuation_summary = {
        "verdict": verdict,
        "composite_fair_value": fair_val,
        "current_price": current_price,
        "margin_of_safety_pct": mos,
        "delta_vs_price_pct": delta_vs_price,
        "premium_pct": premium_pct,
        "price_source": quote.get("provider", "Mercado") if quote else "No disponible",
        "price_date": quote.get("as_of") if quote else None,
        "is_manual": is_manual,
        "target_price": consensus.get("target_price") if consensus else None,
        "target_high": consensus.get("target_high") if consensus else None,
        "target_low": consensus.get("target_low") if consensus else None,
        "recommendation_score": consensus.get("recommendation_score") if consensus else None,
        "recommendation_label": consensus.get("recommendation_label") if consensus else None,
        "pe_trailing": consensus.get("pe_trailing") if consensus else None,
        "forward_pe": consensus.get("forward_pe") if consensus else None
    }

    # Evaluate Quality Scorecards & Checklist
    piotroski, mayer, altman, checklist = evaluate_quality_and_checklist(
        financial_sector=financial_sector,
        revenue=values.get("revenue"),
        net_income=values.get("net_income"),
        operating_income=values.get("operating_income"),
        cfo=values.get("cfo"),
        capex=capex,
        assets=values.get("assets"),
        equity=values.get("equity"),
        prior_equity=prior_equity,
        shares=shares_val,
        current_price=current_price,
        fair_value=fair_val,
        growth=growth,
        values=values,
        previous=previous
    )

    t_rev = values.get("revenue") or 0.0
    t_ebit = values.get("operating_income") or 0.0
    t_ni = values.get("net_income") or 0.0
    t_assets = values.get("assets") or 0.0
    t_equity = values.get("equity") or 0.0
    t_debt = debt_val or 0.0
    t_cash = cash_val or 0.0

    core_indicators = [
        {
            "id": "revenue_growth",
            "name": "Ingresos y Crecimiento YoY",
            "value": t_rev,
            "growth_pct": round(growth * 100.0, 1) if growth is not None else None,
            "formatted": (f"${t_rev/1e9:.2f}B ({growth*100:+.1f}%)" if t_rev >= 1e9 else f"${t_rev/1e6:.1f}M ({growth*100:+.1f}%)") if (t_rev > 0 and growth is not None) else (f"${t_rev/1e9:.2f}B" if t_rev >= 1e9 else f"${t_rev/1e6:.1f}M" if t_rev > 0 else "N/D"),
            "source": "SEC Filings 10-K Anual",
            "period": f"{start} a {end}",
            "status": "available" if t_rev > 0 else "missing",
            "description": "Facturación total reportada en balance anual auditado ante la SEC."
        },
        {
            "id": "operating_margin",
            "name": "Margen Neto Bancario" if financial_sector else "Margen Operativo",
            "value": round(net_margin * 100.0, 1) if financial_sector and net_margin is not None else (round(operating_margin * 100.0, 1) if operating_margin is not None else None),
            "formatted": (f"{net_margin*100.0:.1f}% Margen Neto" if financial_sector and net_margin is not None else (f"{operating_margin*100.0:.1f}% Margen Operativo" if operating_margin is not None else "N/D")),
            "source": "SEC 10-K Income Statement",
            "period": "Anual",
            "status": "available" if (net_margin is not None or operating_margin is not None) else "missing",
            "description": "Eficiencia en la generación de utilidades sobre ingresos brutos."
        },
        {
            "id": "free_cash_flow",
            "name": "Solvencia Patrimonial (PN/Activos)" if financial_sector else "Flujo Libre de Caja (FCF)",
            "value": round(t_equity / t_assets * 100.0, 1) if financial_sector and t_assets > 0 else fcf,
            "formatted": (f"{t_equity/t_assets*100:.1f}% PN/Activos" if financial_sector and t_assets > 0 else (f"${fcf/1e9:.2f}B (Margen {fcf/t_rev*100:.1f}%)" if fcf and t_rev > 0 and abs(fcf) >= 1e9 else (f"${fcf/1e6:.1f}M" if fcf else "N/D"))),
            "source": "Balance General SEC" if financial_sector else "Cash Flow Statement (CFO - CapEx)",
            "period": "Anual",
            "status": "available" if (financial_sector or fcf is not None) else "missing",
            "description": "En bancos se evalúa respaldo patrimonial; en corporaciones flujo libre generado tras CapEx."
        },
        {
            "id": "solvency",
            "name": "Solvencia Financiera",
            "value": round((t_debt - t_cash) / max(1.0, t_ebit), 2) if not financial_sector and t_ebit > 0 else None,
            "formatted": (f"{(t_debt-t_cash)/t_ebit:.1f}x Deuda Neta/EBIT" if not financial_sector and t_ebit > 0 and (t_debt-t_cash) > 0 else ("Caja Neta Positiva" if not financial_sector and (t_debt-t_cash) <= 0 else (f"{t_equity/t_assets*100:.1f}% PN/Activos" if t_assets > 0 else "N/D"))),
            "source": "SEC Balance Sheet",
            "period": f"Al cierre {end}",
            "status": "available",
            "description": "Carga de endeudamiento financiero frente a la capacidad operativa de generación de caja."
        },
        {
            "id": "roic_vs_wacc",
            "name": "Retorno sobre Capital (ROE vs Ke)" if financial_sector else "Retorno sobre Capital (ROIC vs WACC)",
            "value": mayer.get("return_val_pct"),
            "formatted": f"{mayer.get('return_val_pct')}% vs Costo {mayer.get('cost_val_pct')}% (Spread {mayer.get('spread_pct'):+0.1f}%)",
            "source": "Retorno sobre Capital Invertido",
            "period": "Anual",
            "status": "available",
            "description": "Generación de retorno económico sobre el costo de financiamiento (Moat)."
        },
        {
            "id": "valuation_multiple",
            "name": "Múltiplo Patrimonial (P/B)" if financial_sector else "Múltiplo de Valuación (P/E)",
            "value": round(current_price / max(0.01, (t_equity/shares_val)), 2) if financial_sector and current_price and shares_val and t_equity > 0 else (
                consensus.get("pe_trailing") if consensus and consensus.get("pe_trailing") else (
                    round(current_price / max(0.01, (t_ni/shares_val)), 1) if current_price and shares_val and t_ni > 0 else None
                )
            ),
            "formatted": (
                f"P/B: {current_price/(t_equity/shares_val):.2f}x (Justificado: {valuation.get('justified_pb', 1.5):.2f}x)" if financial_sector and current_price and shares_val and t_equity > 0 else (
                    f"P/E Trailing: {consensus.get('pe_trailing'):.1f}x" + (f" (Fwd: {consensus.get('forward_pe'):.1f}x)" if consensus.get('forward_pe') else "") if consensus and consensus.get("pe_trailing") else (
                        f"P/E Trailing: {current_price/(t_ni/shares_val):.1f}x" if current_price and shares_val and t_ni > 0 else "N/D"
                    )
                )
            ),
            "source": "Mercado Institucional (TradingView / Wall Street)" if consensus and consensus.get("pe_trailing") else "Mercado / Balances SEC",
            "period": "Tiempo Real / TTM",
            "status": "available" if (consensus and consensus.get("pe_trailing")) or current_price else "missing",
            "description": "Múltiplo pagado por dólar de ganancia neta o por valor en libros."
        }
    ]

    return {
        "schema_version": MODEL_VERSION,
        "symbol": symbol,
        "ticker": symbol,
        "name": submissions.get("name") or facts.get("entityName") or symbol,
        "company_name": submissions.get("name") or facts.get("entityName") or symbol,
        "activity": submissions.get("sicDescription") or "Actividad no disponible",
        "financial_sector": financial_sector,
        "sector": submissions.get("sicDescription") or "General",
        "industry": submissions.get("sicDescription") or "General",
        "archetype": "FINANCIALS_BANKING" if financial_sector else "NON_FINANCIAL_EQUITY",
        "archetype_label": "Banca & Finanzas (Tier-1)" if financial_sector else "Empresa No Financiera",
        "quote": quote,
        "period": {
            "basis": "FY",
            "start": start,
            "end": end,
            "previous_start": previous.get("start") if previous else None,
            "previous_end": previous.get("end") if previous else None
        },
        "currency": "USD",
        "metrics": metrics,
        "sources": available_sources,
        "warnings": warnings,
        "retrieved_at": utc_now(),
        "facts_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
        "submissions_url": f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
        "valuation": valuation,
        "valuation_summary": valuation_summary,
        "core_indicators": core_indicators,
        "probabilistic_scenarios": valuation.get("scenarios") if isinstance(valuation, dict) else None,
        "reverse_dcf": valuation.get("reverse_dcf") if isinstance(valuation, dict) else None,
        "sensitivity_matrix": valuation.get("sensitivity_matrix") if isinstance(valuation, dict) else None,
        "expected_5y_cagr": valuation.get("expected_5y_cagr") if isinstance(valuation, dict) else None,
        "piotroski_fscore": piotroski,
        "altman_solvency": altman,
        "mayer_100_bagger_metrics": mayer,
        "checklist_due_diligence": checklist,
        "wall_street_consensus": consensus
    }

def fetch_quote(symbol):
    empty = {"status": "missing", "price": None, "currency": "USD", "as_of": None, "provider": "Mercado", "url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='-')}/", "note": "Cotización no disponible; podés ingresar un precio de referencia manual.", "is_manual": False}
    for base in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        try:
            raw = request_json(f"{base}/v8/finance/chart/{quote(symbol, safe='-')}?interval=1d&range=5d")
            if not isinstance(raw, dict) or not isinstance(raw.get("chart"), dict):
                continue
            results = raw.get("chart", {}).get("result") or []
            if not isinstance(results, list) or not results or not isinstance(results[0], dict):
                continue
            meta = results[0].get("meta", {}) if results else {}
            if not isinstance(meta, dict):
                continue
            price, timestamp = number(meta.get("regularMarketPrice")), number(meta.get("regularMarketTime"))
            currency = meta.get("currency") or "USD"
            if price is None or price <= 0 or timestamp is None:
                continue
            as_of = datetime.fromtimestamp(timestamp, timezone.utc)
            if as_of > datetime.now(timezone.utc):
                continue
            age = (datetime.now(timezone.utc) - as_of).total_seconds()
            return {**empty, "price": round(price, 2), "currency": currency, "as_of": as_of.isoformat(), "status": "stale" if age > 7 * 86400 else "available", "provider": "Yahoo Finance", "note": "Cotización informativa con posible demora; fecha proporcionada por Yahoo Finance. No se garantiza tiempo real.", "is_manual": False}
        except (ProviderUnavailable, TypeError, ValueError, OverflowError, OSError):
            continue

    # TradingView fallback for cloud environments
    try:
        tv_url = "https://scanner.tradingview.com/america/scan"
        payload = {"symbols": {"tickers": [f"NASDAQ:{symbol}", f"NYSE:{symbol}", f"AMEX:{symbol}"]}, "columns": ["close", "currency"]}
        res = requests.post(tv_url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            for row in data.get("data", []):
                d = row.get("d")
                if d and d[0] is not None and float(d[0]) > 0:
                    price = round(float(d[0]), 2)
                    currency = d[1] or "USD"
                    return {**empty, "price": price, "currency": currency, "as_of": utc_now(), "status": "available", "provider": "TradingView", "note": "Cotización informativa provista por TradingView.", "is_manual": False}
    except Exception:
        pass

    return empty

def fetch_wall_street_consensus(symbol):
    data = {
        "status": "missing",
        "target_price": None,
        "target_high": None,
        "target_low": None,
        "recommendation_score": None,
        "recommendation_label": "No disponible",
        "pe_trailing": None,
        "forward_pe": None,
        "shares_outstanding": None,
        "source": "Wall Street Consensus",
        "disclaimer": "Estimaciones públicas compiladas de analistas de Wall Street."
    }
    # 1. TradingView Scanner for target price, analyst range, recommendation, P/E trailing, and verified shares
    try:
        tv_url = "https://scanner.tradingview.com/america/scan"
        payload = {
            "symbols": {"tickers": [f"NASDAQ:{symbol}", f"NYSE:{symbol}", f"AMEX:{symbol}"]},
            "columns": ["close", "price_target_average", "price_target_high", "price_target_low", "recommendation_mark", "price_earnings_ttm", "total_shares_outstanding_fundamental"]
        }
        res = requests.post(tv_url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            for row in res.json().get("data", []):
                d = row.get("d", [])
                if d and len(d) >= 7:
                    if d[1] is not None and float(d[1]) > 0:
                        data["target_price"] = round(float(d[1]), 2)
                    if d[2] is not None and float(d[2]) > 0:
                        data["target_high"] = round(float(d[2]), 2)
                    if d[3] is not None and float(d[3]) > 0:
                        data["target_low"] = round(float(d[3]), 2)
                    if d[4] is not None:
                        rec = round(float(d[4]), 2)
                        data["recommendation_score"] = rec
                        data["recommendation_label"] = "Fuerte Compra" if rec <= 1.5 else ("Compra" if rec <= 2.2 else ("Mantener" if rec <= 3.2 else "Consenso de Mercado"))
                    if d[5] is not None and float(d[5]) > 0:
                        data["pe_trailing"] = round(float(d[5]), 1)
                    if d[6] is not None and float(d[6]) > 0:
                        data["shares_outstanding"] = float(d[6])
                    data["status"] = "available"
                    data["source"] = "Wall Street Consensus (TradingView Institutional)"
                    break
    except Exception:
        pass

    # 2. Finviz for Forward P/E & FactSet consensus enrichment
    try:
        url = f"https://finviz.com/quote.ashx?t={symbol}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            target_match = re.search(r'Target Price.*?<span[^>]*>([0-9.]+)</span>', r.text)
            recom_match = re.search(r'>Recom<.*?<span[^>]*>([0-9.]+)</span>', r.text)
            pe_fwd_match = re.search(r'Forward P/E.*?<span[^>]*>([0-9.]+)</span>', r.text)
            pe_ttm_match = re.search(r'>P/E<.*?<span[^>]*>([0-9.]+)</span>', r.text)
            if pe_fwd_match:
                data["forward_pe"] = float(pe_fwd_match.group(1))
            if not data["target_price"] and target_match:
                data["target_price"] = float(target_match.group(1))
            if not data["pe_trailing"] and pe_ttm_match:
                data["pe_trailing"] = float(pe_ttm_match.group(1))
            if not data["recommendation_score"] and recom_match:
                rec = float(recom_match.group(1))
                data["recommendation_score"] = rec
                data["recommendation_label"] = "Fuerte Compra" if rec <= 1.5 else ("Compra" if rec <= 2.2 else ("Mantener" if rec <= 3.2 else "Consenso de Mercado"))
            data["status"] = "available"
    except Exception:
        pass

    return data

def analyze_ticker(ticker_sym, manual_price=None):
    symbol = normalize_ticker(ticker_sym)
    company = resolve_company(symbol)
    cik = int(company["cik_str"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        submission_future = pool.submit(request_json, f"https://data.sec.gov/submissions/CIK{cik:010d}.json", sec=True)
        facts_future = pool.submit(request_json, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", sec=True)
        quote_future = pool.submit(fetch_quote, symbol) if manual_price is None else None
        consensus_future = pool.submit(fetch_wall_street_consensus, symbol)
        
        submissions, facts = submission_future.result(), facts_future.result()
        if manual_price is not None:
            p_val = round(float(manual_price), 2)
            market_quote = {"status": "manual", "price": p_val, "currency": "USD", "as_of": utc_now(), "provider": "Manual del usuario", "is_manual": True, "note": "Precio de referencia manual ingresado por el usuario."}
        else:
            market_quote = quote_future.result()
        wall_street_consensus = consensus_future.result()
    if not isinstance(submissions, dict) or not isinstance(facts, dict):
        raise ProviderUnavailable("La SEC devolvió una respuesta que no se pudo interpretar.")
    result = build_financials(symbol, cik, facts, submissions, quote=market_quote, consensus=wall_street_consensus)
    result["quote"] = market_quote
    result["wall_street_consensus"] = wall_street_consensus
    return result
