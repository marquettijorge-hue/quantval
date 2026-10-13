"""QuantVal's public, read-only API and frontend."""
import copy
import logging
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fetch_financials import VERSION, MODEL_VERSION, ProviderUnavailable, UnsupportedCompany, analyze_ticker, normalize_ticker

app = FastAPI(title="QuantVal — indicadores financieros", version=VERSION)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
CACHE = {}
CACHE_TTL = 900
MAX_CACHE = 128
_cache_lock = threading.Lock()
_inflight = set()
_condition = threading.Condition(_cache_lock)
_provider_slots = threading.BoundedSemaphore(2)
log = logging.getLogger("quantval")
if "PYTEST_CURRENT_TEST" not in os.environ:
    os.environ.setdefault("TALLER_URL", "https://www.educaenlinea.com.ar/web/talleria.html")

def release_info():
    return {"version": VERSION, "model_version": MODEL_VERSION, "commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("COMMIT_SHA") or "local / no informado"}

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

@app.get("/health")
def health():
    return {"status": "ok", "app": "QuantVal Pro", **release_info()}

@app.get("/api/config")
def config():
    destination = os.getenv("TALLER_URL", "").strip()
    parsed = urlparse(destination)
    direct = parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password
    return {**release_info(), "taller_url": destination if direct else "https://www.instagram.com/accionesargentinas/", "taller_label": "Ver Taller de Inversiones con IA" if direct else "Pedime información del Taller", "taller_note": "Abrís la información del Taller." if direct else "Abrís el perfil de @accionesargentinas en Instagram."}

@app.get("/api/evaluate/{ticker}")
def evaluate_stock(ticker: str):
    try:
        symbol = normalize_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    key = (MODEL_VERSION, symbol)
    with _condition:
        if key in _inflight:
            if not _condition.wait_for(lambda: key not in _inflight, timeout=65):
                raise HTTPException(status_code=503, detail="El análisis está tardando más de lo esperado. Intentá nuevamente.")
        cached = CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            result = copy.deepcopy(cached[1])
            result["cache"] = {"hit": True, "age_seconds": round(time.monotonic() - cached[0])}
            return result
        _inflight.add(key)
    try:
        if not _provider_slots.acquire(timeout=10):
            raise HTTPException(status_code=503, detail="Hay otros análisis en curso. Probá nuevamente en unos segundos.")
        try:
            result = analyze_ticker(symbol)
        finally:
            _provider_slots.release()
        result["cache"] = {"hit": False, "age_seconds": 0}
        with _cache_lock:
            if len(CACHE) >= MAX_CACHE:
                del CACHE[min(CACHE, key=lambda k: CACHE[k][0])]
            CACHE[key] = (time.monotonic(), copy.deepcopy(result))
        return result
    except UnsupportedCompany as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        log.exception("No se pudo analizar %s", symbol)
        raise HTTPException(status_code=500, detail="No pudimos completar el análisis. Intentá nuevamente más tarde.")
    finally:
        with _condition:
            _inflight.discard(key)
            _condition.notify_all()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
