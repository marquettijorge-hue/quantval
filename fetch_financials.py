"""Annual financial facts from SEC EDGAR, with explicit provenance.
This release does not estimate fair values, analyst consensus or returns.
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
        response = requests.get(url, headers=HEADERS if sec else {"User-Agent": HEADERS["User-Agent"]}, timeout=15 if sec else 8)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        # No block evasion, retry loops or fabricated fallback financials.
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
    for namespace in ("us-gaap", "ifrs-full"):
        for priority, tag in enumerate(TAGS[key]):
            values = facts.get("facts", {}).get(namespace, {}).get(tag, {}).get("units", {}).get("USD", [])
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
    # Latest filing may restate a comparative; then prefer standard tag order.
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
    return {"provider": "SEC EDGAR", "url": filing_url(cik, row, submissions), "form": row["form"], "filed_at": row["filed"], "period_start": row.get("start"), "period_end": row["end"], "tag": row["namespace"] + ":" + row["tag"], "value": row["val"], "unit": "USD", "accession": row["accn"]}

def metric(key, label, value, unit, formula, sources, *, kind="calculated", status=None, note=""):
    value = number(value)
    return {"id": key, "label": label, "value": value, "unit": unit, "kind": kind, "status": status or ("available" if value is not None else "missing"), "formula": formula, "sources": [s for s in sources if s], "note": note}

def ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator

def build_financials(symbol, cik, facts, submissions, *, today=None):
    today = today or datetime.now(timezone.utc).date()
    rows = {k: records(facts, k, today) for k in TAGS}
    # Annual-only: never sum overlapping quarters/YTD values.
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
    return {"schema_version": MODEL_VERSION, "symbol": symbol, "name": submissions.get("name") or facts.get("entityName") or symbol, "activity": submissions.get("sicDescription") or "Actividad no disponible", "financial_sector": financial_sector, "period": {"basis": "FY", "start": start, "end": end, "previous_start": previous.get("start") if previous else None, "previous_end": previous.get("end") if previous else None}, "currency": "USD", "metrics": metrics, "sources": available_sources, "warnings": warnings, "retrieved_at": utc_now(), "facts_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", "submissions_url": f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", "valuation": {"status": "not_available", "reason": "Esta versión muestra indicadores históricos; no estima valor intrínseco, precio objetivo ni retornos futuros."}}

def fetch_quote(symbol):
    empty = {"status": "missing", "price": None, "currency": None, "as_of": None, "provider": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='-')}/", "note": "Cotización no disponible; el análisis de balances sigue siendo válido."}
    try:
        raw = request_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='-')}?interval=1d&range=5d")
        if not isinstance(raw, dict) or not isinstance(raw.get("chart"), dict):
            return empty
        results = raw.get("chart", {}).get("result") or []
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return empty
        meta = results[0].get("meta", {}) if results else {}
        if not isinstance(meta, dict):
            return empty
        price, timestamp = number(meta.get("regularMarketPrice")), number(meta.get("regularMarketTime"))
        currency = meta.get("currency")
        if price is None or price <= 0 or timestamp is None or not currency:
            return empty
        as_of = datetime.fromtimestamp(timestamp, timezone.utc)
        if as_of > datetime.now(timezone.utc):
            return empty
        age = (datetime.now(timezone.utc) - as_of).total_seconds()
        return {**empty, "price": price, "currency": currency, "as_of": as_of.isoformat(), "status": "stale" if age > 7 * 86400 else "available", "note": "Cotización informativa con posible demora; fecha proporcionada por Yahoo Finance. No se garantiza tiempo real."}
    except (ProviderUnavailable, TypeError, ValueError, OverflowError, OSError):
        return empty

def analyze_ticker(ticker_sym):
    symbol = normalize_ticker(ticker_sym)
    company = resolve_company(symbol)
    cik = int(company["cik_str"])
    # Independent reads run together, still under the process-wide SEC pacer.
    with ThreadPoolExecutor(max_workers=3) as pool:
        submission_future = pool.submit(request_json, f"https://data.sec.gov/submissions/CIK{cik:010d}.json", sec=True)
        facts_future = pool.submit(request_json, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", sec=True)
        quote_future = pool.submit(fetch_quote, symbol)
        submissions, facts, market_quote = submission_future.result(), facts_future.result(), quote_future.result()
    if not isinstance(submissions, dict) or not isinstance(facts, dict):
        raise ProviderUnavailable("La SEC devolvió una respuesta que no se pudo interpretar.")
    result = build_financials(symbol, cik, facts, submissions)
    result["quote"] = market_quote
    return result
