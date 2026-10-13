"""Run explicitly after deployment. Importing this file never calls providers."""
import json
import sys
import urllib.request

def get_json(url):
    with urllib.request.urlopen(url, timeout=70) as response:
        return json.load(response)

def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://quantval.onrender.com").rstrip("/")
    health = get_json(base + "/health")
    assert health["version"] == "3.0.0", "Render no está sirviendo la versión 3.0.0"
    print("Build:", health)
    for symbol in ["AAPL", "MSFT", "NVDA", "JPM", "NFLX"]:
        result = get_json(base + "/api/evaluate/" + symbol)
        assert result["symbol"] == symbol and result["schema_version"] == "annual-sec-v1"
        assert result["period"]["basis"] == "FY"
        if symbol == "JPM":
            assert result["valuation"]["status"] == "not_available" and result["financial_sector"]
            assert result["valuation"]["model_type"] == "banking_valuation"
            print(f"[{symbol}] Modelo Bancario -> Valor Patrimonial: ${result['valuation']['fair_value']:.2f} | P/B Justificado: {result['valuation']['justified_pb']}x")
        else:
            assert result["valuation"]["status"] == "available"
            v = result["valuation"]
            assert v["composite_fair_value"] > 0
            assert "scenarios" in v and "reverse_dcf" in v and "sensitivity_matrix" in v
            print(f"[{symbol}] DCF Fair Value: ${v['composite_fair_value']:.2f} | Reverse DCF Crecimiento Exigido: {v['reverse_dcf'].get('implied_growth_pct')}%")
        assert result["sources"], "Faltan fuentes"
        for m in result["metrics"]:
            assert m["status"] != "available" or m["value"] is not None
        print(f"       Periodo: {result['period']['start']} a {result['period']['end']} | Metricas: {[(m['id'], m['value']) for m in result['metrics']]}")
        print()
    print("Prueba normal de cinco consultas completada; no es una prueba de carga.")

if __name__ == "__main__":
    main()
