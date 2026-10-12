import sys
import os
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Try local import first, then fallback to relative engine directory
try:
    from fetch_financials import analyze_ticker
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent.parent
    ENGINE_DIR = BASE_DIR / ".agent" / "skills" / "equity-valuation" / "scripts"
    sys.path.append(str(ENGINE_DIR))
    from fetch_financials import analyze_ticker

app = FastAPI(
    title="QuantVal Institutional Valuation Engine",
    description="Fundamental equity valuation platform",
    version="2.4.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files path
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory cache: ticker -> (timestamp, data)
CACHE = {}
CACHE_TTL = 900  # 15 minutes

@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(str(index_file))

@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "QuantVal Pro", "version": "2.4.0-lead-magnet-final"}

@app.get("/api/evaluate/{ticker}")
async def evaluate_stock(ticker: str, nocache: bool = False):
    ticker = ticker.strip().upper()
    now = time.time()
    
    # Check cache
    if not nocache and ticker in CACHE:
        cached_time, cached_data = CACHE[ticker]
        if now - cached_time < CACHE_TTL:
            return cached_data
            
    try:
        # Run proprietary engine
        result = analyze_ticker(ticker)
        CACHE[ticker] = (now, result)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"No se encontraron balances públicos para '{ticker}'. Verificá el símbolo (ej. NVDA, AAPL, JPM, MELI, YPF).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluando '{ticker}': {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
