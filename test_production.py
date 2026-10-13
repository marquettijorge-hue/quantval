import urllib.request
import urllib.error
import json

tickers = ['NVDA', 'NFLX', 'JPM', 'AAPL', 'MSFT']
print("=" * 80)
print("VALIDACION DE PRODUCCION EN VIVO (https://quantval.onrender.com/)")
print("=" * 80)

for sym in tickers:
    url = f"https://quantval.onrender.com/api/evaluate/{sym}"
    req = urllib.request.urlopen(url, timeout=30)
    d = json.loads(req.read().decode())
    vs = d['valuation_summary']
    sc = d.get('probabilistic_scenarios', {})
    ev = sc.get('expected_weighted_fair_value')
    bear = sc.get('bear', {}).get('fair_value')
    base = sc.get('base', {}).get('fair_value')
    bull = sc.get('bull', {}).get('fair_value')
    recomputed_ev = round(0.25 * bear + 0.50 * base + 0.25 * bull, 2)
    match_ev = (round(ev, 2) == recomputed_ev)
    
    print(f"[{sym}] Cotizacion: ${vs['current_price']:.2f} | Fair Value: ${vs['composite_fair_value']:.2f} | MoS: {vs['margin_of_safety_pct']}% | Veredicto: {vs['verdict']}")
    print(f"      Escenarios -> Bear(25%): ${bear:.2f} | Base(50%): ${base:.2f} | Bull(25%): ${bull:.2f} | E[V] Match: {match_ev}")
    core_summary = [f"{c['name']}: {c['formatted']}" for c in d.get('core_indicators', [])]
    print(f"      6 Metricas Core: {core_summary}")
    print()

print("-" * 80)
try:
    urllib.request.urlopen("https://quantval.onrender.com/api/evaluate/NONEXISTENT999XYZ", timeout=15)
    print("Error: Bad ticker did not return error!")
except urllib.error.HTTPError as e:
    print(f"Manejo de ticker inexistente: HTTP {e.code} -> {e.read().decode()}")

print("=" * 80)
