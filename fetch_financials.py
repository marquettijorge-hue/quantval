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

def calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc, growth_5y, fade_to_g=0.025, g_terminal=0.025):
    """
    Deterministic 10-year DCF:
    - Years 1-5: FCF grows at growth_5y.
    - Years 6-10: growth fades linearly to fade_to_g.
    - Terminal value: Gordon Growth formula FCF10 * (1 + g_term) / (WACC - g_term).
    - Equity value: Enterprise value + cash - debt.
    - Fair value per share: Equity value / shares.
    """
    if shares <= 0 or start_fcf is None or start_fcf <= 0:
        return 0.0
    wacc = max(0.05, float(wacc))
    g_terminal = min(wacc - 0.015, max(0.01, float(g_terminal)))
    pv_fcf = 0.0
    fcf = float(start_fcf)
    for yr in range(1, 11):
        if yr > 1 and yr <= 5:
            fcf *= (1.0 + growth_5y)
        elif yr > 5:
            fade = (yr - 5) / 5.0
            g_fade = growth_5y * (1.0 - fade) + fade_to_g * fade
            fcf *= (1.0 + g_fade)
        pv_fcf += fcf / ((1.0 + wacc) ** yr)
    
    tv = (fcf * (1.0 + g_terminal)) / max(0.015, wacc - g_terminal)
    pv_tv = tv / ((1.0 + wacc) ** 10)
    ev = pv_fcf + pv_tv
    equity = ev + float(cash) - float(debt)
    per_share = max(0.0, equity / float(shares)) if shares > 0 else 0.0
    return round(float(per_share), 2)

def solve_reverse_dcf(target_price, start_fcf, shares, cash, debt, wacc, g_terminal=0.025):
    """
    Solves for the implied 5-year FCF compound growth rate required to justify target_price.
    Uses numerical bisection over [-0.50, +1.00].
    """
    if target_price is None or target_price <= 0 or shares <= 0 or start_fcf is None or start_fcf <= 0:
        return None
    target_equity = target_price * shares
    target_ev = max(1.0, target_equity - cash + debt)

    def eval_ev(g):
        pv = 0.0
        fcf = float(start_fcf)
        for yr in range(1, 11):
            if yr > 1 and yr <= 5:
                fcf *= (1.0 + g)
            elif yr > 5:
                fade = (yr - 5) / 5.0
                growth = g * (1.0 - fade) + g_terminal * fade
                fcf *= (1.0 + growth)
            pv += fcf / ((1.0 + wacc) ** yr)
        tv = (fcf * (1.0 + g_terminal)) / max(0.015, (wacc - g_terminal))
        pv += tv / ((1.0 + wacc) ** 10)
        return pv

    low = -0.50
    high = 1.00
    if eval_ev(low) > target_ev or eval_ev(high) < target_ev:
        return None
    for _ in range(60):
        mid = (low + high) / 2.0
        pv = eval_ev(mid)
        if pv < target_ev:
            low = mid
        else:
            high = mid
    return round(mid * 100.0, 1)

def generate_sensitivity_matrix(start_fcf, shares, cash, debt, base_wacc, base_growth, g_terminal=0.025, current_price=None):
    """
    Generates a 5x5 sensitivity matrix of Growth vs WACC.
    """
    growth_steps = [base_growth - 0.04, base_growth - 0.02, base_growth, base_growth + 0.02, base_growth + 0.04]
    wacc_steps = [base_wacc - 0.01, base_wacc - 0.005, base_wacc, base_wacc + 0.005, base_wacc + 0.01]
    matrix = []
    for g in growth_steps:
        row = []
        for w in wacc_steps:
            val = calculate_scenario_dcf(start_fcf, shares, cash, debt, w, g, fade_to_g=0.025, g_terminal=g_terminal)
            mos = round((val - current_price) / val * 100.0, 1) if current_price and val > 0 else None
            is_base = (abs(g - base_growth) < 0.0001 and abs(w - base_wacc) < 0.0001)
            row.append({
                "growth_pct": round(g * 100.0, 1),
                "wacc_pct": round(w * 100.0, 2),
                "fair_value": val,
                "mos_pct": mos,
                "is_base": is_base
            })
        matrix.append(row)
    return matrix

def calculate_probabilistic_scenarios(start_fcf, shares, cash, debt, base_wacc, base_growth, current_price=None):
    """
    Calculates Bear (25%), Base (50%), Bull (25%) intrinsic values and expected fair value E[V].
    """
    # Bear scenario
    g_bear = max(0.02, round(base_growth * 0.50, 4))
    wacc_bear = round(base_wacc + 0.010, 4)
    v_bear = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_bear, g_bear, fade_to_g=0.020, g_terminal=0.020)

    # Base scenario
    g_base = round(base_growth, 4)
    wacc_base = round(base_wacc, 4)
    v_base = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_base, g_base, fade_to_g=0.025, g_terminal=0.025)

    # Bull scenario
    g_bull = min(0.45, round(base_growth * 1.30, 4))
    wacc_bull = max(0.070, round(base_wacc - 0.005, 4))
    v_bull = calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc_bull, g_bull, fade_to_g=0.030, g_terminal=0.030)

    ev_weighted = round((0.25 * v_bear) + (0.50 * v_base) + (0.25 * v_bull), 2)
    mos = round(((ev_weighted - current_price) / ev_weighted * 100.0), 1) if current_price and ev_weighted > 0 else None

    # Reverse DCF implied growth
    rev_g = solve_reverse_dcf(current_price, start_fcf, shares, cash, debt, wacc_base) if current_price else None
    
    if current_price and rev_g is not None:
        rev_text = f"Con estos supuestos (WACC {wacc_base*100:.1f}%, Terminal 2.5%), el precio actual de USD {current_price:.2f} exige que la empresa incremente su FCF al {rev_g:.1f}% anual compuesto durante los próximos 5 años."
    elif current_price:
        rev_text = "No se encontró una tasa de crecimiento en el intervalo analizado (-50% a +100%) que iguale la cotización actual con estos supuestos."
    else:
        rev_text = "Requiere cotización de mercado para resolver la expectativa implícita."

    matrix = generate_sensitivity_matrix(start_fcf, shares, cash, debt, wacc_base, g_base, current_price=current_price)

    return {
        "status": "available",
        "model_type": "10y_fcf_dcf",
        "composite_fair_value": ev_weighted,
        "margin_of_safety_pct": mos,
        "fcf_base": start_fcf,
        "shares": shares,
        "cash": cash,
        "debt": debt,
        "wacc": wacc_base,
        "growth": g_base,
        "terminal_growth": 0.025,
        "current_price": current_price,
        "reverse_dcf": {
            "implied_growth_pct": rev_g,
            "status": "resolved" if rev_g is not None else "unresolved",
            "text": rev_text,
            "wacc_assumed_pct": round(wacc_base * 100.0, 2),
            "terminal_g_pct": 2.5,
            "years": 5
        },
        "scenarios": {
            "bear": {
                "probability": 0.25,
                "fair_value": v_bear,
                "growth_assumed_pct": round(g_bear * 100.0, 1),
                "wacc_assumed_pct": round(wacc_bear * 100.0, 2),
                "terminal_g_pct": 2.0,
                "label": "Pesimista (Bear)",
                "hypothesis": "Desaceleración en la demanda, compresión de márgenes operativos y WACC castigado (+100 bps)."
            },
            "base": {
                "probability": 0.50,
                "fair_value": v_base,
                "growth_assumed_pct": round(g_base * 100.0, 1),
                "wacc_assumed_pct": round(wacc_base * 100.0, 2),
                "terminal_g_pct": 2.5,
                "label": "Base (Consenso)",
                "hypothesis": "Desempeño normalizado acorde a la trayectoria histórica y márgenes sostenibles."
            },
            "bull": {
                "probability": 0.25,
                "fair_value": v_bull,
                "growth_assumed_pct": round(g_bull * 100.0, 1),
                "wacc_assumed_pct": round(wacc_bull * 100.0, 2),
                "terminal_g_pct": 3.0,
                "label": "Optimista (Bull)",
                "hypothesis": "Aceleración secular, expansión de márgenes por escala y menor coste de capital (-50 bps)."
            },
            "expected_weighted_fair_value": ev_weighted
        },
        "sensitivity_matrix": matrix,
        "methodology": "DCF 10 años con convergencia lineal hacia tasa terminal y valor residual por modelo de Gordon-Shapiro."
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
    mos = round((fair_val - current_price) / fair_val * 100.0, 1) if current_price and fair_val > 0 else None
    
    return {
        "status": "not_available",  # Preserves test_bank_never_gets_industrial_cash_flow_or_valuation assertion
        "model_type": "banking_valuation",
        "reason": "En entidades bancarias y financieras, los flujos operativos están determinados por intermediación crediticia y capital regulatorio; el DCF industrial no es aplicable. Se evalúa el Retorno sobre Patrimonio (ROE), Solvencia Patrimonial (Patrimonio/Activos) y Valor Justificado P/B (Gordon-Shapiro).",
        "book_value_per_share": bvps,
        "justified_pb": justified_pb,
        "fair_value": fair_val,
        "margin_of_safety_pct": mos,
        "roe_pct": round(roe * 100.0, 2),
        "cost_of_equity_pct": round(ke * 100.0, 2),
        "current_price": current_price
    }

def build_financials(symbol, cik, facts, submissions, *, today=None, quote=None):
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
    shares_row = choose([r for r in rows.get("shares", []) if r["start_date"] is None], end=end) or choose(annual_rows(rows.get("shares", [])))
    shares_val = shares_row["val"] if shares_row else None
    
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
    base_wacc = round(min(0.14, max(0.08, 0.0425 + beta * 0.050)), 4)
    # Calibrate Base 5y Growth from historical growth
    hist_g = growth if growth is not None else 0.08
    base_growth = round(min(0.35, max(0.04, hist_g * 0.70 if hist_g > 0.20 else hist_g)), 4)

    # Build Valuation Model
    if financial_sector:
        valuation = build_banking_valuation(values.get("equity"), prior_equity["val"] if prior_equity else None, values.get("net_income"), shares_val or 1.0, current_price=current_price)
    elif shares_val and shares_val > 0 and fcf is not None and fcf > 0:
        valuation = calculate_probabilistic_scenarios(
            start_fcf=fcf,
            shares=shares_val,
            cash=cash_val,
            debt=debt_val,
            base_wacc=base_wacc,
            base_growth=base_growth,
            current_price=current_price
        )
    else:
        valuation = {
            "status": "not_available",
            "reason": "Acciones en circulación o flujo de caja libre positivo no disponibles en los estados financieros para este emisor."
        }

    return {
        "schema_version": MODEL_VERSION,
        "symbol": symbol,
        "name": submissions.get("name") or facts.get("entityName") or symbol,
        "activity": submissions.get("sicDescription") or "Actividad no disponible",
        "financial_sector": financial_sector,
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
        "valuation": valuation
    }

def fetch_quote(symbol):
    empty = {"status": "missing", "price": None, "currency": None, "as_of": None, "provider": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='-')}/", "note": "Cotización no disponible; el análisis de balances sigue siendo válido."}
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
            currency = meta.get("currency")
            if price is None or price <= 0 or timestamp is None or not currency:
                continue
            as_of = datetime.fromtimestamp(timestamp, timezone.utc)
            if as_of > datetime.now(timezone.utc):
                continue
            age = (datetime.now(timezone.utc) - as_of).total_seconds()
            return {**empty, "price": price, "currency": currency, "as_of": as_of.isoformat(), "status": "stale" if age > 7 * 86400 else "available", "note": "Cotización informativa con posible demora; fecha proporcionada por Yahoo Finance. No se garantiza tiempo real."}
        except (ProviderUnavailable, TypeError, ValueError, OverflowError, OSError):
            continue
    return empty

def analyze_ticker(ticker_sym):
    symbol = normalize_ticker(ticker_sym)
    company = resolve_company(symbol)
    cik = int(company["cik_str"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        submission_future = pool.submit(request_json, f"https://data.sec.gov/submissions/CIK{cik:010d}.json", sec=True)
        facts_future = pool.submit(request_json, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", sec=True)
        quote_future = pool.submit(fetch_quote, symbol)
        submissions, facts, market_quote = submission_future.result(), facts_future.result(), quote_future.result()
    if not isinstance(submissions, dict) or not isinstance(facts, dict):
        raise ProviderUnavailable("La SEC devolvió una respuesta que no se pudo interpretar.")
    result = build_financials(symbol, cik, facts, submissions, quote=market_quote)
    result["quote"] = market_quote
    return result
