#!/usr/bin/env python3
"""
Institutional Quantitative Equity Valuation Engine
===================================================
Incorporating:
1. Operations Research Business Model Archetype Classification
2. 10,000-Iteration Monte Carlo Simulation (Vectorized NumPy)
3. Reverse DCF (Market-Implied Expectations Root Solver)
4. Blume-Adjusted Cost of Capital (CAPM / WACC Shrinkage)
5. Joseph Piotroski (2000) 9-Point F-Score
6. Christopher Mayer (100 Baggers) ROIC & Capital Allocation Metrics
7. Asness, Frazzini & Pedersen (AQR) Quality-Minus-Junk (QMJ)
8. Altman Z''-Score (1993 Service/Tech) & Classic Altman Z (1968)
9. Rule of 40 & FCF Cash Conversion Analytics
10. Multi-Model Valuation (EPV, Forward P/E, PEG, DCF)
11. Market Sentiment, Ownership & Contrarian Momentum Indicators
12. Kelly Criterion & Multi-Criteria Decision Analysis (MCDA 0-100)
"""

import sys
import json
import math
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def safe_float(val, default=0.0):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def get_row(df, possible_names):
    if df is None or df.empty:
        return None
    for name in possible_names:
        if name in df.index:
            return df.loc[name]
    return None

# --- INSTITUTIONAL SECTOR & INDUSTRY BENCHMARKS (DAMODARAN / FACTSET 2025/2026) ---
SECTOR_BENCHMARKS = {
    'TECH_SOFTWARE': {
        'name': 'Tecnología / Software, Cloud & SaaS',
        'pe': 28.5,
        'ev_ebitda': 20.0,
        'gross_margin': 0.68,
        'operating_margin': 0.24,
        'fcf_margin': 0.22,
        'roic': 0.185,
        'capex_intensity': 0.035,
        'rev_growth': 0.140,
        'net_debt_to_ebitda': 0.5
    },
    'TECH_HARDWARE_SEMIS': {
        'name': 'Tecnología / Hardware & Semiconductores',
        'pe': 20.0,
        'pe_peak_cycle': 12.0,
        'ev_ebitda': 14.0,
        'gross_margin': 0.46,
        'operating_margin': 0.18,
        'fcf_margin': 0.15,
        'roic': 0.150,
        'capex_intensity': 0.090,
        'rev_growth': 0.105,
        'net_debt_to_ebitda': 0.4
    },
    'COMMUNICATION_SERVICES': {
        'name': 'Servicios de Comunicación & Medios Digitales',
        'pe': 22.0,
        'ev_ebitda': 13.0,
        'gross_margin': 0.48,
        'operating_margin': 0.20,
        'fcf_margin': 0.16,
        'roic': 0.150,
        'capex_intensity': 0.055,
        'rev_growth': 0.100,
        'net_debt_to_ebitda': 1.6
    },
    'CONSUMER_DISCRETIONARY': {
        'name': 'Consumo Discrecional / E-Commerce & Retail',
        'pe': 23.0,
        'ev_ebitda': 14.5,
        'gross_margin': 0.36,
        'operating_margin': 0.095,
        'fcf_margin': 0.070,
        'roic': 0.130,
        'capex_intensity': 0.045,
        'rev_growth': 0.110,
        'net_debt_to_ebitda': 1.3
    },
    'CONSUMER_DEFENSIVE': {
        'name': 'Consumo Defensivo / Alimentos & Bebidas',
        'pe': 19.5,
        'ev_ebitda': 13.0,
        'gross_margin': 0.38,
        'operating_margin': 0.140,
        'fcf_margin': 0.085,
        'roic': 0.120,
        'capex_intensity': 0.038,
        'rev_growth': 0.045,
        'net_debt_to_ebitda': 2.2
    },
    'HEALTHCARE': {
        'name': 'Salud / Farmacéutica & Biotecnología',
        'pe': 21.0,
        'ev_ebitda': 13.5,
        'gross_margin': 0.62,
        'operating_margin': 0.190,
        'fcf_margin': 0.145,
        'roic': 0.140,
        'capex_intensity': 0.040,
        'rev_growth': 0.065,
        'net_debt_to_ebitda': 1.4
    },
    'FINANCIAL_SERVICES': {
        'name': 'Servicios Financieros, Banca & Fintech',
        'pe': 14.5,
        'ev_ebitda': 11.0,
        'gross_margin': 0.50,
        'operating_margin': 0.280,
        'fcf_margin': 0.180,
        'roic': 0.130,
        'capex_intensity': 0.025,
        'rev_growth': 0.075,
        'net_debt_to_ebitda': 1.0
    },
    'INDUSTRIALS': {
        'name': 'Industrial / Manufactura & Bienes de Capital',
        'pe': 18.5,
        'ev_ebitda': 12.0,
        'gross_margin': 0.28,
        'operating_margin': 0.110,
        'fcf_margin': 0.065,
        'roic': 0.105,
        'capex_intensity': 0.040,
        'rev_growth': 0.055,
        'net_debt_to_ebitda': 1.8
    },
    'ENERGY': {
        'name': 'Energía / Petróleo, Gas & Renovables',
        'pe': 11.5,
        'ev_ebitda': 5.8,
        'gross_margin': 0.35,
        'operating_margin': 0.150,
        'fcf_margin': 0.100,
        'roic': 0.115,
        'capex_intensity': 0.095,
        'rev_growth': 0.035,
        'net_debt_to_ebitda': 1.1
    },
    'BROAD_MARKET': {
        'name': 'Mercado General / S&P 500 Mediana',
        'pe': 21.0,
        'ev_ebitda': 13.0,
        'gross_margin': 0.36,
        'operating_margin': 0.130,
        'fcf_margin': 0.090,
        'roic': 0.115,
        'capex_intensity': 0.050,
        'rev_growth': 0.065,
        'net_debt_to_ebitda': 1.5
    }
}

def get_sector_benchmark(sector, industry):
    sec = str(sector).lower()
    ind = str(industry).lower()
    
    if any(k in ind for k in ['semiconductor', 'hardware', 'memory', 'electronic component', 'equipment']):
        return SECTOR_BENCHMARKS['TECH_HARDWARE_SEMIS']
    if any(k in ind for k in ['software', 'cloud', 'information tech', 'saas', 'internet content']):
        return SECTOR_BENCHMARKS['TECH_SOFTWARE']
    if 'communication' in sec or any(k in ind for k in ['entertainment', 'media', 'broadcasting', 'telecom', 'streaming']):
        return SECTOR_BENCHMARKS['COMMUNICATION_SERVICES']
    if any(k in ind for k in ['retail', 'internet retail', 'apparel', 'auto', 'consumer cyclical', 'e-commerce']):
        return SECTOR_BENCHMARKS['CONSUMER_DISCRETIONARY']
    if 'defensive' in sec or any(k in ind for k in ['beverage', 'food', 'tobacco', 'household', 'staple']):
        return SECTOR_BENCHMARKS['CONSUMER_DEFENSIVE']
    if 'health' in sec or any(k in ind for k in ['drug', 'biotech', 'medical', 'pharma']):
        return SECTOR_BENCHMARKS['HEALTHCARE']
    if 'financial' in sec or any(k in ind for k in ['bank', 'credit', 'payment', 'fintech', 'insurance']):
        return SECTOR_BENCHMARKS['FINANCIAL_SERVICES']
    if 'energy' in sec or any(k in ind for k in ['oil', 'gas', 'refin']):
        return SECTOR_BENCHMARKS['ENERGY']
    if 'industrial' in sec or any(k in ind for k in ['aerospace', 'machinery', 'transport', 'defense']):
        return SECTOR_BENCHMARKS['INDUSTRIALS']
    return SECTOR_BENCHMARKS['BROAD_MARKET']

def solve_reverse_dcf(target_price, start_fcf, shares, cash, debt, wacc, g_terminal=0.025):
    """
    Numerically solves for the implied 5-year CAGR growth rate
    required to justify the current market price via DCF.
    """
    target_equity = target_price * shares
    target_ev = max(1.0, target_equity - cash + debt)
    
    low = -0.30
    high = 0.60
    for _ in range(60):
        mid = (low + high) / 2.0
        pv = 0.0
        fcf = start_fcf
        for yr in range(1, 11):
            if yr == 1:
                pass
            elif yr <= 5:
                fcf *= (1 + mid)
            else:
                fade = (yr - 5) / 5.0
                growth = mid * (1 - fade) + g_terminal * fade
                fcf *= (1 + growth)
            pv += fcf / ((1 + wacc) ** yr)
        
        tv = (fcf * (1 + g_terminal)) / max(0.01, (wacc - g_terminal))
        pv += tv / ((1 + wacc) ** 10)
        
        if pv < target_ev:
            low = mid
        else:
            high = mid
    return mid

def calculate_scenario_dcf(start_fcf, shares, cash, debt, wacc, growth_5y, fade_to_g=0.025, exit_multiple=None, g_terminal=0.025):
    """
    10-year deterministic DCF with growth in years 1-5 and linear convergence to terminal growth in years 6-10.
    """
    pv_fcf = 0.0
    fcf = start_fcf
    for yr in range(1, 11):
        if yr > 1 and yr <= 5:
            fcf *= (1 + growth_5y)
        elif yr > 5:
            fade = (yr - 5) / 5.0
            g_fade = growth_5y * (1 - fade) + fade_to_g * fade
            fcf *= (1 + g_fade)
        pv_fcf += fcf / ((1 + wacc) ** yr)
    
    if exit_multiple is not None and exit_multiple > 0:
        tv = fcf * exit_multiple
    else:
        tv = (fcf * (1 + g_terminal)) / max(0.015, wacc - g_terminal)
    pv_tv = tv / ((1 + wacc) ** 10)
    
    ev = pv_fcf + pv_tv
    equity = ev + cash - debt
    per_share = max(0.0, equity / shares) if shares > 0 else 0.0
    return float(per_share)

def calculate_probabilistic_scenarios(archetype, fwd_rev_growth_0y, fwd_eps_0y, start_fcf, shares, cash, debt, wacc, 
                                      conservative_pe, fair_pe, growth_pe, bvps, roe_bank, g_bank, epv_per_share, current_price):
    """
    Computes rigorous 3-scenario intrinsic values (Bear 25%, Base 50%, Bull 25%)
    and the Expected Weighted Intrinsic Value E[V] = 0.25*Bear + 0.50*Base + 0.25*Bull.
    """
    if archetype == "FINANCIALS_BANKING":
        # Bear (25% prob): credit stress, compressed NIM, WACC +100bps
        roe_bear = max(0.08, roe_bank * 0.70)
        ke_bear = wacc + 0.010
        val_bear_pe = (fwd_eps_0y * 0.88 * conservative_pe) / (1 + ke_bear)
        val_bear_pb = max(0.80, min(1.30, (roe_bear - 0.02) / max(0.015, ke_bear - 0.02))) * bvps
        v_bear = max(5.0, 0.55 * val_bear_pe + 0.45 * val_bear_pb)
        bear_hypo = "Estrés crediticio moderado, compresión de NIM y coste de capital elevado (+100 bps)."

        # Base (50% prob): normalized ROE, base WACC, fair PE
        roe_base = roe_bank
        ke_base = wacc
        val_base_pe = (fwd_eps_0y * fair_pe) / (1 + ke_base)
        val_base_pb = max(0.90, min(2.50, (roe_base - g_bank) / max(0.015, ke_base - g_bank))) * bvps
        v_base = max(5.0, 0.55 * val_base_pe + 0.45 * val_base_pb)
        base_hypo = "Rentabilidad sobre patrimonio normalizada en línea con promedio de ciclo y calidad de cartera estable."

        # Bull (25% prob): expanding ROE, lower funding cost, premium multiple
        roe_bull = min(0.24, roe_bank * 1.20)
        ke_bull = max(0.07, wacc - 0.005)
        val_bull_pe = (fwd_eps_0y * 1.12 * growth_pe) / (1 + ke_bull)
        val_bull_pb = max(1.20, min(3.00, (roe_bull - g_bank) / max(0.015, ke_bull - g_bank))) * bvps
        v_bull = max(5.0, 0.55 * val_bull_pe + 0.45 * val_bull_pb)
        bull_hypo = "Expansión sostenida de préstamos, menor coste de fondeo y margen financiero robusto."
    else:
        # Non-Banking DCF 10-Year Scenarios
        # Bear (25% prob): severe deceleration, WACC +100bps, Gordon terminal g=2.0%
        g_bear = max(0.02, min(0.12, fwd_rev_growth_0y * 0.40))
        wacc_bear = wacc + 0.010
        v_bear = calculate_scenario_dcf(
            start_fcf=start_fcf, shares=shares, cash=cash, debt=debt,
            wacc=wacc_bear, growth_5y=g_bear, fade_to_g=0.020, g_terminal=0.020
        )
        if epv_per_share > 0:
            v_bear = max(v_bear, epv_per_share * 0.85)
        bear_hypo = "Desaceleración severa, compresión de márgenes, tasa WACC castigada (+100 bps) y digestión de inversiones."

        # Base (50% prob): consensus growth faded, base WACC, Gordon terminal g=2.5%
        g_base = max(0.05, min(0.32, fwd_rev_growth_0y))
        wacc_base = wacc
        v_base = calculate_scenario_dcf(
            start_fcf=start_fcf, shares=shares, cash=cash, debt=debt,
            wacc=wacc_base, growth_5y=g_base, fade_to_g=0.025, g_terminal=0.025
        )
        base_hypo = "Desempeño alineado al consenso de analistas, márgenes normalizados y convergencia macro."

        # Bull (25% prob): secular acceleration, WACC -50bps, Gordon terminal g=3.0%
        g_bull = min(0.48, g_base * 1.30)
        wacc_bull = max(0.065, wacc - 0.005)
        v_bull = calculate_scenario_dcf(
            start_fcf=start_fcf, shares=shares, cash=cash, debt=debt,
            wacc=wacc_bull, growth_5y=g_bull, fade_to_g=0.030, g_terminal=0.030
        )
        bull_hypo = "Aceleración secular, expansión de márgenes por apalancamiento operativo y sólida captura de cuota de mercado."

    ev_weighted = (0.25 * v_bear) + (0.50 * v_base) + (0.25 * v_bull)
    return {
        'bear': {
            'probability': 0.25,
            'fair_value': round(float(v_bear), 2),
            'growth_assumed_pct': round(float(g_bear if archetype != "FINANCIALS_BANKING" else (roe_bear*100)), 1),
            'wacc_assumed_pct': round(float((wacc_bear if archetype != "FINANCIALS_BANKING" else ke_bear) * 100), 2),
            'hypothesis': bear_hypo
        },
        'base': {
            'probability': 0.50,
            'fair_value': round(float(v_base), 2),
            'growth_assumed_pct': round(float(g_base if archetype != "FINANCIALS_BANKING" else (roe_base*100)), 1),
            'wacc_assumed_pct': round(float((wacc_base if archetype != "FINANCIALS_BANKING" else ke_base) * 100), 2),
            'hypothesis': base_hypo
        },
        'bull': {
            'probability': 0.25,
            'fair_value': round(float(v_bull), 2),
            'growth_assumed_pct': round(float(g_bull if archetype != "FINANCIALS_BANKING" else (roe_bull*100)), 1),
            'wacc_assumed_pct': round(float((wacc_bull if archetype != "FINANCIALS_BANKING" else ke_bull) * 100), 2),
            'hypothesis': bull_hypo
        },
        'expected_weighted_fair_value': round(float(ev_weighted), 2)
    }

def run_monte_carlo(n_sims, start_fcf, shares, cash, debt, base_wacc, base_growth, fcf_volatility=0.025):
    """
    Vectorized 10,000-iteration Monte Carlo Simulation.
    Simulates stochastic revenue/FCF growth, WACC, and terminal multiple/growth.
    """
    np.random.seed(42)  # For reproducible institutional benchmarks
    
    # 1. Growth draws (Años 1-5): Normal centered at base_growth with sigma 3.0%
    growth_draws = np.random.normal(loc=base_growth, scale=0.030, size=(n_sims, 5))
    growth_draws = np.clip(growth_draws, -0.15, 0.45)
    
    # 2. WACC draws: Normal centered at base_wacc with sigma 0.75%
    wacc_draws = np.random.normal(loc=base_wacc, scale=0.0075, size=n_sims)
    wacc_draws = np.clip(wacc_draws, 0.065, 0.14)
    
    # 3. Terminal perpetual growth draws (1.8% to 2.8%)
    g_term_draws = np.random.uniform(0.018, 0.028, size=n_sims)
    
    # Vectorized projection across all 10,000 scenarios
    pv_fcf = np.zeros(n_sims)
    current_fcf = np.full(n_sims, start_fcf)
    
    # Years 1 to 5
    for yr in range(5):
        if yr > 0:
            current_fcf *= (1 + growth_draws[:, yr])
        discount_factor = (1 + wacc_draws) ** (yr + 1)
        pv_fcf += current_fcf / discount_factor
        
    # Years 6 to 10 (Convergence to terminal growth)
    for yr in range(5, 10):
        fade = (yr - 4) / 5.0
        growth_faded = growth_draws[:, 4] * (1 - fade) + g_term_draws * fade
        current_fcf *= (1 + growth_faded)
        discount_factor = (1 + wacc_draws) ** (yr + 1)
        pv_fcf += current_fcf / discount_factor
        
    # Terminal Value via Gordon Growth
    denom = np.maximum(0.015, wacc_draws - g_term_draws)
    tv = (current_fcf * (1 + g_term_draws)) / denom
    pv_tv = tv / ((1 + wacc_draws) ** 10)
    
    # Enterprise & Equity Values
    ev_sims = pv_fcf + pv_tv
    equity_sims = ev_sims + cash - debt
    per_share_sims = np.maximum(0.0, equity_sims / shares)
    
    return per_share_sims

def run_monte_carlo_banking(n_sims, fwd_eps, bvps, roe, ke, g_bank, justified_pb):
    """
    Vectorized Monte Carlo Simulation specialized for Banks & Financial Institutions.
    Simulates stochastic EPS growth, Cost of Equity, terminal P/E multiple, and Justified P/B.
    """
    np.random.seed(42)
    # 1. EPS growth draws (3-year compound growth)
    g_draws = np.random.normal(loc=max(0.04, min(0.14, g_bank * 2.2)), scale=0.030, size=n_sims)
    g_draws = np.clip(g_draws, -0.05, 0.22)
    
    # 2. Cost of equity draws
    ke_draws = np.random.normal(loc=ke, scale=0.006, size=n_sims)
    ke_draws = np.clip(ke_draws, 0.075, 0.135)
    
    # 3. Terminal P/E draws (Fair banking multiple centered at 12.5x with std 1.3x)
    pe_draws = np.random.normal(loc=12.5, scale=1.3, size=n_sims)
    pe_draws = np.clip(pe_draws, 8.5, 16.5)
    
    # 4. Justified P/B draws
    pb_draws = np.random.normal(loc=justified_pb, scale=0.15, size=n_sims)
    pb_draws = np.clip(pb_draws, 0.60, 3.20)
    
    # Forward EPS in year 2 discounted back
    eps_y2 = fwd_eps * (1 + g_draws)
    val_pe_sims = (eps_y2 * pe_draws) / (1 + ke_draws)
    val_pb_sims = pb_draws * bvps
    
    per_share_sims = 0.55 * val_pe_sims + 0.45 * val_pb_sims
    return np.maximum(5.0, per_share_sims)

def fetch_cloud_safe_info(ticker_sym, ticker=None):
    """
    Fetches real-time price, metadata and institutional consensus.
    Guaranteed to work on cloud datacenter IPs (Render, AWS, GCP)
    where yfinance's raw ticker.info gets blocked with 401 Unauthorized.
    """
    sym = str(ticker_sym).strip().upper()
    info = {}
    
    # Static profiles for major mega-caps to guarantee archetype stability under total network blocks
    TOP_PROFILES = {
        'NVDA': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'NVIDIA Corporation'},
        'AAPL': {'sector': 'Technology', 'industry': 'Consumer Electronics', 'longName': 'Apple Inc.'},
        'MSFT': {'sector': 'Technology', 'industry': 'Software - Infrastructure', 'longName': 'Microsoft Corporation'},
        'GOOGL': {'sector': 'Communication Services', 'industry': 'Internet Content & Information', 'longName': 'Alphabet Inc.'},
        'GOOG': {'sector': 'Communication Services', 'industry': 'Internet Content & Information', 'longName': 'Alphabet Inc.'},
        'AMZN': {'sector': 'Consumer Cyclical', 'industry': 'Internet Retail', 'longName': 'Amazon.com, Inc.'},
        'META': {'sector': 'Communication Services', 'industry': 'Internet Content & Information', 'longName': 'Meta Platforms, Inc.'},
        'TSLA': {'sector': 'Consumer Cyclical', 'industry': 'Auto Manufacturers', 'longName': 'Tesla, Inc.'},
        'JPM': {'sector': 'Financial Services', 'industry': 'Banks - Diversified', 'longName': 'JPMorgan Chase & Co.'},
        'BAC': {'sector': 'Financial Services', 'industry': 'Banks - Diversified', 'longName': 'Bank of America Corporation'},
        'WFC': {'sector': 'Financial Services', 'industry': 'Banks - Diversified', 'longName': 'Wells Fargo & Company'},
        'C': {'sector': 'Financial Services', 'industry': 'Banks - Diversified', 'longName': 'Citigroup Inc.'},
        'GS': {'sector': 'Financial Services', 'industry': 'Capital Markets', 'longName': 'Goldman Sachs Group, Inc.'},
        'MS': {'sector': 'Financial Services', 'industry': 'Capital Markets', 'longName': 'Morgan Stanley'},
        'MELI': {'sector': 'Consumer Cyclical', 'industry': 'Internet Retail', 'longName': 'MercadoLibre, Inc.'},
        'NFLX': {'sector': 'Communication Services', 'industry': 'Entertainment', 'longName': 'Netflix, Inc.'},
        'AMD': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'Advanced Micro Devices, Inc.'},
        'INTC': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'Intel Corporation'},
        'TSM': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'Taiwan Semiconductor Manufacturing'},
        'AVGO': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'Broadcom Inc.'},
        'QCOM': {'sector': 'Technology', 'industry': 'Semiconductors', 'longName': 'Qualcomm Inc.'},
        'KO': {'sector': 'Consumer Defensive', 'industry': 'Beverages - Non-Alcoholic', 'longName': 'The Coca-Cola Company'},
        'PEP': {'sector': 'Consumer Defensive', 'industry': 'Beverages - Non-Alcoholic', 'longName': 'PepsiCo, Inc.'},
        'COST': {'sector': 'Consumer Defensive', 'industry': 'Discount Stores', 'longName': 'Costco Wholesale Corporation'},
        'WMT': {'sector': 'Consumer Defensive', 'industry': 'Discount Stores', 'longName': 'Walmart Inc.'},
        'PG': {'sector': 'Consumer Defensive', 'industry': 'Household & Personal Products', 'longName': 'Procter & Gamble Company'},
        'JNJ': {'sector': 'Healthcare', 'industry': 'Drug Manufacturers - General', 'longName': 'Johnson & Johnson'},
        'LLY': {'sector': 'Healthcare', 'industry': 'Drug Manufacturers - General', 'longName': 'Eli Lilly and Company'},
        'UNH': {'sector': 'Healthcare', 'industry': 'Healthcare Plans', 'longName': 'UnitedHealth Group Incorporated'},
        'XOM': {'sector': 'Energy', 'industry': 'Oil & Gas Integrated', 'longName': 'Exxon Mobil Corporation'},
        'CVX': {'sector': 'Energy', 'industry': 'Oil & Gas Integrated', 'longName': 'Chevron Corporation'},
        'CAT': {'sector': 'Industrials', 'industry': 'Farm & Heavy Construction Machinery', 'longName': 'Caterpillar Inc.'},
        'GE': {'sector': 'Industrials', 'industry': 'Aerospace & Defense', 'longName': 'General Electric Company'},
        'BA': {'sector': 'Industrials', 'industry': 'Aerospace & Defense', 'longName': 'The Boeing Company'},
        'BRK.B': {'sector': 'Financial Services', 'industry': 'Insurance - Diversified', 'longName': 'Berkshire Hathaway Inc.'},
        'BRK-B': {'sector': 'Financial Services', 'industry': 'Insurance - Diversified', 'longName': 'Berkshire Hathaway Inc.'},
    }
    
    # 1. Direct public Yahoo Chart API (100% reliable for price, name and dividends without crumb)
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        url_chart = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1y&events=div'
        r = requests.get(url_chart, headers=headers, timeout=5)
        if r.status_code == 200:
            res_data = r.json().get('chart', {}).get('result', [{}])[0]
            meta = res_data.get('meta', {})
            p = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
            if p:
                info['currentPrice'] = float(p)
                info['regularMarketPrice'] = float(p)
            if meta.get('longName'):
                info['longName'] = meta.get('longName')
            if meta.get('shortName'):
                info['shortName'] = meta.get('shortName')
            if meta.get('currency'):
                info['currency'] = meta.get('currency')
            
            # Extract dividends from chart events
            div_events = res_data.get('events', {}).get('dividends', {})
            if div_events:
                trailing_div_sum = sum(float(v.get('amount', 0)) for v in div_events.values())
                if trailing_div_sum > 0:
                    info['dividendRate'] = trailing_div_sum
                    if info.get('currentPrice', 0) > 0:
                        info['dividendYield'] = trailing_div_sum / info['currentPrice']
    except Exception:
        pass

    # 2. Public Yahoo Search API (guaranteed sector, industry, longName on cloud datacenter IPs)
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        url_search = f'https://query1.finance.yahoo.com/v1/finance/search?q={sym}&quotesCount=1&newsCount=0'
        rs = requests.get(url_search, headers=headers, timeout=5)
        if rs.status_code == 200:
            quotes = rs.json().get('quotes', [])
            if quotes:
                q0 = quotes[0]
                if q0.get('sector') and not info.get('sector'):
                    info['sector'] = q0.get('sector')
                if q0.get('industry') and not info.get('industry'):
                    info['industry'] = q0.get('industry')
                if q0.get('longname') and not info.get('longName'):
                    info['longName'] = q0.get('longname')
                if q0.get('shortname') and not info.get('shortName'):
                    info['shortName'] = q0.get('shortname')
    except Exception:
        pass

    # 3. Apply TOP_PROFILES fallback if sector is still missing
    if (not info.get('sector') or info.get('sector') == 'N/A') and sym in TOP_PROFILES:
        prof = TOP_PROFILES[sym]
        info['sector'] = prof['sector']
        info['industry'] = prof['industry']
        if not info.get('longName'):
            info['longName'] = prof['longName']

    # 4. Direct YFinance object methods that do not depend on ticker.info
    if ticker:
        try:
            # Analyst targets
            apt = getattr(ticker, 'analyst_price_targets', None)
            if isinstance(apt, dict):
                if apt.get('mean') and not info.get('targetMeanPrice'):
                    info['targetMeanPrice'] = float(apt['mean'])
                if apt.get('high') and not info.get('targetHighPrice'):
                    info['targetHighPrice'] = float(apt['high'])
                if apt.get('low') and not info.get('targetLowPrice'):
                    info['targetLowPrice'] = float(apt['low'])
                if apt.get('median') and not info.get('targetMedianPrice'):
                    info['targetMedianPrice'] = float(apt['median'])
        except Exception:
            pass

        try:
            # Recommendation opinions count
            rec_sum = getattr(ticker, 'recommendations_summary', None)
            if rec_sum is not None and hasattr(rec_sum, 'iloc') and len(rec_sum) > 0:
                row0 = rec_sum.iloc[0]
                total_ops = sum(int(row0.get(k, 0)) for k in ['strongBuy', 'buy', 'hold', 'sell', 'strongSell'] if k in row0)
                if total_ops > 0 and not info.get('numberOfAnalystOpinions'):
                    info['numberOfAnalystOpinions'] = total_ops
        except Exception:
            pass

        try:
            # Institutional & insider ownership
            mh = getattr(ticker, 'major_holders', None)
            if mh is not None and hasattr(mh, 'index'):
                for idx, row in mh.iterrows():
                    lbl = str(row.iloc[0] if len(row) > 0 else idx).lower()
                    val = safe_float(row.iloc[1] if len(row) > 1 else row.iloc[0])
                    if 'institution' in lbl and 'percent' in lbl and val > 0:
                        info['heldPercentInstitutions'] = val
                    elif 'insider' in lbl and 'percent' in lbl and val > 0:
                        info['heldPercentInsiders'] = val
        except Exception:
            pass

        try:
            # Dividends fallback if chart API missed it
            if not info.get('dividendRate'):
                divs = getattr(ticker, 'dividends', None)
                if divs is not None and not divs.empty:
                    last_1y = divs.tail(4).sum()
                    if last_1y > 0:
                        info['dividendRate'] = float(last_1y)
                        if info.get('currentPrice', 0) > 0 and not info.get('dividendYield'):
                            info['dividendYield'] = float(last_1y) / info['currentPrice']
        except Exception:
            pass

    # 5. Crumb-authenticated quoteSummary session to supplement beta, PE, pegRatio if possible
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        s = requests.Session()
        s.headers.update(headers)
        try:
            s.get('https://fc.yahoo.com', timeout=4)
        except Exception:
            pass
        rc = s.get('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=4)
        crumb = rc.text.strip()
        if crumb and '<' not in crumb:
            modules = 'price,summaryDetail,defaultKeyStatistics,financialData,assetProfile'
            url_qs = f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules={modules}&crumb={crumb}'
            rqs = s.get(url_qs, timeout=6)
            if rqs.status_code == 200:
                raw_res = rqs.json().get('quoteSummary', {}).get('result', [{}])[0]
                def extract(mod, key):
                    val = raw_res.get(mod, {}).get(key)
                    if isinstance(val, dict):
                        return val.get('raw', val.get('fmt'))
                    return val

                for target_k, mod, src_k in [
                    ('currentPrice', 'price', 'regularMarketPrice'),
                    ('regularMarketPrice', 'price', 'regularMarketPrice'),
                    ('longName', 'price', 'longName'),
                    ('shortName', 'price', 'shortName'),
                    ('sector', 'assetProfile', 'sector'),
                    ('industry', 'assetProfile', 'industry'),
                    ('sharesOutstanding', 'defaultKeyStatistics', 'sharesOutstanding'),
                    ('marketCap', 'price', 'marketCap'),
                    ('beta', 'defaultKeyStatistics', 'beta'),
                    ('targetMeanPrice', 'financialData', 'targetMeanPrice'),
                    ('targetHighPrice', 'financialData', 'targetHighPrice'),
                    ('targetLowPrice', 'financialData', 'targetLowPrice'),
                    ('targetMedianPrice', 'financialData', 'targetMedianPrice'),
                    ('numberOfAnalystOpinions', 'financialData', 'numberOfAnalystOpinions'),
                    ('trailingPE', 'summaryDetail', 'trailingPE'),
                    ('forwardPE', 'summaryDetail', 'forwardPE'),
                    ('pegRatio', 'defaultKeyStatistics', 'pegRatio'),
                    ('heldPercentInstitutions', 'defaultKeyStatistics', 'heldPercentInstitutions'),
                    ('heldPercentInsiders', 'defaultKeyStatistics', 'heldPercentInsiders'),
                    ('shortPercentOfFloat', 'defaultKeyStatistics', 'shortPercentOfFloat'),
                    ('shortRatio', 'defaultKeyStatistics', 'shortRatio'),
                    ('dividendYield', 'summaryDetail', 'dividendYield'),
                    ('payoutRatio', 'summaryDetail', 'payoutRatio'),
                    ('ebitda', 'financialData', 'ebitda'),
                ]:
                    val = extract(mod, src_k)
                    if val is not None and not info.get(target_k):
                        info[target_k] = val
    except Exception:
        pass

    # 6. yfinance raw ticker.info if still missing or to supplement
    if ticker:
        try:
            raw_info = getattr(ticker, 'info', None)
            if raw_info and isinstance(raw_info, dict):
                for k, v in raw_info.items():
                    if v is not None and k not in info:
                        info[k] = v
        except Exception:
            pass

    # 7. fast_info fallback
    if (not info.get('currentPrice') or info.get('currentPrice') == 0) and ticker:
        try:
            fi = getattr(ticker, 'fast_info', None)
            if fi:
                p = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                if p:
                    info['currentPrice'] = float(p)
                    info['regularMarketPrice'] = float(p)
                if not info.get('sharesOutstanding'):
                    sh = getattr(fi, 'shares', None)
                    if sh and sh > 0:
                        info['sharesOutstanding'] = float(sh)
                if not info.get('marketCap'):
                    mc = getattr(fi, 'market_cap', None)
                    if mc and mc > 0:
                        info['marketCap'] = float(mc)
        except Exception:
            pass

    # 8. history fallback
    if (not info.get('currentPrice') or info.get('currentPrice') == 0) and ticker:
        try:
            hist = ticker.history(period='5d')
            if hist is not None and not hist.empty and 'Close' in hist:
                p = float(hist['Close'].dropna().iloc[-1])
                if p > 0:
                    info['currentPrice'] = p
                    info['regularMarketPrice'] = p
        except Exception:
            pass

    return info

def analyze_ticker(ticker_sym):
    ticker = yf.Ticker(ticker_sym)
    info = fetch_cloud_safe_info(ticker_sym, ticker)
    
    fin = ticker.financials
    bs = ticker.balance_sheet
    cf = ticker.cashflow
    
    if fin is None or fin.empty or bs is None or bs.empty:
        raise ValueError(f"No financial statements found for ticker {ticker_sym}")

    # Check for more recent quarterly statements to build TTM and MRQ balance sheet
    q_fin = getattr(ticker, 'quarterly_financials', None)
    q_cf = getattr(ticker, 'quarterly_cash_flow', None)
    q_bs = getattr(ticker, 'quarterly_balance_sheet', None)
    
    if q_fin is not None and not q_fin.empty and len(q_fin.columns) >= 4:
        try:
            latest_q_date = str(q_fin.columns[0]).split()[0]
            latest_annual_date = str(fin.columns[0]).split()[0]
            if latest_q_date > latest_annual_date:
                ttm_fin = q_fin.iloc[:, :4].sum(axis=1)
                ttm_fin.name = 'TTM'
                fin = pd.concat([pd.DataFrame(ttm_fin), fin], axis=1)
                
                if q_cf is not None and not q_cf.empty:
                    ttm_cf = q_cf.iloc[:, :4].sum(axis=1)
                    ttm_cf.name = 'TTM'
                    cf = pd.concat([pd.DataFrame(ttm_cf), cf], axis=1)
                    
                if q_bs is not None and not q_bs.empty:
                    mrq_bs = q_bs.iloc[:, 0]
                    mrq_bs.name = 'MRQ'
                    bs = pd.concat([pd.DataFrame(mrq_bs), bs], axis=1)
        except Exception:
            pass
        
    dates = [str(d).split()[0] for d in fin.columns]
    
    def extract_series(df, names, length=None):
        target_len = length if length is not None else len(dates)
        if df is None or df.empty:
            return [0.0] * target_len
        row = get_row(df, names)
        if row is None:
            return [0.0] * target_len
        vals = [safe_float(x) for x in row.values]
        if len(vals) < target_len:
            vals = vals + [0.0] * (target_len - len(vals))
        elif len(vals) > target_len:
            vals = vals[:target_len]
        return vals

    rev = extract_series(fin, ['Total Revenue', 'Operating Revenue'])
    gross_profit = extract_series(fin, ['Gross Profit'])
    ebit = extract_series(fin, ['Operating Income', 'Total Operating Income As Reported', 'EBIT'])
    
    # Ensure operating income does not exceed gross profit for non-financial companies
    for i in range(len(ebit)):
        gp_val = gross_profit[i] if i < len(gross_profit) else 0.0
        if gp_val > 0 and ebit[i] > gp_val:
            ebit[i] = gp_val
    net_income = extract_series(fin, ['Net Income', 'Net Income Common Stockholders', 'Net Income From Continuing And Discontinued Operation'])
    interest_exp = extract_series(fin, ['Interest Expense', 'Net Interest Income'])
    tax_exp = extract_series(fin, ['Tax Provision', 'Income Tax Expense'])
    pretax_inc = extract_series(fin, ['Pretax Income'])
    eps_diluted = extract_series(fin, ['Diluted EPS', 'Basic EPS'])

    cfo = extract_series(cf, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities'])
    capex = extract_series(cf, ['Capital Expenditure'])
    fcf = extract_series(cf, ['Free Cash Flow'])
    sbc = extract_series(cf, ['Stock Based Compensation', 'Stock-Based Compensation'])
    depr = extract_series(cf, ['Depreciation And Amortization', 'Depreciation Amortization Depletion', 'Depreciation'])
    repurchases = extract_series(cf, ['Repurchase Of Capital Stock', 'Common Stock Payments'])
    repurchases = [abs(x) for x in repurchases]

    capex = [abs(x) for x in capex]
    for i in range(len(fcf)):
        cfo_val = cfo[i] if i < len(cfo) else 0.0
        capex_val = capex[i] if i < len(capex) else 0.0
        if fcf[i] == 0.0 and (cfo_val != 0.0 or capex_val != 0.0):
            fcf[i] = cfo_val - capex_val

    assets = extract_series(bs, ['Total Assets'])
    cur_assets = extract_series(bs, ['Current Assets'])
    cur_liab = extract_series(bs, ['Current Liabilities'])
    net_ppe = extract_series(bs, ['Net PPE', 'Property Plant And Equipment Net', 'Gross PPE'])
    total_debt = extract_series(bs, ['Total Debt'])
    cash = extract_series(bs, ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
    equity = extract_series(bs, ['Stockholders Equity', 'Common Stock Equity', 'Total Equity Gross Minority Interest'])
    shares_bs = extract_series(bs, ['Ordinary Shares Number', 'Share Issued'])

    current_price = safe_float(info.get('currentPrice') or info.get('regularMarketPrice'))
    if current_price <= 0.0:
        try:
            fi = getattr(ticker, 'fast_info', None)
            if fi:
                current_price = safe_float(getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None))
        except Exception:
            pass
    if current_price <= 0.0:
        try:
            hist = ticker.history(period='5d')
            if hist is not None and not hist.empty and 'Close' in hist:
                current_price = safe_float(hist['Close'].dropna().iloc[-1])
        except Exception:
            pass

    shares_out = safe_float(info.get('sharesOutstanding'))
    if shares_out <= 0.0:
        try:
            fi = getattr(ticker, 'fast_info', None)
            if fi:
                shares_out = safe_float(getattr(fi, 'shares', None))
        except Exception:
            pass
    if shares_out <= 0.0 and len(shares_bs) > 0 and shares_bs[0] > 0:
        shares_out = float(shares_bs[0])
    if shares_out <= 0.0 and len(eps_diluted) > 0 and eps_diluted[0] > 0 and len(net_income) > 0 and net_income[0] > 0:
        shares_out = float(net_income[0] / eps_diluted[0])
        
    market_cap = safe_float(info.get('marketCap')) or (current_price * shares_out if current_price > 0 and shares_out > 0 else 0.0)
    raw_beta = safe_float(info.get('beta'), default=1.1)
    if raw_beta <= 0.2:
        raw_beta = 1.0

    # Blume Adjusted Beta (Bayesian Mean Reversion towards 1.0)
    blume_beta = 0.67 * raw_beta + 0.33 * 1.00

    # Latest year figures
    t_rev = rev[0]
    t_ebit = ebit[0]
    t_ni = net_income[0]
    t_fcf = fcf[0]
    t_cfo = cfo[0]
    t_assets = assets[0]
    t_debt = total_debt[0]
    t_cash = cash[0]
    t_equity = equity[0]
    t_capex = capex[0]
    t_sbc = sbc[0] if len(sbc) > 0 else 0.0
    t_depr = depr[0] if len(depr) > 0 else 0.0
    t_repurchases = repurchases[0] if len(repurchases) > 0 else 0.0
    t_net_ppe = net_ppe[0] if len(net_ppe) > 0 else 0.0

    eff_tax_rate = 0.21
    if len(pretax_inc) > 0 and pretax_inc[0] > 0 and len(tax_exp) > 0 and tax_exp[0] > 0:
        calc_tax = tax_exp[0] / pretax_inc[0]
        if 0.05 < calc_tax < 0.40:
            eff_tax_rate = calc_tax

    # --- 1. BUSINESS MODEL ARCHETYPE CLASSIFICATION ---
    sector = info.get('sector', 'N/A')
    industry = info.get('industry', 'N/A')
    capex_intensity = (t_capex / t_rev) if t_rev > 0 else 0.0
    gross_margin_calc = (gross_profit[0] / t_rev) if len(gross_profit) > 0 and t_rev > 0 else 0.0

    is_tech_media = (sector in ['Technology', 'Communication Services'] or 
                     any(k in industry.lower() for k in ['software', 'entertainment', 'internet', 'media', 'interactive', 'information tech']))
    is_software_cloud = any(k in industry.lower() for k in ['software', 'interactive', 'internet', 'entertainment', 'cloud', 'information tech'])
    is_semi_or_hardware = any(k in industry.lower() for k in ['semiconductor', 'hardware', 'equipment', 'electronic components', 'memory'])

    # Fabless Semiconductor Check (e.g. NVIDIA, AMD, Qualcomm, Broadcom):
    # These companies design chips and create software/AI ecosystems without owning physical fabs (capex < 6% and gross margin >= 48%).
    # Foundries / Fabs (TSMC, Intel, Micron) have capex intensity > 15-40%.
    is_fabless_tech = (any(k in industry.lower() for k in ['semiconductor']) and 
                       not any(k in industry.lower() for k in ['memory', 'storage', 'equipment', 'electronic components']) and 
                       capex_intensity < 0.08 and gross_margin_calc >= 0.48)

    if is_software_cloud or is_fabless_tech or (is_tech_media and not is_semi_or_hardware and capex_intensity < 0.28):
        archetype = "TECH_ASSET_LIGHT"
        if is_fabless_tech:
            archetype_label = "Semiconductores Fabless / Software & IA (Asset-Light)"
            archetype_desc = "Modelo Fabless (sin fundición pesada). Foco en Rule of 40, FCF Conversion, Ecosistema CUDA y Forward P/E."
        elif is_software_cloud:
            archetype_label = "Software, Cloud & Plataformas Digitales (Asset-Light)"
            archetype_desc = "Modelo SaaS / Infraestructura Cloud. Foco en Rule of 40, FCF Conversion, Forward P/E y Escalabilidad."
        else:
            archetype_label = "Tecnológica / Plataforma Digital (Asset-Light)"
            archetype_desc = "Foco en Rule of 40, FCF Conversion, Forward P/E y Escalabilidad sin Capex Pesado."
    elif is_semi_or_hardware or (sector in ['Technology'] and capex_intensity >= 0.25):
        archetype = "CAPITAL_INTENSIVE_HARDWARE"
        archetype_label = "Hardware / Semiconductores con Fabs (Capital Intensivo)"
        archetype_desc = "Foco en Ciclos de Capex, Capacidad Fab, Graham Floor, Valor Libro Tangible y Normalización de Margen."
    elif (sector in ['Financial Services', 'Banking'] or any(k in industry.lower() for k in ['bank', 'savings', 'capital markets', 'investment banking', 'insurance'])) and not is_tech_media:
        archetype = "FINANCIALS_BANKING"
        archetype_label = "Servicios Financieros / Banca & Mercados de Capital"
        archetype_desc = "Foco en Retorno sobre Patrimonio (ROE), P/TBV Justificado y Solvencia Patrimonial (Equity/Assets)."
    elif sector in ['Consumer Defensive', 'Healthcare']:
        archetype = "CONSUMER_DEFENSIVE"
        archetype_label = "Consumo Defensivo / Salud"
        archetype_desc = "Foco en Poder de Precios, Payout de Dividendos y FCF Estable."
    else:
        archetype = "CAPITAL_INTENSIVE_INDUSTRIAL"
        archetype_label = "Industrial / Manufactura (Capital Intensivo)"
        archetype_desc = "Foco en Activos Tangibles, Capex de Mantenimiento, Graham Number y Ciclos."

    # --- 2. PIOTROSKI F-SCORE (Joseph Piotroski 2000) ---
    f_score_details = {}
    f_total = 0
    if len(dates) >= 2:
        roa_t = t_ni / assets[1] if assets[1] > 0 else 0
        f_roa = 1 if roa_t > 0 else 0
        f_score_details['F_ROA'] = {'score': f_roa, 'val': f"{roa_t*100:.2f}%", 'criteria': 'ROA > 0'}
        f_total += f_roa

        f_cfo = 1 if t_cfo > 0 else 0
        f_score_details['F_CFO'] = {'score': f_cfo, 'val': f"${t_cfo/1e9:.2f}B", 'criteria': 'CFO > 0'}
        f_total += f_cfo

        roa_prev = net_income[1] / assets[1] if len(assets) > 1 and assets[1] > 0 else 0
        f_droa = 1 if roa_t > roa_prev else 0
        f_score_details['F_Delta_ROA'] = {'score': f_droa, 'val': f"Δ {(roa_t - roa_prev)*100:.2f}%", 'criteria': 'ROA_t > ROA_t-1'}
        f_total += f_droa

        f_accrual = 1 if t_cfo > t_ni else 0
        f_score_details['F_ACCRUAL'] = {'score': f_accrual, 'val': f"CFO: ${t_cfo/1e9:.2f}B vs NI: ${t_ni/1e9:.2f}B", 'criteria': 'CFO > Net Income'}
        f_total += f_accrual

        lev_t = t_debt / t_assets if t_assets > 0 else 0
        lev_prev = total_debt[1] / assets[1] if assets[1] > 0 else 0
        f_dlev = 1 if lev_t <= lev_prev else 0
        f_score_details['F_Delta_LEVER'] = {'score': f_dlev, 'val': f"{lev_t*100:.1f}% vs {lev_prev*100:.1f}%", 'criteria': 'Leverage_t <= Leverage_t-1'}
        f_total += f_dlev

        cr_t = cur_assets[0] / cur_liab[0] if len(cur_liab) > 0 and cur_liab[0] > 0 else 1.0
        cr_prev = cur_assets[1] / cur_liab[1] if len(cur_liab) > 1 and cur_liab[1] > 0 else 1.0
        f_dliq = 1 if cr_t >= cr_prev else 0
        f_score_details['F_Delta_LIQUID'] = {'score': f_dliq, 'val': f"{cr_t:.2f} vs {cr_prev:.2f}", 'criteria': 'CR_t >= CR_t-1'}
        f_total += f_dliq

        sh_t = shares_bs[0] if len(shares_bs) > 0 and shares_bs[0] > 0 else shares_out
        sh_prev = shares_bs[1] if len(shares_bs) > 1 and shares_bs[1] > 0 else shares_out
        f_eq = 1 if sh_t <= sh_prev * 1.01 else 0
        f_score_details['EQ_OFFER'] = {'score': f_eq, 'val': f"{sh_t/1e6:.1f}M vs {sh_prev/1e6:.1f}M sh", 'criteria': 'Shares_t <= Shares_t-1'}
        f_total += f_eq

        gm_t = gross_profit[0] / rev[0] if len(gross_profit) > 0 and rev[0] > 0 else 0
        gm_prev = gross_profit[1] / rev[1] if len(gross_profit) > 1 and rev[1] > 0 else 0
        f_dmg = 1 if gm_t >= gm_prev else 0
        f_score_details['F_Delta_MARGIN'] = {'score': f_dmg, 'val': f"{gm_t*100:.1f}% vs {gm_prev*100:.1f}%", 'criteria': 'GrossMargin_t >= GM_t-1'}
        f_total += f_dmg

        turn_t = rev[0] / assets[1] if assets[1] > 0 else 0
        turn_prev = rev[1] / assets[2] if len(assets) > 2 and assets[2] > 0 else (rev[1] / assets[1] if assets[1] > 0 else 0)
        f_turn = 1 if turn_t >= turn_prev else 0
        f_score_details['F_Delta_TURN'] = {'score': f_turn, 'val': f"{turn_t:.2f}x vs {turn_prev:.2f}x", 'criteria': 'Turnover_t >= Turn_t-1'}
        f_total += f_turn

    # --- 3. ALTMAN Z-SCORE (Standard vs Z'' for Services/Tech) ---
    wc = (cur_assets[0] - cur_liab[0]) if len(cur_assets) > 0 and len(cur_liab) > 0 else 0
    retained_earnings = safe_float(get_row(bs, ['Retained Earnings']))
    if isinstance(retained_earnings, list):
        retained_earnings = retained_earnings[0]
    total_liab = safe_float(get_row(bs, ['Total Liabilities Net Minority Interest', 'Total Liabilities']))
    if isinstance(total_liab, list):
        total_liab = total_liab[0]
    if total_liab == 0.0:
        total_liab = t_assets - t_equity

    x1 = wc / t_assets if t_assets > 0 else 0
    x2 = retained_earnings / t_assets if t_assets > 0 else 0
    x3 = t_ebit / t_assets if t_assets > 0 else 0
    x4 = market_cap / total_liab if total_liab > 0 else 1.0
    x4_book = t_equity / total_liab if total_liab > 0 else 1.0
    x5 = t_rev / t_assets if t_assets > 0 else 0
    
    altman_z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 0.999 * x5
    altman_z_prime = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4_book

    if archetype == "FINANCIALS_BANKING":
        equity_to_assets = (t_equity / t_assets * 100) if t_assets > 0 else 0.0
        z_display = equity_to_assets
        z_name = "Solvencia Patrimonial (Equity / Assets)"
        z_zone = "Zona Segura (> 8.0%)" if equity_to_assets >= 8.0 else ("Adecuación Normal (6-8%)" if equity_to_assets >= 6.0 else "Alerta de Capital (< 6.0%)")
    elif archetype == "TECH_ASSET_LIGHT":
        z_display = altman_z_prime
        z_name = "Altman Z''-Score (Servicios/Tech)"
        z_zone = "Zona Segura (Solvencia alta)" if z_display > 2.60 else ("Zona Gris" if z_display >= 1.10 else "Zona de Distress")
    else:
        z_display = altman_z
        z_name = "Altman Z-Score (Industrial)"
        z_zone = "Zona Segura" if z_display > 2.99 else ("Zona Gris" if z_display >= 1.81 else "Zona de Distress")

    # --- 4. MAYER 100-BAGGERS CRITERIA & ASSET-LIGHT METRICS ---
    invested_capital = t_debt + t_equity - t_cash
    nopat = t_ebit * (1 - eff_tax_rate)
    roic = nopat / invested_capital if invested_capital > 0 else 0
    
    rev_cagr_3y = 0.0
    if len(rev) >= 4 and rev[3] > 0 and rev[0] > 0:
        rev_cagr_3y = ((rev[0] / rev[3]) ** (1/3) - 1)
    elif len(rev) >= 3 and rev[2] > 0 and rev[0] > 0:
        rev_cagr_3y = ((rev[0] / rev[2]) ** (1/2) - 1)

    fcf_cagr_3y = 0.0
    if len(fcf) >= 4 and fcf[3] > 0 and fcf[0] > 0:
        fcf_cagr_3y = ((fcf[0] / fcf[3]) ** (1/3) - 1)

    ebitda = safe_float(info.get('ebitda')) or (t_ebit + t_capex * 0.5)
    net_debt = t_debt - t_cash
    if archetype == "FINANCIALS_BANKING":
        net_debt_to_ebitda = 0.0
        interest_coverage = 99.0
    else:
        net_debt_to_ebitda = net_debt / ebitda if ebitda > 0 else 0
        interest_coverage = t_ebit / abs(interest_exp[0]) if len(interest_exp) > 0 and interest_exp[0] != 0 else 99.0

    fcf_conversion_ebitda = (t_fcf / ebitda * 100) if ebitda > 0 else 0.0
    fcf_conversion_ni = (t_fcf / t_ni * 100) if t_ni > 0 else 0.0

    # Quality-Minus-Junk factors (AQR)
    gpoa = gross_profit[0] / t_assets if len(gross_profit) > 0 and t_assets > 0 else 0
    roe = t_ni / t_equity if t_equity > 0 else 0
    roa = t_ni / t_assets if t_assets > 0 else 0
    cfoa = t_cfo / t_assets if t_assets > 0 else 0
    accruals = (t_ni - t_cfo) / t_assets if t_assets > 0 else 0

    # --- 5. COST OF CAPITAL & BETA CALIBRATION ---
    rf = 0.041  # 10Y US Treasury (~4.1%)
    erp = 0.050 # Equity Risk Premium (5.0%)
    ke_raw = rf + raw_beta * erp
    ke_blume = rf + blume_beta * erp
    
    kd = (abs(interest_exp[0]) / t_debt) if t_debt > 0 and len(interest_exp) > 0 and interest_exp[0] != 0 else 0.045
    kd_after_tax = kd * (1 - eff_tax_rate)
    
    total_val = market_cap + t_debt
    we = market_cap / total_val if total_val > 0 else 0.90
    wd = t_debt / total_val if total_val > 0 else 0.10
    
    wacc_raw = we * ke_raw + wd * kd_after_tax
    wacc_blume = we * ke_blume + wd * kd_after_tax
    # For banks, Cost of Equity (Ke) is the discount rate since deposit liabilities are operational
    if archetype == "FINANCIALS_BANKING":
        wacc = ke_blume
    elif archetype == "TECH_ASSET_LIGHT":
        wacc = wacc_blume
    else:
        wacc = wacc_raw
    wacc = max(0.065, min(0.125, wacc))

    # --- 6. FORWARD ESTIMATES & CONSENSUS (WALL STREET & ANALYSTS) ---
    forward_pe = safe_float(info.get('forwardPE'))
    trailing_pe = safe_float(info.get('trailingPE'))
    peg_ratio = safe_float(info.get('pegRatio'))
    forward_eps_info = safe_float(info.get('forwardEps'))
    target_mean = safe_float(info.get('targetMeanPrice'))
    target_high = safe_float(info.get('targetHighPrice'))
    target_low = safe_float(info.get('targetLowPrice'))
    target_median = safe_float(info.get('targetMedianPrice'))
    num_analysts = int(safe_float(info.get('numberOfAnalystOpinions')))

    ee = getattr(ticker, 'earnings_estimate', None)
    re = getattr(ticker, 'revenue_estimate', None)
    
    fwd_eps_0y = safe_float(ee.loc['0y', 'avg']) if ee is not None and not ee.empty and '0y' in ee.index else (forward_eps_info if forward_eps_info > 0 else eps_diluted[0] * 1.12)
    fwd_eps_1y = safe_float(ee.loc['+1y', 'avg']) if ee is not None and not ee.empty and '+1y' in ee.index else (fwd_eps_0y * 1.10)
    
    fwd_rev_0y = safe_float(re.loc['0y', 'avg']) if re is not None and not re.empty and '0y' in re.index else (t_rev * 1.12)
    fwd_rev_1y = safe_float(re.loc['+1y', 'avg']) if re is not None and not re.empty and '+1y' in re.index else (fwd_rev_0y * 1.10)

    fwd_rev_growth_0y = safe_float(re.loc['0y', 'growth']) if re is not None and not re.empty and '0y' in re.index else 0.12
    fwd_eps_growth_0y = safe_float(ee.loc['0y', 'growth']) if ee is not None and not ee.empty and '0y' in ee.index else 0.15

    # --- HISTORICAL 3-YEAR COMPANY FINANCIAL BENCHMARKS ---
    n_hist = min(4, len(rev))
    
    gm_list = [gross_profit[i] / rev[i] for i in range(n_hist) if len(gross_profit) > i and rev[i] > 0]
    hist_gross_margin_avg = float(np.mean(gm_list)) if gm_list else gross_margin_calc

    op_list = [ebit[i] / rev[i] for i in range(n_hist) if len(ebit) > i and rev[i] > 0]
    hist_operating_margin_avg = float(np.mean(op_list)) if op_list else (t_ebit / t_rev if t_rev > 0 else 0.0)

    net_m_list = [net_income[i] / rev[i] for i in range(n_hist) if len(net_income) > i and rev[i] > 0]
    hist_net_margin_avg = float(np.mean(net_m_list)) if net_m_list else (t_ni / t_rev if t_rev > 0 else 0.0)

    fcf_m_list = [fcf[i] / rev[i] for i in range(n_hist) if len(fcf) > i and rev[i] > 0]
    hist_fcf_margin_avg = float(np.mean(fcf_m_list)) if fcf_m_list else (t_fcf / t_rev if t_rev > 0 else 0.0)

    capex_list = [capex[i] / rev[i] for i in range(n_hist) if len(capex) > i and rev[i] > 0]
    hist_capex_intensity_avg = float(np.mean(capex_list)) if capex_list else capex_intensity

    fcf_conv_list = [fcf[i] / net_income[i] for i in range(n_hist) if len(net_income) > i and net_income[i] > 0]
    hist_fcf_conversion_avg = float(np.mean(fcf_conv_list)) * 100 if fcf_conv_list else fcf_conversion_ni

    roic_hist_list = []
    for i in range(n_hist):
        inv_cap = (total_debt[i] if len(total_debt) > i else 0) + (equity[i] if len(equity) > i else 0) - (cash[i] if len(cash) > i else 0)
        nopat_i = (ebit[i] if len(ebit) > i else 0) * (1 - eff_tax_rate)
        if inv_cap > 0 and nopat_i > 0:
            roic_hist_list.append(nopat_i / inv_cap)
    hist_roic_avg = float(np.mean(roic_hist_list)) if roic_hist_list else roic

    # Historical P/E estimate (3y mean price vs 3y mean diluted EPS)
    hist_pe_avg = trailing_pe
    try:
        hist_prices = ticker.history(period="3y")
        if hist_prices is not None and not hist_prices.empty:
            mean_3y_price = float(hist_prices['Close'].mean())
            eps_positive = [eps_diluted[i] for i in range(min(3, len(eps_diluted))) if len(eps_diluted) > i and eps_diluted[i] > 0]
            if eps_positive and np.mean(eps_positive) > 0:
                hist_pe_avg = float(mean_3y_price / np.mean(eps_positive))
    except Exception:
        pass

    # Sector Benchmark Lookup
    sec_bm = get_sector_benchmark(sector, industry)
    
    # Relative Spreads vs Sector
    curr_gross_m = (gross_profit[0] / t_rev) if len(gross_profit) > 0 and t_rev > 0 else 0.0
    curr_op_m = (t_ebit / t_rev) if t_rev > 0 else 0.0
    curr_fcf_m = (t_fcf / t_rev) if t_rev > 0 else 0.0
    curr_ev_ebitda = safe_float(info.get('enterpriseToEbitda')) or (15.0 if ebitda <= 0 else (market_cap + net_debt) / ebitda)
    
    pe_vs_sector_pct = ((trailing_pe - sec_bm['pe']) / sec_bm['pe'] * 100) if (sec_bm['pe'] > 0 and trailing_pe > 0) else 0.0
    pe_vs_hist_pct = ((trailing_pe - hist_pe_avg) / hist_pe_avg * 100) if (hist_pe_avg > 0 and trailing_pe > 0) else 0.0
    roic_spread_sector = (roic - sec_bm['roic']) * 100
    roic_spread_hist = (roic - hist_roic_avg) * 100
    op_m_spread_sector = (curr_op_m - sec_bm['operating_margin']) * 100
    op_m_spread_hist = (curr_op_m - hist_operating_margin_avg) * 100

    # Diagnostic Badges
    if roic_spread_sector >= 7.0:
        moat_diagnostic = "Wide Moat (Ventaja Competitiva Estructural)"
    elif roic_spread_sector >= 2.0:
        moat_diagnostic = "Narrow Moat (Ventaja Competitiva Moderada)"
    else:
        moat_diagnostic = "Sin Moat / Rentabilidad en Línea con la Industria"

    if pe_vs_sector_pct <= -15.0:
        sector_val_diagnostic = "Descuento Significativo vs Sector"
    elif pe_vs_sector_pct <= 15.0:
        sector_val_diagnostic = "Valuación en Línea con el Sector"
    else:
        sector_val_diagnostic = "Prima de Calidad sobre el Sector"

    if pe_vs_hist_pct <= -15.0:
        hist_val_diagnostic = "Descuento Histórico Propio (Oportunidad)"
    elif pe_vs_hist_pct <= 15.0:
        hist_val_diagnostic = "En Rango Histórico Normal"
    else:
        hist_val_diagnostic = "Cotizando con Prima vs su Historial"

    if op_m_spread_hist >= 1.5:
        margin_trend_diagnostic = "Márgenes en Expansión (Apalancamiento Operativo Sano)"
    elif op_m_spread_hist >= -1.5:
        margin_trend_diagnostic = "Márgenes Estables"
    else:
        margin_trend_diagnostic = "Presión o Compresión de Márgenes"

    # 1. Economic FCF Normalization (Float & Working Capital Distortion Filter)
    # Crucial for Fintechs, Payment Platforms & Marketplaces (like MercadoLibre/Mercado Pago, PayPal, Square)
    # where customer deposits enter CFO and artificially inflate apparent FCF by 3x-6x!
    fcf_distortion_flag = False
    fcf_distortion_note = "Estándar (Flujo de caja libre orgánico normal)"
    
    is_fintech_or_payments = (sector in ['Financial Services'] or 
                              any(k in industry.lower() for k in ['fintech', 'banking', 'payment', 'credit', 'internet retail']))
    
    if is_fintech_or_payments and t_ni > 0 and t_fcf > 1.80 * t_ni:
        fcf_distortion_flag = True
        fcf_distortion_note = "Normalizado (Ajustado por depósitos de terceros / float de pagos fintech)"
        sustainable_fcf = min(t_fcf, max(nopat, t_ni * 1.20))
    elif t_fcf <= 0 and t_ni > 0:
        fcf_distortion_flag = True
        fcf_distortion_note = "Normalizado (FCF temporalmente negativo por capex puntual)"
        sustainable_fcf = max(0.0, nopat * 0.70)
    else:
        sustainable_fcf = t_fcf

    fcf_margin_sustainable = (sustainable_fcf / t_rev) if t_rev > 0 else 0.15
    fcf_margin_sustainable = min(0.55, max(0.02, fcf_margin_sustainable))
    projected_fcf_0y = fwd_rev_0y * fcf_margin_sustainable
    rule_of_40 = (fwd_rev_growth_0y + fcf_margin_sustainable) * 100

    # Ownership & Market Sentiment
    inst_own = safe_float(info.get('heldPercentInstitutions')) * 100
    insider_own = safe_float(info.get('heldPercentInsiders')) * 100
    short_pct = safe_float(info.get('shortPercentOfFloat')) * 100
    short_ratio = safe_float(info.get('shortRatio'))
    perf_52w = safe_float(info.get('52WeekChange')) * 100
    sp500_52w = safe_float(info.get('SandP52WeekChange')) * 100
    rel_52w_alpha = perf_52w - sp500_52w

    # --- 7. DETERMINISTIC VALUATION MODELS & CYCLICAL MULTIPLE CALIBRATION ---
    bvps = t_equity / shares_out if shares_out > 0 else 0
    eps_current = safe_float(info.get('trailingEps')) or (t_ni / shares_out if shares_out > 0 else 0)
    
    # Graham Number
    graham_number = math.sqrt(max(0, 22.5 * eps_current * bvps)) if (eps_current > 0 and bvps > 0) else 0.0
    g_graham = max(3.0, min(15.0, rev_cagr_3y * 100))
    graham_revised = (eps_current * (8.5 + 2 * g_graham) * 4.4) / (rf * 100) if rf > 0 else 0.0
    graham_conservative = (eps_current * (7.0 + 1 * g_graham) * 4.4) / (rf * 100) if rf > 0 else 0.0

    # EPV (Bruce Greenwald - Columbia University) with Growth vs Maintenance Capex
    delta_rev = (rev[0] - rev[1]) if len(rev) > 1 else 0.0
    ppe_intensity = (t_net_ppe / t_rev) if t_rev > 0 else 0.0
    if delta_rev > 0 and ppe_intensity > 0:
        growth_capex = min(t_capex, delta_rev * ppe_intensity)
    else:
        growth_capex = 0.0
    maint_capex = max(0.0, t_capex - growth_capex)
    maint_capex_pct = (maint_capex / t_capex * 100.0) if t_capex > 0 else 100.0

    # Greenwald Adjusted Operating Earnings: NOPAT + (Depreciation - Maintenance Capex)
    depr_maint_spread = (t_depr - maint_capex) if t_depr > 0 else 0.0
    nopat_greenwald = max(0.0, nopat + depr_maint_spread)
    greenwald_epv_total = (nopat_greenwald / wacc) + t_cash - t_debt if wacc > 0 else 0.0
    greenwald_epv_per_share = max(0.0, greenwald_epv_total / shares_out) if shares_out > 0 else 0.0

    epv_total = (nopat / wacc) + t_cash - t_debt
    epv_per_share = epv_total / shares_out if shares_out > 0 else 0.0
    growth_premium_pct = ((current_price - epv_per_share) / current_price * 100) if current_price > 0 else 0.0

    # 2. Valuation Benchmarks & Banking Models
    val_pb_justified = 0.0
    justified_pb = 0.0
    val_ddm = 0.0
    roe_bank = 0.0
    g_bank = 0.0

    is_cyclical = (archetype in ["CAPITAL_INTENSIVE_HARDWARE", "CAPITAL_INTENSIVE_INDUSTRIAL"]) and (fwd_rev_growth_0y > 0.45 or fwd_eps_growth_0y > 0.50 or any(k in industry.lower() for k in ['memory', 'storage', 'metal', 'steel', 'commodity']))
    if is_cyclical:
        cyclical_note = "Cíclico (Múltiplos comprimidos para evitar trampa de ciclo pico)"
        fair_pe_benchmark = 12.0
        conservative_pe_benchmark = 9.0
        growth_pe_benchmark = 15.0
    elif archetype == "FINANCIALS_BANKING":
        cyclical_note = "Banca & Finanzas (Valuación P/TBV Justificado y Forward P/E)"
        fair_pe_benchmark = 13.0
        conservative_pe_benchmark = 10.5
        growth_pe_benchmark = 15.0
        
        roe_bank = roe if roe > 0 else 0.12
        payout_ratio_raw = safe_float(info.get('payoutRatio'))
        payout_norm = payout_ratio_raw / 100.0 if payout_ratio_raw > 1.0 else payout_ratio_raw
        payout_norm = max(0.20, min(0.65, payout_norm if payout_norm > 0 else 0.35))
        retention_ratio = 1.0 - payout_norm
        g_bank = min(0.035, max(0.015, roe_bank * retention_ratio))
        
        ke_bank = wacc
        if ke_bank > g_bank:
            justified_pb = (roe_bank - g_bank) / (ke_bank - g_bank)
        else:
            justified_pb = roe_bank / ke_bank
        justified_pb = max(0.60, min(3.20, float(justified_pb)))
        val_pb_justified = justified_pb * bvps
        
        div_rate = safe_float(info.get('dividendRate'))
        if div_rate == 0.0:
            div_yield_val = safe_float(info.get('dividendYield'))
            div_rate = current_price * (div_yield_val / 100.0 if div_yield_val > 0.5 else div_yield_val)
        if div_rate > 0 and ke_bank > g_bank:
            val_ddm = (div_rate * (1 + g_bank)) / (ke_bank - g_bank)
        else:
            val_ddm = fwd_eps_0y * 12.5
    elif archetype == "TECH_ASSET_LIGHT":
        cyclical_note = "Crecimiento Secular (Asset-Light)"
        fair_pe_benchmark = 22.0
        conservative_pe_benchmark = 18.0
        growth_pe_benchmark = 26.0
    elif archetype == "CONSUMER_DEFENSIVE":
        cyclical_note = "Defensivo / Estable"
        fair_pe_benchmark = 20.0
        conservative_pe_benchmark = 16.0
        growth_pe_benchmark = 22.0
    else:
        cyclical_note = "Industrial Estándar"
        fair_pe_benchmark = 16.0
        conservative_pe_benchmark = 12.0
        growth_pe_benchmark = 19.0

    val_pe_conservative = fwd_eps_0y * conservative_pe_benchmark
    val_pe_fair = fwd_eps_0y * fair_pe_benchmark
    val_pe_growth = fwd_eps_0y * growth_pe_benchmark
    val_fcf_20x = (projected_fcf_0y / shares_out) * 20.0 if shares_out > 0 else 0.0
    val_fcf_25x = (projected_fcf_0y / shares_out) * 25.0 if shares_out > 0 else 0.0

    # --- 8. REVERSE DCF (MARKET-IMPLIED GROWTH EXPECTATIONS) ---
    start_fcf_engine = projected_fcf_0y if projected_fcf_0y > 0 else sustainable_fcf
    if archetype == "FINANCIALS_BANKING":
        ke_bank = wacc
        implied_roe = ((current_price / bvps) * (ke_bank - g_bank) + g_bank) if bvps > 0 else 0.12
        implied_growth = (implied_roe - roe_bank)
        growth_gap = implied_growth
        if implied_roe > roe_bank * 1.15:
            implied_sentiment = f"Exigente (El mercado descuenta un ROE de {implied_roe*100:.1f}% vs {roe_bank*100:.1f}% actual)"
        elif implied_roe >= roe_bank * 0.88:
            implied_sentiment = f"Racional (ROE implícito de {implied_roe*100:.1f}% en línea con rentabilidad histórica)"
        else:
            implied_sentiment = f"Descuento / Escéptico (El mercado descuenta compresión de ROE a {implied_roe*100:.1f}%)"
    else:
        implied_growth = solve_reverse_dcf(
            target_price=current_price,
            start_fcf=start_fcf_engine,
            shares=shares_out,
            cash=t_cash,
            debt=t_debt,
            wacc=wacc,
            g_terminal=0.025
        )
        growth_gap = implied_growth - fwd_rev_growth_0y
        if growth_gap > 0.05:
            implied_sentiment = "Exigente (El mercado exige mayor aceleración de FCF que las ventas)"
        elif growth_gap >= -0.02:
            implied_sentiment = "Racional (Expectativas de crecimiento alineadas al consenso)"
        else:
            implied_sentiment = "Escéptico / Descuento (El mercado descuenta una desaceleración severa)"

    # --- 9. MONTE CARLO SIMULATION (10,000 ITERATIONS) ---
    if archetype == "FINANCIALS_BANKING":
        mc_sims = run_monte_carlo_banking(
            n_sims=10000,
            fwd_eps=fwd_eps_0y,
            bvps=bvps,
            roe=roe_bank,
            ke=wacc,
            g_bank=g_bank,
            justified_pb=justified_pb
        )
    else:
        if archetype == "TECH_ASSET_LIGHT":
            base_growth_mc = max(0.12, min(0.38, 0.50 * fwd_rev_growth_0y + 0.50 * implied_growth if implied_growth > 0 else fwd_rev_growth_0y))
        else:
            base_growth_mc = max(0.06, min(0.18, fwd_rev_growth_0y if fwd_rev_growth_0y > 0 else 0.10))

        mc_sims = run_monte_carlo(
            n_sims=10000,
            start_fcf=start_fcf_engine,
            shares=shares_out,
            cash=t_cash,
            debt=t_debt,
            base_wacc=wacc,
            base_growth=base_growth_mc
        )
    
    mc_mean = float(np.mean(mc_sims))
    mc_median = float(np.median(mc_sims))
    mc_std = float(np.std(mc_sims))
    mc_p10 = float(np.percentile(mc_sims, 10))
    mc_p25 = float(np.percentile(mc_sims, 25))
    mc_p75 = float(np.percentile(mc_sims, 75))
    mc_p90 = float(np.percentile(mc_sims, 90))
    prob_undervalued = float(np.mean(mc_sims >= current_price) * 100.0)

    # --- 10. OPERATIONS RESEARCH DECISION OPTIMIZATION (KELLY & MCDA) ---
    upside_b = max(0.01, mc_p90 - current_price)
    downside_a = max(0.01, current_price - mc_p10)
    b_ratio = upside_b / downside_a if downside_a > 0 else 1.0
    p_win = prob_undervalued / 100.0
    q_loss = 1.0 - p_win
    
    kelly_full = (p_win * b_ratio - q_loss) / b_ratio if b_ratio > 0 else 0.0
    kelly_half = max(0.0, min(0.20, kelly_full * 0.50)) # Cap at 20% portfolio risk

    # Multi-Criteria Decision Analysis (MCDA) Scoring (0 to 100)
    score_valuation = min(30.0, max(0.0, (prob_undervalued / 100.0) * 20.0 + (10.0 if peg_ratio < 1.3 else 5.0)))
    score_quality = min(30.0, max(0.0, (min(0.40, roic) / 0.40) * 15.0 + (f_total / 9.0) * 15.0))
    if archetype == "FINANCIALS_BANKING":
        score_solvency = min(20.0, max(0.0, (12.0 if z_display >= 8.0 else 6.0) + (8.0 if f_total >= 6 else 4.0)))
    else:
        score_solvency = min(20.0, max(0.0, (10.0 if z_display > 2.60 else 5.0) + (10.0 if net_debt_to_ebitda < 1.0 else 5.0)))
    score_sentiment = min(20.0, max(0.0, (10.0 if inst_own > 70.0 else 5.0) + (10.0 if short_pct < 4.0 else 4.0)))
    mcda_total_score = score_valuation + score_quality + score_solvency + score_sentiment

    if mcda_total_score >= 80.0:
        mcda_rating = "CONVICCIÓN ALTA (Compounder de Élite con Fundamentos Blindados)"
    elif mcda_total_score >= 65.0:
        mcda_rating = "CONVICCIÓN MODERADA-ALTA (Crecimiento de Calidad a Precio Racional)"
    elif mcda_total_score >= 50.0:
        mcda_rating = "CONVICCIÓN NEUTRAL (Mantener / Monitorear Valoración)"
    else:
        mcda_rating = "CONVICCIÓN BAJA (Riesgo de Valuación o Deterioro Operativo)"

    # Final Strict Probabilistic Scenarios & Composite Fair Value
    scenarios = calculate_probabilistic_scenarios(
        archetype=archetype,
        fwd_rev_growth_0y=fwd_rev_growth_0y,
        fwd_eps_0y=fwd_eps_0y,
        start_fcf=start_fcf_engine,
        shares=shares_out,
        cash=t_cash,
        debt=t_debt,
        wacc=wacc,
        conservative_pe=conservative_pe_benchmark,
        fair_pe=fair_pe_benchmark,
        growth_pe=growth_pe_benchmark,
        bvps=bvps,
        roe_bank=roe_bank,
        g_bank=g_bank,
        epv_per_share=epv_per_share,
        current_price=current_price
    )
    ev_val = scenarios['expected_weighted_fair_value']

    if archetype == "FINANCIALS_BANKING":
        composite_fair_value = (ev_val * 0.50) + (mc_median * 0.30) + (val_pb_justified * 0.20)
    elif archetype == "TECH_ASSET_LIGHT":
        floor_anchor = max(epv_per_share, val_pe_conservative) if epv_per_share > 0 else val_pe_conservative
        composite_fair_value = (ev_val * 0.55) + (mc_median * 0.30) + (floor_anchor * 0.15)
    elif archetype in ["CAPITAL_INTENSIVE_HARDWARE", "CAPITAL_INTENSIVE_INDUSTRIAL"]:
        floor_anchor = graham_number if graham_number > 0 else epv_per_share
        if floor_anchor > 0:
            composite_fair_value = (ev_val * 0.50) + (mc_median * 0.30) + (floor_anchor * 0.20)
        else:
            composite_fair_value = (ev_val * 0.60) + (mc_median * 0.40)
    else:
        composite_fair_value = (ev_val * 0.55) + (mc_median * 0.30) + (val_pe_conservative * 0.15)
        
    if composite_fair_value >= current_price:
        margin_of_safety = ((composite_fair_value - current_price) / composite_fair_value * 100) if composite_fair_value > 0 else 0.0
    else:
        margin_of_safety = ((composite_fair_value - current_price) / current_price * 100) if current_price > 0 else -99.9

    # Strict Value Investing Verdict (Graham / Klarman Standard)
    if margin_of_safety >= 25.0:
        rec_verdict = "SUBVALUADA / OPORTUNIDAD CON AMPLIO MARGEN DE SEGURIDAD"
    elif margin_of_safety >= 10.0:
        rec_verdict = "VALORACIÓN ATRACTIVA / MARGEN MODERADO"
    elif margin_of_safety >= -10.0:
        rec_verdict = "VALOR RAZONABLE / MANTENER (Fair Value)"
    else:
        rec_verdict = "SOBREVALORADA / SIN MARGEN DE SEGURIDAD"

    # --- 11. SHAREHOLDER YIELD & BUYBACK POWER ---
    div_yield_raw = safe_float(info.get('dividendYield'))
    div_yield_pct = (div_yield_raw * 100.0) if (0 < div_yield_raw <= 0.20) else div_yield_raw
    payout_raw = safe_float(info.get('payoutRatio'))
    payout_pct = (payout_raw * 100.0) if (0 < payout_raw <= 1.5) else payout_raw

    net_share_change_3y_pct = 0.0
    if len(shares_bs) >= 4 and shares_bs[3] > 0 and shares_bs[0] > 0:
        net_share_change_3y_pct = ((shares_bs[0] - shares_bs[3]) / shares_bs[3]) * 100.0
    elif len(shares_bs) >= 2 and shares_bs[1] > 0 and shares_bs[0] > 0:
        net_share_change_3y_pct = ((shares_bs[0] - shares_bs[1]) / shares_bs[1]) * 100.0

    if net_share_change_3y_pct < -0.5:
        buyback_annual_yield = abs(net_share_change_3y_pct) / (3.0 if len(shares_bs) >= 4 else 1.0)
        buyback_status = f"Recompra Neta Activa (-{abs(net_share_change_3y_pct):.1f}% acciones en 3y)"
    elif net_share_change_3y_pct > 1.5:
        buyback_annual_yield = 0.0
        buyback_status = f"Dilución de Capital (+{net_share_change_3y_pct:.1f}% acciones en 3y)"
    else:
        buyback_annual_yield = 0.0
        buyback_status = "Flotante Estable / Sin Recompras Masivas"

    total_shareholder_yield = div_yield_pct + buyback_annual_yield

    # --- ACADEMIC PAPERS METRICS & EXPECTED 5-YEAR CAGR ---
    # 1. Expected 5-Year CAGR (TIR Estimada a 5 Años)
    def calc_5y_cagr(target_p, cur_p, yield_pct):
        if cur_p <= 0 or target_p <= 0:
            return 0.0
        return float(((target_p / cur_p) ** (1.0 / 5.0) - 1.0) * 100.0 + yield_pct)

    cagr_base = calc_5y_cagr(scenarios['base']['fair_value'], current_price, total_shareholder_yield)
    cagr_bear = calc_5y_cagr(scenarios['bear']['fair_value'], current_price, total_shareholder_yield)
    cagr_bull = calc_5y_cagr(scenarios['bull']['fair_value'], current_price, total_shareholder_yield)
    # Expected TIR as mathematical expectation: 25% Bear + 50% Base + 25% Bull
    cagr_expected = (0.25 * cagr_bear) + (0.50 * cagr_base) + (0.25 * cagr_bull)

    if cagr_expected >= 15.0:
        cagr_verdict = "Atractivo Superior (TIR proyectada supera ampliamente el benchmark de 10% del S&P 500)"
    elif cagr_expected >= 10.0:
        cagr_verdict = "Rendimiento Competitivo (En línea con la media histórica del mercado accionario)"
    elif cagr_expected >= 4.1:
        cagr_verdict = "Rendimiento Moderado (Supera al bono del Tesoro 4.1% pero con prima de riesgo reducida)"
    else:
        cagr_verdict = "Rendimiento Insuficiente (Riesgo de bajo retorno o erosión patrimonial)"

    # 2. Aswath Damodaran (NYU Stern) - Stock-Based Compensation & Real Economic FCF
    real_economic_fcf = t_fcf - t_sbc
    sbc_pct_rev = (t_sbc / t_rev * 100.0) if t_rev > 0 else 0.0
    dilution_offset_pct = (t_sbc / t_repurchases * 100.0) if t_repurchases > 0 else 0.0
    if sbc_pct_rev >= 4.0:
        sbc_note = f"Impacto Elevado ({sbc_pct_rev:.1f}% de ingresos). FCF contable sobrestima caja real distribuible por dilución en opciones."
    elif sbc_pct_rev >= 1.5:
        sbc_note = f"Impacto Moderado ({sbc_pct_rev:.1f}% de ingresos). Absorbe parte de las recompras brutas."
    else:
        sbc_note = f"Impacto Mínimo ({sbc_pct_rev:.1f}% de ingresos). Sin distorsión relevante de FCF."

    # 3. Richard Sloan (1996) - Accrual Anomaly & Forensic Earnings Quality
    sloan_ratio = (t_ni - t_cfo) / t_assets if t_assets > 0 else 0.0
    sloan_pct = sloan_ratio * 100.0
    if sloan_pct <= -5.0:
        sloan_cat = "Excelente (CFO > Utilidad Contable: Beneficios respaldados plenamente por caja real)"
        sloan_grade = "ALTA_CALIDAD"
    elif sloan_pct <= 5.0:
        sloan_cat = "Sana / Normal (Devengos contables equilibrados con la generación operativa)"
        sloan_grade = "SANA"
    else:
        sloan_cat = "Alerta de Devengos (Ganancias sobre papel con riesgo de reversión contable)"
        sloan_grade = "ALERTA"

    # 4. Robert Novy-Marx (2013) & AQR QMJ - Gross Profitability of Assets (GPOA)
    gpoa_pct = (gross_profit[0] / t_assets * 100.0) if (len(gross_profit) > 0 and t_assets > 0) else 0.0
    if gpoa_pct >= 40.0:
        gpoa_grade = "Productividad de Élite (Moat de Rentabilidad Bruta Excepcional)"
    elif gpoa_pct >= 25.0:
        gpoa_grade = "Alta Productividad Económica de Activos"
    elif gpoa_pct >= 12.0:
        gpoa_grade = "Productividad Normal / Promedio de Mercado"
    else:
        gpoa_grade = "Baja Rentabilidad sobre Activos"

    # 5. Michael Mauboussin (2013) - Competitive Advantage Period (CAP) & Fade Horizon
    if roic_spread_sector >= 7.0:
        cap_years = 10
        cap_note = "Wide Moat: Horizonte de Ventaja Competitiva de 10 Años con persistencia de retornos excedentes (ROIC > WACC)."
    elif roic_spread_sector >= 2.0:
        cap_years = 5
        cap_note = "Narrow Moat: Ventaja competitiva moderada con convergencia gradual hacia el costo de capital a 5 años."
    else:
        cap_years = 3
        cap_note = "Sin Moat Estructural: Rápida convergencia competitiva hacia WACC en 3 años."

    # --- 12. SNOWFLAKE RADAR 5-PILLAR INSTITUTIONAL SCORING (0-100) ---
    # Pillar 1: Value
    score_v = 0.0
    if margin_of_safety >= 20.0:
        score_v += 40.0
    elif margin_of_safety >= 10.0:
        score_v += 32.0
    elif margin_of_safety >= 0.0:
        score_v += 24.0
    elif margin_of_safety >= -15.0:
        score_v += 14.0
    else:
        score_v += 6.0

    if pe_vs_sector_pct <= -15.0:
        score_v += 30.0
    elif pe_vs_sector_pct <= 0.0:
        score_v += 22.0
    elif pe_vs_sector_pct <= 20.0:
        score_v += 14.0
    else:
        score_v += 6.0

    if peg_ratio > 0 and peg_ratio <= 1.0:
        score_v += 30.0
    elif peg_ratio > 0 and peg_ratio <= 1.6:
        score_v += 22.0
    elif peg_ratio > 0 and peg_ratio <= 2.5:
        score_v += 14.0
    else:
        score_v += 10.0
    score_v = float(min(100.0, max(5.0, score_v)))

    # Pillar 2: Future Growth
    score_f = 0.0
    if fwd_rev_growth_0y >= 0.25:
        score_f += 35.0
    elif fwd_rev_growth_0y >= 0.12:
        score_f += 28.0
    elif fwd_rev_growth_0y >= 0.05:
        score_f += 20.0
    else:
        score_f += 10.0

    if fwd_eps_growth_0y >= 0.25:
        score_f += 35.0
    elif fwd_eps_growth_0y >= 0.12:
        score_f += 28.0
    elif fwd_eps_growth_0y >= 0.05:
        score_f += 20.0
    else:
        score_f += 10.0

    if target_mean > current_price * 1.15:
        score_f += 30.0
    elif target_mean > current_price:
        score_f += 20.0
    else:
        score_f += 8.0
    score_f = float(min(100.0, max(5.0, score_f)))

    # Pillar 3: Past Performance
    score_p = 0.0
    if rev_cagr_3y >= 0.20:
        score_p += 35.0
    elif rev_cagr_3y >= 0.10:
        score_p += 28.0
    elif rev_cagr_3y >= 0.04:
        score_p += 20.0
    else:
        score_p += 10.0

    metric_return = roe if archetype == "FINANCIALS_BANKING" else roic
    if metric_return >= 0.20:
        score_p += 35.0
    elif metric_return >= 0.14:
        score_p += 28.0
    elif metric_return >= 0.08:
        score_p += 18.0
    else:
        score_p += 8.0

    if op_m_spread_hist >= 1.0:
        score_p += 30.0
    elif op_m_spread_hist >= -1.0:
        score_p += 22.0
    else:
        score_p += 10.0
    score_p = float(min(100.0, max(5.0, score_p)))

    # Pillar 4: Financial Health
    score_h = 0.0
    if archetype == "FINANCIALS_BANKING":
        if z_display >= 8.5:
            score_h += 40.0
        elif z_display >= 7.0:
            score_h += 30.0
        else:
            score_h += 15.0
        score_h += (f_total / 9.0) * 35.0
        score_h += 25.0
    else:
        if z_display > 2.99:
            score_h += 35.0
        elif z_display >= 1.81:
            score_h += 25.0
        else:
            score_h += 10.0

        if net_debt_to_ebitda <= 0.5:
            score_h += 35.0
        elif net_debt_to_ebitda <= 1.5:
            score_h += 25.0
        elif net_debt_to_ebitda <= 3.0:
            score_h += 15.0
        else:
            score_h += 5.0

        if interest_coverage >= 10.0:
            score_h += 30.0
        elif interest_coverage >= 3.5:
            score_h += 20.0
        else:
            score_h += 8.0
    score_h = float(min(100.0, max(5.0, score_h)))

    # Pillar 5: Dividends & Buybacks
    score_d = 0.0
    if total_shareholder_yield >= 5.0:
        score_d += 40.0
    elif total_shareholder_yield >= 3.0:
        score_d += 30.0
    elif total_shareholder_yield >= 1.5:
        score_d += 20.0
    elif total_shareholder_yield >= 0.5:
        score_d += 12.0
    else:
        score_d += 4.0

    if 10.0 <= payout_pct <= 65.0:
        score_d += 30.0
    elif 0 < payout_pct <= 80.0:
        score_d += 20.0
    else:
        score_d += 6.0

    if buyback_annual_yield >= 1.5:
        score_d += 30.0
    elif buyback_annual_yield > 0.0:
        score_d += 22.0
    elif net_share_change_3y_pct <= 1.0:
        score_d += 15.0
    else:
        score_d += 5.0
    score_d = float(min(100.0, max(5.0, score_d)))

    snowflake_scores = {
        'value': round(score_v, 1),
        'future': round(score_f, 1),
        'past': round(score_p, 1),
        'health': round(score_h, 1),
        'dividends': round(score_d, 1)
    }

    # Assemble Result Object
    result = {
        'company_name': info.get('shortName') or info.get('longName') or ticker_sym,
        'ticker': ticker_sym.upper(),
        'sector': sector,
        'industry': industry,
        'archetype': archetype,
        'archetype_label': archetype_label,
        'archetype_desc': archetype_desc,
        'currency': info.get('currency', 'USD'),
        'current_price': current_price,
        'market_cap': market_cap,
        'shares_outstanding': shares_out,
        'beta': {
            'raw_beta': raw_beta,
            'blume_adjusted_beta': blume_beta
        },
        'cost_of_capital': {
            'wacc': wacc,
            'cost_of_equity': ke_blume if archetype == "TECH_ASSET_LIGHT" else ke_raw,
            'cost_of_debt': kd_after_tax,
            'effective_tax_rate': eff_tax_rate
        },
        'market_sentiment_and_ownership': {
            'institutional_ownership_pct': inst_own,
            'insider_ownership_pct': insider_own,
            'short_percent_of_float': short_pct,
            'short_ratio_days': short_ratio,
            'relative_52w_alpha_vs_sp500': rel_52w_alpha,
            'num_analysts': num_analysts,
            'target_mean_price': target_mean,
            'target_median_price': target_median,
            'target_low_price': target_low,
            'target_high_price': target_high
        },
        'tech_asset_light_kpis': {
            'is_tech_asset_light': (archetype == "TECH_ASSET_LIGHT"),
            'capital_intensity_pct': capex_intensity * 100,
            'fcf_conversion_ebitda_pct': fcf_conversion_ebitda,
            'fcf_conversion_ni_pct': fcf_conversion_ni,
            'rule_of_40_score': rule_of_40,
            'rule_of_40_status': 'Élite (>40%)' if rule_of_40 >= 40.0 else ('Sólido (30-40%)' if rule_of_40 >= 30.0 else 'Moderado')
        },
        'latest_financials': {
            'revenue': t_rev,
            'operating_income_ebit': t_ebit,
            'net_income': t_ni,
            'free_cash_flow': t_fcf,
            'fcf': t_fcf,
            'operating_cash_flow': t_cfo,
            'total_assets': t_assets,
            'total_debt': t_debt,
            'cash_and_equiv': t_cash,
            'net_debt': net_debt,
            'stockholders_equity': t_equity,
            'eps_diluted': eps_current,
            'bvps': bvps,
            'gross_margin': (gross_profit[0] / t_rev) if t_rev > 0 else 0,
            'operating_margin': (t_ebit / t_rev) if t_rev > 0 else 0,
            'net_margin': (t_ni / t_rev) if t_rev > 0 else 0,
            'fcf_margin': (t_fcf / t_rev) if t_rev > 0 else 0,
            'roe': roe * 100
        },
        'forward_consensus': {
            'trailing_pe': trailing_pe,
            'forward_pe': forward_pe,
            'peg_ratio': peg_ratio,
            'fwd_eps_0y': fwd_eps_0y,
            'fwd_eps_1y': fwd_eps_1y,
            'fwd_eps_growth_0y': fwd_eps_growth_0y,
            'fwd_rev_0y': fwd_rev_0y,
            'fwd_rev_1y': fwd_rev_1y,
            'fwd_rev_growth_0y': fwd_rev_growth_0y
        },
        'piotroski_fscore': {
            'total_score': f_total,
            'max_score': 9,
            'category': 'Alta Calidad' if f_total >= 8 else ('Saludable' if f_total >= 6 else 'Neutral'),
            'details': f_score_details
        },
        'altman_solvency': {
            'z_score': z_display,
            'model_used': z_name,
            'zone': z_zone
        },
        'mayer_100_bagger_metrics': {
            'roic': roic,
            'roic_status': 'Sobresaliente (>15%)' if roic >= 0.15 else 'Aceptable',
            'net_debt_to_ebitda': net_debt_to_ebitda,
            'interest_coverage': interest_coverage
        },
        'reverse_dcf': {
            'implied_fcf_growth_5y_pct': implied_growth * 100,
            'consensus_revenue_growth_pct': fwd_rev_growth_0y * 100,
            'gap_pct': growth_gap * 100,
            'market_sentiment': implied_sentiment
        },
        'monte_carlo_simulation': {
            'iterations': 10000,
            'mean_fair_value': mc_mean,
            'median_fair_value': mc_median,
            'std_dev': mc_std,
            'percentile_10_floor': mc_p10,
            'percentile_25_defensive': mc_p25,
            'percentile_75_optimistic': mc_p75,
            'percentile_90_bull_ceiling': mc_p90,
            'prob_undervalued_pct': prob_undervalued
        },
        'probabilistic_scenarios': scenarios,
        'expected_5y_cagr': {
            'cagr_expected_weighted_pct': round(cagr_expected, 2),
            'cagr_base_pct': round(cagr_base, 2),
            'cagr_bear_pct': round(cagr_bear, 2),
            'cagr_bull_pct': round(cagr_bull, 2),
            'shareholder_yield_added_pct': round(total_shareholder_yield, 2),
            'sp500_spread_pct': round(cagr_expected - 10.0, 2),
            'treasury_spread_pct': round(cagr_expected - 4.1, 2),
            'cagr_verdict': cagr_verdict
        },
        'academic_forensics': {
            'damodaran_sbc': {
                'reported_fcf': t_fcf,
                'stock_based_compensation': t_sbc,
                'real_economic_fcf': real_economic_fcf,
                'sbc_pct_revenue': round(sbc_pct_rev, 2),
                'sbc_dilution_offset_pct': round(dilution_offset_pct, 1),
                'dilution_drag_note': sbc_note,
                'paper_reference': "Aswath Damodaran (NYU Stern 2020) Real FCF post-SBC"
            },
            'greenwald_capex': {
                'total_capex': t_capex,
                'growth_capex': growth_capex,
                'maintenance_capex': maint_capex,
                'maintenance_capex_pct': round(maint_capex_pct, 1),
                'greenwald_adjusted_epv': round(greenwald_epv_per_share, 2),
                'net_ppe': t_net_ppe,
                'paper_reference': "Bruce Greenwald (Columbia University) Value Investing"
            },
            'sloan_accruals': {
                'accrual_ratio_pct': round(sloan_pct, 2),
                'quality_rating': sloan_cat,
                'quality_grade': sloan_grade,
                'is_cash_backed': sloan_pct <= 5.0,
                'paper_reference': "Richard Sloan (1996) The Accounting Review"
            },
            'novy_marx_profitability': {
                'gpoa_pct': round(gpoa_pct, 2),
                'productivity_rating': gpoa_grade,
                'paper_reference': "Robert Novy-Marx (2013) Journal of Financial Economics"
            },
            'mauboussin_moat': {
                'moat_rating': moat_diagnostic,
                'cap_years': cap_years,
                'fade_horizon_note': cap_note,
                'paper_reference': "Michael Mauboussin (Credit Suisse / Morgan Stanley 2013)"
            }
        },
        'valuation_models': {
            'epv_per_share': epv_per_share,
            'greenwald_epv_per_share': round(greenwald_epv_per_share, 2),
            'growth_premium_pct': growth_premium_pct,
            'graham_number_tangible_floor': graham_number,
            'graham_revised': graham_revised,
            'graham_conservative': graham_conservative,
            'val_pe_conservative': val_pe_conservative,
            'val_pe_fair': val_pe_fair,
            'val_pe_growth': val_pe_growth,
            'fair_pe_benchmark': fair_pe_benchmark,
            'conservative_pe_benchmark': conservative_pe_benchmark,
            'growth_pe_benchmark': growth_pe_benchmark,
            'val_pb_justified': val_pb_justified,
            'justified_pb_ratio': justified_pb,
            'val_ddm': val_ddm,
            'roe_bank': roe_bank,
            'val_pe_conservative_20x': val_pe_conservative,
            'val_pe_fair_25x': val_pe_fair,
            'val_pe_growth_30x': val_pe_growth,
            'val_pe_cyclical_10x': fwd_eps_0y * 10.0,
            'val_pe_cyclical_12x': fwd_eps_0y * 12.0,
            'val_fcf_20x': val_fcf_20x,
            'val_fcf_25x': val_fcf_25x
        },
        'shareholder_yield': {
            'dividend_yield_pct': round(div_yield_pct, 2),
            'payout_ratio_pct': round(payout_pct, 1),
            'buyback_annual_yield_pct': round(buyback_annual_yield, 2),
            'total_shareholder_yield_pct': round(total_shareholder_yield, 2),
            'net_share_change_3y_pct': round(net_share_change_3y_pct, 1),
            'buyback_status': buyback_status
        },
        'snowflake_scores': snowflake_scores,
        'accounting_adjustments': {
            'fcf_distortion_detected': fcf_distortion_flag,
            'fcf_adjustment_note': fcf_distortion_note,
            'raw_fcf': t_fcf,
            'sustainable_fcf': sustainable_fcf,
            'is_cyclical': is_cyclical,
            'cyclical_note': cyclical_note,
            'fair_pe_applied': fair_pe_benchmark,
            'conservative_pe_applied': conservative_pe_benchmark
        },
        'competitive_benchmarking': {
            'sector_benchmark_name': sec_bm['name'],
            'company_current': {
                'pe_trailing': trailing_pe,
                'pe_forward': forward_pe,
                'ev_ebitda': curr_ev_ebitda,
                'gross_margin_pct': curr_gross_m * 100,
                'operating_margin_pct': curr_op_m * 100,
                'fcf_margin_pct': curr_fcf_m * 100,
                'roic_pct': roic * 100,
                'capex_intensity_pct': capex_intensity * 100,
                'rev_growth_pct': fwd_rev_growth_0y * 100,
                'net_debt_to_ebitda': net_debt_to_ebitda
            },
            'company_historical_3y': {
                'pe_trailing_avg': hist_pe_avg,
                'gross_margin_pct': hist_gross_margin_avg * 100,
                'operating_margin_pct': hist_operating_margin_avg * 100,
                'fcf_margin_pct': hist_fcf_margin_avg * 100,
                'roic_pct': hist_roic_avg * 100,
                'capex_intensity_pct': hist_capex_intensity_avg * 100,
                'fcf_conversion_ni_pct': hist_fcf_conversion_avg,
                'rev_cagr_3y_pct': rev_cagr_3y * 100
            },
            'sector_benchmark': {
                'pe': sec_bm['pe'],
                'ev_ebitda': sec_bm['ev_ebitda'],
                'gross_margin_pct': sec_bm['gross_margin'] * 100,
                'operating_margin_pct': sec_bm['operating_margin'] * 100,
                'fcf_margin_pct': sec_bm['fcf_margin'] * 100,
                'roic_pct': sec_bm['roic'] * 100,
                'capex_intensity_pct': sec_bm['capex_intensity'] * 100,
                'rev_growth_pct': sec_bm['rev_growth'] * 100,
                'net_debt_to_ebitda': sec_bm['net_debt_to_ebitda']
            },
            'relative_spreads': {
                'pe_vs_sector_pct': pe_vs_sector_pct,
                'pe_vs_hist_pct': pe_vs_hist_pct,
                'roic_spread_vs_sector': roic_spread_sector,
                'roic_spread_vs_hist': roic_spread_hist,
                'op_margin_spread_vs_sector': op_m_spread_sector,
                'op_margin_spread_vs_hist': op_m_spread_hist
            },
            'diagnostics': {
                'moat_rating': moat_diagnostic,
                'sector_valuation_rating': sector_val_diagnostic,
                'historical_valuation_rating': hist_val_diagnostic,
                'margin_trend_rating': margin_trend_diagnostic
            }
        },
        'operations_research_optimization': {
            'kelly_criterion_full_pct': kelly_full * 100,
            'half_kelly_recommended_pct': kelly_half * 100,
            'mcda_composite_score_100': mcda_total_score,
            'mcda_conviction_rating': mcda_rating
        },
        'valuation_summary': {
            'composite_fair_value': composite_fair_value,
            'expected_weighted_fair_value': ev_val,
            'current_price': current_price,
            'margin_of_safety_pct': margin_of_safety,
            'verdict': rec_verdict
        }
    }
    return result

def print_mega_executive_report(res):
    p = res['valuation_summary']
    f = res['latest_financials']
    piot = res['piotroski_fscore']
    mayer = res['mayer_100_bagger_metrics']
    fwd = res['forward_consensus']
    kpi = res['tech_asset_light_kpis']
    solv = res['altman_solvency']
    mc = res['monte_carlo_simulation']
    rev_dcf = res['reverse_dcf']
    sent = res['market_sentiment_and_ownership']
    opt = res['operations_research_optimization']
    
    print("=" * 85)
    print(f" VALUADOR CUANTITATIVO INSTITUCIONAL: {res['company_name']} ({res['ticker']})")
    print(f" Perfil de Negocio: {res['archetype_label']}")
    print(f" Metodología Prioritaria: {res['archetype_desc']}")
    print("=" * 85)
    print(f"Precio Actual: ${p['current_price']:.2f} {res['currency']} | Market Cap: ${res['market_cap']/1e9:.2f}B | WACC: {res['cost_of_capital']['wacc']*100:.2f}%")
    print(f"Beta Raw: {res['beta']['raw_beta']:.2f} -> Beta Blume Ajustado: {res['beta']['blume_adjusted_beta']:.2f} (Atenuación Bayesiana)")
    print("-" * 85)
    
    print("1. RADIOGRAFÍA DE CALIDAD Y EFICIENCIA OPERATIVA (PAPERS AUDITADOS):")
    print(f" • Piotroski F-Score:      {piot['total_score']}/9 ({piot['category']}) | Altman Solvencia: {solv['z_score']:.2f} [{solv['zone']}]")
    print(f" • ROIC (Christopher Mayer):{mayer['roic']*100:.2f}% [{mayer['roic_status']}] (Spread sobre WACC: +{(mayer['roic']-res['cost_of_capital']['wacc'])*100:.2f}%)")
    print(f" • Estructura de Capital:  Deuda Neta/EBITDA: {mayer['net_debt_to_ebitda']:.2f}x | Cobertura Intereses: {mayer['interest_coverage']:.1f}x")
    print(f" • Márgenes Reales:        Bruto {f['gross_margin']*100:.1f}% | Operativo {f['operating_margin']*100:.1f}% | FCF {f['fcf_margin']*100:.1f}%")
    if res['archetype'] == "FINANCIALS_BANKING":
        print(f" • Solvencia Bancaria:     {solv['z_score']:.1f}% [{solv['zone']}] (Patrimonio Neto / Activos Totales)")
        print(f" • Retorno Patrimonio:     ROE {f.get('roe', 0):.1f}% | P/TBV Justificado: {res['valuation_models']['justified_pb_ratio']:.2f}x (${res['valuation_models']['val_pb_justified']:.2f} USD)")
        print(f" • Rendimiento Accionista: Dividendo: {res['shareholder_yield']['dividend_yield_pct']:.1f}% | Recompra 3y: {res['shareholder_yield']['buyback_annual_yield_pct']:.1f}% | Total: {res['shareholder_yield']['total_shareholder_yield_pct']:.1f}%")
        print(f" • Recompras y Flotante:   {res['shareholder_yield']['buyback_status']}")
    elif kpi['is_tech_asset_light']:
        print(f" • Regla del 40 (Tech):    {kpi['rule_of_40_score']:.1f}% [{kpi['rule_of_40_status']}] (Crecimiento Ventas + Margen FCF)")
        print(f" • Intensidad de Capex:    {kpi['capital_intensity_pct']:.1f}% (Asset-Light -> Expansión sin quema de capital)")
        print(f" • Conversión a Efectivo:  FCF / EBITDA: {kpi['fcf_conversion_ebitda_pct']:.1f}% | FCF / Utilidad Neta: {kpi['fcf_conversion_ni_pct']:.1f}%")
        print(f" • Rendimiento Accionista: Total: {res['shareholder_yield']['total_shareholder_yield_pct']:.1f}% (Div: {res['shareholder_yield']['dividend_yield_pct']:.1f}%, Recompra: {res['shareholder_yield']['buyback_annual_yield_pct']:.1f}%)")
    else:
        print(f" • Intensidad de Capex:    {kpi['capital_intensity_pct']:.1f}% (Infraestructura de Fabs / Capital Intensivo)")
        print(f" • Conversión a Efectivo:  FCF / EBITDA: {kpi['fcf_conversion_ebitda_pct']:.1f}% | FCF / Utilidad Neta: {kpi['fcf_conversion_ni_pct']:.1f}%")
        print(f" • Piso de Graham (Tangible): ${res['valuation_models']['graham_number_tangible_floor']:.2f} USD | BVPS: ${f['bvps']:.2f} USD")
        print(f" • Rendimiento Accionista: Total: {res['shareholder_yield']['total_shareholder_yield_pct']:.1f}% (Div: {res['shareholder_yield']['dividend_yield_pct']:.1f}%, Recompra: {res['shareholder_yield']['buyback_annual_yield_pct']:.1f}%)")
    print("-" * 85)

    print("2. REVERSE DCF (EXPECTATIVAS IMPLÍCITAS DE MERCADO):")
    print(f" • Crecimiento FCF que exige el precio actual (${p['current_price']:.2f}): {rev_dcf['implied_fcf_growth_5y_pct']:.2f}% anual")
    print(f" • Crecimiento de Ventas proyectado por analistas:      {rev_dcf['consensus_revenue_growth_pct']:.2f}% anual")
    print(f" • Diagnóstico de Expectativas:                         {rev_dcf['market_sentiment']}")
    print("-" * 85)

    print("3. SIMULACIÓN DE MONTE CARLO (10.000 ITERACIONES ESTOCÁSTICAS):")
    print(f" • Media Simulada:     ${mc['mean_fair_value']:.2f} | Mediana (P50): ${mc['median_fair_value']:.2f} | Desvío: ±${mc['std_dev']:.2f}")
    print(f" • Percentil 10 (Piso Conservador): ${mc['percentile_10_floor']:.2f}  (El 90% de las simulaciones supera este valor)")
    print(f" • Percentil 25 (Valor Defensivo):  ${mc['percentile_25_defensive']:.2f}")
    print(f" • Percentil 75 (Valor Optimista):  ${mc['percentile_75_optimistic']:.2f}")
    print(f" • Percentil 90 (Techo Alcista):    ${mc['percentile_90_bull_ceiling']:.2f}")
    print(f" • PROBABILIDAD ESTADÍSTICA DE SUBVALUACIÓN: {mc['prob_undervalued_pct']:.1f}%")
    print("-" * 85)

    print("4. SENTIMIENTO DE MERCADO, INSTITUCIONES Y CONTRARIAN MOMENTUM:")
    print(f" • Tenencia Institucional: {sent['institutional_ownership_pct']:.1f}% (Fuerte respaldo de fondos institucionales)")
    print(f" • Posiciones Cortas (Short Float): {sent['short_percent_of_float']:.2f}% (Bajo interés bajista / Cobertura: {sent['short_ratio_days']:.1f} días)")
    print(f" • Consenso Wall Street:   Target Promedio ${sent['target_mean_price']:.2f} (Upside: +{((sent['target_mean_price']-p['current_price'])/p['current_price'])*100:.1f}%)")
    print(f" • Alpha Relativo 52 Sem:  {sent['relative_52w_alpha_vs_sp500']:+.1f}% vs S&P 500 (Oportunidad de compresión / Reversión a la media)")
    print("-" * 85)

    print("5. INVESTIGACIÓN OPERATIVA: CRITERIO DE KELLY Y SCORING MCDA (0-100):")
    print(f" • Score Institucional MCDA:   {opt['mcda_composite_score_100']:.1f} / 100 -> {opt['mcda_conviction_rating']}")
    print(f" • Asignación Óptima (Kelly):  {opt['half_kelly_recommended_pct']:.1f}% del portafolio (Half-Kelly para control estricto de volatilidad)")
    print("-" * 85)

    bm = res.get('competitive_benchmarking', {})
    cur = bm.get('company_current', {})
    hist = bm.get('company_historical_3y', {})
    sec = bm.get('sector_benchmark', {})
    diag = bm.get('diagnostics', {})
    sp = bm.get('relative_spreads', {})
    
    print(f"6. BENCHMARKING COMPETITIVO (HISTÓRICO 3Y Y SECTOR: {bm.get('sector_benchmark_name', 'Sector')}):")
    print(f" • Múltiplo P/E Trailing:  Actual: {cur.get('pe_trailing', 0):.1f}x | Histórico 3y: {hist.get('pe_trailing_avg', 0):.1f}x | Sector: {sec.get('pe', 0):.1f}x (Dif vs Sector: {sp.get('pe_vs_sector_pct', 0):+.1f}%)")
    print(f" • Margen Operativo EBIT:  Actual: {cur.get('operating_margin_pct', 0):.1f}% | Histórico 3y: {hist.get('operating_margin_pct', 0):.1f}% | Sector: {sec.get('operating_margin_pct', 0):.1f}% (Spread: {sp.get('op_margin_spread_vs_sector', 0):+.1f}%)")
    print(f" • Retorno Capital (ROIC): Actual: {cur.get('roic_pct', 0):.1f}% | Histórico 3y: {hist.get('roic_pct', 0):.1f}% | Sector: {sec.get('roic_pct', 0):.1f}% (Spread Moat: {sp.get('roic_spread_vs_sector', 0):+.1f}%)")
    print(f" • Diagnóstico Competitivo: {diag.get('moat_rating', '')} | {diag.get('sector_valuation_rating', '')}")
    print(f" • Diagnóstico Histórico:   {diag.get('margin_trend_rating', '')} | {diag.get('historical_valuation_rating', '')}")
    print("-" * 85)

    print("7. VEREDICTO FINAL Y MARGEN DE SEGURIDAD INTEGRADO:")
    print(f" • VALOR INTRÍNSECO COMPUESTO: ${p['composite_fair_value']:.2f} USD")
    print(f" • PRECIO DE COTIZACIÓN ACTUAL: ${p['current_price']:.2f} USD")
    print(f" • MARGEN DE SEGURIDAD (MoS):   {p['margin_of_safety_pct']:+.2f}%")
    print(f" • DECISIÓN DE INVERSIÓN:       {p['verdict']}")
    print("=" * 85)

if __name__ == '__main__':
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else 'NFLX'
    output_json = '--json' in sys.argv
    
    res = analyze_ticker(ticker_arg)
    
    if output_json:
        print(json.dumps(res, indent=2))
    else:
        print_mega_executive_report(res)
        with open(f"valuation_{ticker_arg.lower()}.json", "w", encoding="utf-8") as fp:
            json.dump(res, fp, indent=2)
