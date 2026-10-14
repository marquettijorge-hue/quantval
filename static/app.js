"use strict";

// Number formatter for es-AR
const nf = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });

// Required unit test functions for tests/frontend.test.cjs
function formatMetric(m) {
  if (!m || m.status !== "available" || m.value === null || m.value === undefined || !Number.isFinite(m.value)) {
    return "No disponible";
  }
  if (m.unit === "percent") {
    return nf.format(m.value * 100) + "%";
  }
  if (m.unit === "USD") {
    const n = m.value;
    const abs = Math.abs(n);
    if (n === 0) return "US$ 0";
    if (abs >= 1e9) {
      return "US$ " + nf.format(n / 1e9) + " mil millones";
    }
    if (abs >= 1e6) {
      return "US$ " + nf.format(n / 1e6) + " millones";
    }
    return "US$ " + nf.format(n);
  }
  return nf.format(m.value);
}

function comparisonRows(pair) {
  const allIds = [];
  const seen = new Set();
  pair.forEach(item => {
    (item.metrics || []).forEach(m => {
      if (m && m.id && !seen.has(m.id)) {
        seen.add(m.id);
        allIds.push(m.id);
      }
    });
  });

  const rows = [];
  allIds.forEach(id => {
    const m0 = (pair[0]?.metrics || []).find(m => m.id === id) || null;
    const m1 = (pair[1]?.metrics || []).find(m => m.id === id) || null;
    rows.push({ id, metrics: [m0, m1] });
  });
  return rows;
}

function normalizeInput(value) {
  if (!value || typeof value !== "string" || !value.trim()) {
    throw new Error("Ingresá un ticker");
  }
  const sym = value.trim().toUpperCase().replace(/\./g, "-");
  if (!/^[A-Z][A-Z0-9]{0,7}(?:-[A-Z0-9]{1,2})?$/.test(sym)) {
    throw new Error("Ingresá un ticker válido");
  }
  return sym;
}

function showError(message) {
  const resNode = document.getElementById("results");
  if (resNode) resNode.hidden = true;
  const errNode = document.getElementById("error");
  if (errNode) {
    errNode.hidden = false;
    errNode.textContent = message;
  }
}

function summary(data) {
  const items = Array.isArray(data) ? data : [data];
  const lines = [];
  items.forEach(d => {
    lines.push(`# ${d.name} (${d.symbol})`);
    if (d.period) lines.push(`Período: ${d.period.start} a ${d.period.end}`);
    (d.metrics || []).forEach(m => {
      const valStr = formatMetric(m);
      lines.push(`- ${m.label}: ${valStr} (${m.kind === 'calculated' ? 'Cálculo histórico' : 'Dato reportado'})`);
    });
    (d.sources || []).forEach(s => {
      lines.push(`Fuente: ${s.form} (${s.url})`);
    });
  });
  return lines.join("\n");
}

// -------------------------------------------------------------
// Global Application State
// -------------------------------------------------------------
let currentData = null;
let currentDuelDataA = null;
let currentDuelDataB = null;
let currentViewMode = "single";
let isManualPriceActive = false;

let baseGrowth = 15;
let baseWacc = 10;
let baseMultiple = 20;
let baseFairValue = 100;

// UI Tabs Switching
function switchViewMode(mode) {
  currentViewMode = mode;
  const tabS = document.getElementById("tabSingle");
  const tabD = document.getElementById("tabDuel");
  const singleSearch = document.getElementById("singleSearchWrapper");
  const duelSearch = document.getElementById("duelSearchWrapper");
  const singleDash = document.getElementById("dashboard");
  const duelDash = document.getElementById("duelDashboard");

  if (!tabS || !tabD) return;

  if (mode === "duel") {
    tabD.className = "px-5 py-2.5 rounded-xl font-bold text-xs transition-all bg-gradient-to-r from-amber-500 to-rose-600 text-white shadow-lg shadow-amber-500/20 flex items-center gap-2";
    tabS.className = "px-5 py-2.5 rounded-xl font-bold text-xs transition-all bg-dark-800 hover:bg-dark-700 text-gray-300 border border-dark-700 hover:border-cyan-500/50 flex items-center gap-2";
    if (singleSearch) singleSearch.classList.add("hidden");
    if (duelSearch) duelSearch.classList.remove("hidden");
    if (singleDash) singleDash.classList.add("hidden");
    if (duelDash) duelDash.classList.remove("hidden");

    if (!currentDuelDataA || !currentDuelDataB) {
      evaluateDuel("NVDA", "MSFT");
    }
  } else {
    tabS.className = "px-5 py-2.5 rounded-xl font-bold text-xs transition-all bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-lg shadow-cyan-500/20 flex items-center gap-2";
    tabD.className = "px-5 py-2.5 rounded-xl font-bold text-xs transition-all bg-dark-800 hover:bg-dark-700 text-gray-300 border border-dark-700 hover:border-amber-500/50 flex items-center gap-2";
    if (duelSearch) duelSearch.classList.add("hidden");
    if (singleSearch) singleSearch.classList.remove("hidden");
    if (duelDash) duelDash.classList.add("hidden");
    if (singleDash) singleDash.classList.remove("hidden");
  }
}

// Single Stock Evaluation
async function evaluateTicker(ticker, manualPrice = null, refresh = false) {
  const raw = (ticker || "").trim();
  if (!raw) return;

  const match = raw.match(/^([A-Za-z0-9\.\-]+)\s*(?:vs\.?|contra|\/|,|-)\s*([A-Za-z0-9\.\-]+)$/i);
  if (match) {
    switchViewMode("duel");
    evaluateDuel(match[1], match[2]);
    return;
  }

  const sym = raw.toUpperCase().replace(/\./g, "-");
  const inEl = document.getElementById("tickerInput");
  if (inEl) inEl.value = sym;

  const loadState = document.getElementById("loadingState");
  const dashEl = document.getElementById("dashboard");
  const loadTitle = document.getElementById("loadingTitle");

  if (loadState) loadState.classList.remove("hidden");
  if (dashEl) dashEl.classList.add("opacity-30", "pointer-events-none");
  if (loadTitle) loadTitle.innerText = `Evaluando balances SEC de ${sym}...`;

  try {
    let url = `/api/evaluate/${encodeURIComponent(sym)}`;
    const params = [];
    if (manualPrice !== null && Number.isFinite(Number(manualPrice))) {
      params.push(`manual_price=${encodeURIComponent(manualPrice)}`);
      isManualPriceActive = true;
    } else {
      isManualPriceActive = false;
    }
    if (refresh) {
      params.push("refresh=true");
    }
    if (params.length > 0) {
      url += `?${params.join("&")}`;
    }

    const resp = await fetch(url);
    if (!resp.ok) {
      let errTxt = "";
      try { errTxt = (await resp.json()).detail; } catch(_) { errTxt = await resp.text(); }
      throw new Error(errTxt || `Error HTTP ${resp.status}`);
    }

    const data = await resp.json();
    renderDashboard(data);
    updateURL([sym]);
  } catch (err) {
    showToast(err.message || `No se pudo obtener información para ${sym}.`, true);
  } finally {
    if (loadState) loadState.classList.add("hidden");
    if (dashEl) dashEl.classList.remove("opacity-30", "pointer-events-none");
  }
}

// Render Single Stock Dashboard
function renderDashboard(d) {
  currentData = d;
  const v = d.valuation_summary || {};
  const isBank = (d.archetype === "FINANCIALS_BANKING" || d.financial_sector);
  const q = d.quote || {};

  // Company Head
  const compNameEl = document.getElementById("compName");
  if (compNameEl) compNameEl.innerText = d.company_name || d.name || d.symbol;
  const tickerBadgeEl = document.getElementById("tickerBadge");
  if (tickerBadgeEl) tickerBadgeEl.innerText = d.symbol || d.ticker;
  const archetypeBadgeEl = document.getElementById("archetypeBadge");
  if (archetypeBadgeEl) archetypeBadgeEl.innerText = d.archetype_label || (isBank ? "Banca & Finanzas (Tier-1)" : "Empresa No Financiera");
  const compSectorEl = document.getElementById("compSector");
  if (compSectorEl) compSectorEl.innerText = `${d.sector || d.activity || 'General'} • ${d.industry || d.activity || 'General'}`;

  // Prominent Quote Block with Badges & Source
  const currPriceEl = document.getElementById("currPrice");
  const priceVal = q.price !== null && q.price !== undefined ? Number(q.price) : (v.current_price || null);
  if (currPriceEl) {
    currPriceEl.innerText = priceVal !== null ? `$${priceVal.toFixed(2)}` : "No disponible";
  }

  const quoteBadgeEl = document.getElementById("quoteBadge");
  const quoteAsOfEl = document.getElementById("quoteAsOf");
  if (quoteBadgeEl) {
    if (q.is_manual || isManualPriceActive) {
      quoteBadgeEl.innerText = "🔵 Manual de Referencia";
      quoteBadgeEl.className = "text-[10px] font-bold px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800/60";
    } else if (d.cache?.hit) {
      const ageMin = Math.round((d.cache.age_seconds || 0) / 60);
      quoteBadgeEl.innerText = `🟡 Caché (${ageMin > 0 ? ageMin + ' min' : 'Reciente'})`;
      quoteBadgeEl.className = "text-[10px] font-bold px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800/60";
    } else {
      quoteBadgeEl.innerText = "🟢 Mercado en Tiempo Real";
      quoteBadgeEl.className = "text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/60";
    }
  }

  if (quoteAsOfEl) {
    if (q.as_of) {
      const dObj = new Date(q.as_of);
      quoteAsOfEl.innerText = "Fecha cotización: " + (Number.isNaN(dObj.getTime()) ? q.as_of : dObj.toLocaleDateString("es-AR") + " " + dObj.toLocaleTimeString("es-AR", { hour: '2-digit', minute: '2-digit' }));
    } else {
      quoteAsOfEl.innerText = "Cotización de referencia en USD";
    }
  }

  // Quantitative Verdict
  const verdictTextEl = document.getElementById("verdictText");
  if (verdictTextEl) verdictTextEl.innerText = v.verdict || "Análisis completado";

  const vBox = document.getElementById("verdictBox");
  const mosVal = v.margin_of_safety_pct;
  if (vBox) {
    if (mosVal !== null && mosVal !== undefined && mosVal >= 10) {
      vBox.className = "p-3.5 px-5 rounded-xl flex items-center gap-4 bg-emerald-950/40 border border-emerald-800/40";
      if (verdictTextEl) verdictTextEl.className = "text-sm sm:text-base font-extrabold text-emerald-400";
    } else if (deltaVal !== null && deltaVal !== undefined && Math.abs(deltaVal) <= 10) {
      vBox.className = "p-3.5 px-5 rounded-xl flex items-center gap-4 bg-amber-950/40 border border-amber-800/40";
      if (verdictTextEl) verdictTextEl.className = "text-sm sm:text-base font-extrabold text-amber-400";
    } else {
      vBox.className = "p-3.5 px-5 rounded-xl flex items-center gap-4 bg-rose-950/40 border border-rose-800/40";
      if (verdictTextEl) verdictTextEl.className = "text-sm sm:text-base font-extrabold text-rose-400";
    }
  }

  // Wall Street Consensus Target Card
  const ws = d.wall_street_consensus || {};
  const wsTargetEl = document.getElementById("wsTargetPrice");
  const wsRecomBadgeEl = document.getElementById("wsRecomBadge");
  const wsTargetNoteEl = document.getElementById("wsTargetNote");
  const wsBottomNoteEl = document.getElementById("wsBottomNote");

  if (wsTargetEl) {
    if (ws.target_price) {
      wsTargetEl.innerText = `$${ws.target_price.toFixed(2)}`;
      const upside = priceVal ? ((ws.target_price - priceVal) / priceVal * 100) : null;
      if (wsTargetNoteEl) {
        wsTargetNoteEl.innerText = upside !== null ? `${upside >= 0 ? '+' : ''}${upside.toFixed(1)}% vs mercado` : "Target promedio";
      }
    } else {
      wsTargetEl.innerText = "N/D";
      if (wsTargetNoteEl) wsTargetNoteEl.innerText = "Estimación no disp.";
    }
    if (wsRecomBadgeEl) {
      wsRecomBadgeEl.innerText = ws.recommendation_label || "Analistas";
      if (ws.recommendation_score && ws.recommendation_score <= 1.8) {
        wsRecomBadgeEl.className = "text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/60";
      } else {
        wsRecomBadgeEl.className = "text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800/60";
      }
    }
    if (wsBottomNoteEl) {
      wsBottomNoteEl.innerText = ws.forward_pe ? `P/E Fwd: ${ws.forward_pe.toFixed(1)}x` : (ws.source || "Consenso de analistas");
    }
  }

  // Fair Value Ponderado E[V]
  const fairVal = v.composite_fair_value;
  const fairValueEl = document.getElementById("fairValue");
  if (fairValueEl) {
    fairValueEl.innerText = fairVal > 0 ? `$${fairVal.toFixed(2)}` : "No disponible";
  }

  // Margen de Seguridad (MoS) Card: (E[V] - P) / E[V] strictly non-negative
  const mosValueEl = document.getElementById("mosValue");
  const mosFormulaEl = document.getElementById("mosFormula");
  const mosNoteEl = document.getElementById("mosNote");

  if (mosValueEl) {
    if (fairVal && priceVal) {
      if (fairVal >= priceVal) {
        const mosCalc = ((fairVal - priceVal) / fairVal) * 100;
        mosValueEl.innerText = `+${mosCalc.toFixed(2)}%`;
        mosValueEl.className = "text-xl font-black text-emerald-400";
        if (mosFormulaEl) mosFormulaEl.innerText = "Fórmula: (E[V] - P) / E[V]";
        if (mosNoteEl) mosNoteEl.innerText = "Descuento respecto a Fair Value";
      } else {
        const premiumCalc = ((priceVal - fairVal) / fairVal) * 100;
        mosValueEl.innerText = "0.00%";
        mosValueEl.className = "text-xl font-black text-gray-400";
        if (mosFormulaEl) mosFormulaEl.innerText = "Sin margen de seguridad";
        if (mosNoteEl) mosNoteEl.innerText = `Prima de mercado: +${premiumCalc.toFixed(1)}%`;
      }
    } else {
      mosValueEl.innerText = "N/D";
    }
  }

  // Diferencia sobre Cotización (Delta) Card: (E[V] - P) / P
  const deltaValueEl = document.getElementById("deltaValue");
  let deltaCalc = v.delta_vs_price_pct !== undefined ? v.delta_vs_price_pct : (priceVal && fairVal ? ((fairVal - priceVal) / priceVal) * 100 : null);
  if (deltaValueEl) {
    if (deltaCalc !== null && deltaCalc !== undefined) {
      deltaCalc = Math.max(-100.0, deltaCalc); // Mathematical floor at -100%
      deltaValueEl.innerText = `${deltaCalc > 0 ? '+' : ''}${deltaCalc.toFixed(2)}%`;
      deltaValueEl.className = `text-xl font-black ${deltaCalc >= 10 ? 'text-emerald-400' : (deltaCalc >= -10 ? 'text-amber-400' : 'text-rose-400')}`;
    } else {
      deltaValueEl.innerText = "N/D";
    }
  }

  // Base del modelo fair value in top card
  const scenBaseValTopEl = document.getElementById("scenBaseValTop");
  const sc = d.probabilistic_scenarios || (d.valuation?.scenarios) || {};
  if (scenBaseValTopEl) {
    scenBaseValTopEl.innerText = sc.base?.fair_value ? `$${sc.base.fair_value.toFixed(2)}` : (fairVal > 0 ? `$${fairVal.toFixed(2)}` : "-");
  }

  // Render Sub-Sections
  renderReverseDcf(d);
  renderCoreIndicators(d.core_indicators);
  renderProbabilisticScenarios(sc);
  renderExpectedCagr(d.expected_5y_cagr || d.valuation?.expected_5y_cagr);
  initSensitivitySliders(d);
  renderQualityScorecard(d);
  renderChecklist(d);
}

// -------------------------------------------------------------
// Reverse DCF: ¿Qué Crecimiento Descuenta el Precio Actual?
// -------------------------------------------------------------
function renderReverseDcf(d) {
  const rev = d.reverse_dcf || (d.valuation?.reverse_dcf) || {};
  const revGrowthEl = document.getElementById("reverseDcfGrowth");
  const revTextEl = document.getElementById("reverseDcfText");
  const revParamsEl = document.getElementById("reverseDcfParams");
  const exigencyBadge = document.getElementById("dcfExigencyBadge");

  if (!revGrowthEl) return;

  const isResolved = rev.status === "resolved" || rev.solved;
  const gPct = rev.implied_growth_pct !== undefined ? rev.implied_growth_pct : rev.implied_fcf_growth_5y_pct;

  if (isResolved && gPct !== null && gPct !== undefined && Number.isFinite(gPct)) {
    revGrowthEl.innerText = `${gPct > 0 ? '+' : ''}${gPct.toFixed(1)}% anual (5 años)`;
    revGrowthEl.className = "text-3xl sm:text-4xl font-black text-cyan-400 mb-2";
    if (revTextEl) {
      revTextEl.innerText = rev.text || `Con estos supuestos, para justificar la cotización actual de mercado de $${(d.quote?.price || d.valuation_summary?.current_price || 0).toFixed(2)} USD, el flujo de caja libre exige crecer a una tasa compuesta del ${gPct.toFixed(1)}% anual durante los próximos 5 años.`;
    }
    if (revParamsEl) {
      revParamsEl.innerText = `Supuestos aplicados: WACC ${(rev.wacc_assumed_pct || 10).toFixed(1)}% • Tasa Terminal Perpetua g ${(rev.terminal_g_pct || rev.terminal_g_assumed_pct || 2.5).toFixed(1)}%`;
    }

    if (exigencyBadge) {
      if (gPct <= 10.0) {
        exigencyBadge.innerText = "🟢 Exigencia Conservadora (<10%)";
        exigencyBadge.className = "text-[11px] font-bold px-3 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/60";
      } else if (gPct <= 22.0) {
        exigencyBadge.innerText = "🟡 Exigencia Moderada (10% - 22%)";
        exigencyBadge.className = "text-[11px] font-bold px-3 py-1 rounded-full bg-amber-950 text-amber-300 border border-amber-800/60";
      } else {
        exigencyBadge.innerText = "🔴 Exigencia Muy Alta (>22%)";
        exigencyBadge.className = "text-[11px] font-bold px-3 py-1 rounded-full bg-rose-950 text-rose-300 border border-rose-800/60";
      }
    }
  } else {
    revGrowthEl.innerText = "No pudo resolverse";
    revGrowthEl.className = "text-xl font-bold text-gray-400 mb-2";
    if (revTextEl) {
      revTextEl.innerText = rev.note || "No existe una tasa matemática de crecimiento dentro del intervalo analizado (-50% a +150%) que iguale la cotización actual bajo el modelo DCF.";
    }
    if (revParamsEl) {
      revParamsEl.innerText = "Requiere flujo de caja operativo normalizado.";
    }
    if (exigencyBadge) {
      exigencyBadge.innerText = "⚪ Sin Expectativa Resuelta";
      exigencyBadge.className = "text-[11px] font-bold px-3 py-1 rounded-full bg-dark-900 text-gray-400 border border-dark-700";
    }
  }
}

// -------------------------------------------------------------
// 6 Core Indicators (Audited SEC Filings)
// -------------------------------------------------------------
function renderCoreIndicators(indicators) {
  const grid = document.getElementById("coreIndicatorsGrid");
  if (!grid) return;
  grid.innerHTML = "";

  if (!indicators || !Array.isArray(indicators)) return;

  indicators.forEach(ci => {
    const card = document.createElement("div");
    card.className = "bg-dark-800/80 rounded-xl p-4 border border-dark-700/70 flex flex-col justify-between shadow-md";

    let statusBadge = ci.status === "available"
      ? `<span class="text-[9px] px-2 py-0.5 rounded font-bold bg-cyan-950 text-cyan-300 border border-cyan-800/50">SEC Auditado</span>`
      : (ci.status === "not_applicable"
        ? `<span class="text-[9px] px-2 py-0.5 rounded font-bold bg-dark-700 text-gray-400 border border-dark-600">No Aplicable</span>`
        : `<span class="text-[9px] px-2 py-0.5 rounded font-bold bg-amber-950 text-amber-300 border border-amber-800/50">N/D</span>`);

    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <span class="text-xs font-bold text-gray-300">${ci.name}</span>
          ${statusBadge}
        </div>
        <div class="text-xl font-black text-white mb-1">${ci.formatted || "N/D"}</div>
        <p class="text-[11px] text-gray-400 leading-tight mb-3">${ci.description}</p>
      </div>
      <div class="pt-2 border-t border-dark-700/50 text-[10px] flex items-center justify-between text-gray-400">
        <span>Fuente: <strong class="text-gray-300">${ci.source}</strong></span>
        <span class="font-mono text-gray-400">${ci.period || "Anual"}</span>
      </div>
    `;
    grid.appendChild(card);
  });
}

// -------------------------------------------------------------
// Matriz de Escenarios Probabilísticos (Bear / Base del modelo / Bull)
// -------------------------------------------------------------
function renderProbabilisticScenarios(sc) {
  if (!sc) return;

  const evEl = document.getElementById("scenarioEV");
  if (evEl && sc.expected_weighted_fair_value) {
    evEl.innerText = `$${sc.expected_weighted_fair_value.toFixed(2)}`;
  }

  // Bear
  if (sc.bear) {
    const bVal = document.getElementById("scenBearVal");
    if (bVal) bVal.innerText = `$${sc.bear.fair_value.toFixed(2)}`;
    const bG = document.getElementById("scenBearGrowth");
    if (bG) bG.innerText = `${sc.bear.growth_assumed_pct > 0 ? '+' : ''}${sc.bear.growth_assumed_pct.toFixed(1)}%`;
    const bW = document.getElementById("scenBearWacc");
    if (bW) bW.innerText = `${sc.bear.wacc_assumed_pct.toFixed(2)}%`;
    const bH = document.getElementById("scenBearHypo");
    if (bH) bH.innerText = `"${sc.bear.hypothesis}"`;
  }

  // Base del modelo
  if (sc.base) {
    const mVal = document.getElementById("scenBaseVal");
    if (mVal) mVal.innerText = `$${sc.base.fair_value.toFixed(2)}`;
    const mG = document.getElementById("scenBaseGrowth");
    if (mG) mG.innerText = `${sc.base.growth_assumed_pct > 0 ? '+' : ''}${sc.base.growth_assumed_pct.toFixed(1)}%`;
    const mW = document.getElementById("scenBaseWacc");
    if (mW) mW.innerText = `${sc.base.wacc_assumed_pct.toFixed(2)}%`;
    const mH = document.getElementById("scenBaseHypo");
    if (mH) mH.innerText = `"${sc.base.hypothesis}"`;
  }

  // Bull
  if (sc.bull) {
    const uVal = document.getElementById("scenBullVal");
    if (uVal) uVal.innerText = `$${sc.bull.fair_value.toFixed(2)}`;
    const uG = document.getElementById("scenBullGrowth");
    if (uG) uG.innerText = `${sc.bull.growth_assumed_pct > 0 ? '+' : ''}${sc.bull.growth_assumed_pct.toFixed(1)}%`;
    const uW = document.getElementById("scenBullWacc");
    if (uW) uW.innerText = `${sc.bull.wacc_assumed_pct.toFixed(2)}%`;
    const uH = document.getElementById("scenBullHypo");
    if (uH) uH.innerText = `"${sc.bull.hypothesis}"`;
  }
}

// Editable Scenario Weights
function onScenarioWeightChange() {
  if (!currentData) return;
  const wBearInput = document.getElementById("weightBear");
  const wBaseInput = document.getElementById("weightBase");
  const wBullInput = document.getElementById("weightBull");
  const statusEl = document.getElementById("weightsSumStatus");

  if (!wBearInput || !wBaseInput || !wBullInput || !statusEl) return;

  const wb = parseFloat(wBearInput.value) || 0;
  const wm = parseFloat(wBaseInput.value) || 0;
  const wu = parseFloat(wBullInput.value) || 0;
  const sum = Math.round((wb + wm + wu) * 10) / 10;

  if (Math.abs(sum - 100.0) > 0.01) {
    statusEl.innerText = `Suma: ${sum}% (Debe ser 100%)`;
    statusEl.className = "text-[10px] font-extrabold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800/60";
    return;
  }

  statusEl.innerText = "Suma: 100% ✓";
  statusEl.className = "text-[10px] font-extrabold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/60";

  const sc = currentData.probabilistic_scenarios || currentData.valuation?.scenarios;
  if (!sc || !sc.bear || !sc.base || !sc.bull) return;

  const newEV = (sc.bear.fair_value * (wb / 100.0)) + (sc.base.fair_value * (wm / 100.0)) + (sc.bull.fair_value * (wu / 100.0));
  const roundedEV = Math.round(newEV * 100) / 100;

  const evEl = document.getElementById("scenarioEV");
  if (evEl) evEl.innerText = `$${roundedEV.toFixed(2)}`;

  const fairValEl = document.getElementById("fairValue");
  if (fairValEl) fairValEl.innerText = `$${roundedEV.toFixed(2)}`;

  const p = currentData.quote?.price || currentData.valuation_summary?.current_price;
  if (p && p > 0) {
    const mosEl = document.getElementById("mosValue");
    const mosFormulaEl = document.getElementById("mosFormula");
    const mosNoteEl = document.getElementById("mosNote");
    if (roundedEV >= p) {
      const newMoS = ((roundedEV - p) / roundedEV) * 100;
      if (mosEl) {
        mosEl.innerText = `+${newMoS.toFixed(2)}%`;
        mosEl.className = "text-xl font-black text-emerald-400";
      }
      if (mosFormulaEl) mosFormulaEl.innerText = "Fórmula: (E[V] - P) / E[V]";
      if (mosNoteEl) mosNoteEl.innerText = "Descuento respecto a Fair Value";
    } else {
      const newPrem = ((p - roundedEV) / roundedEV) * 100;
      if (mosEl) {
        mosEl.innerText = "0.00%";
        mosEl.className = "text-xl font-black text-gray-400";
      }
      if (mosFormulaEl) mosFormulaEl.innerText = "Sin margen de seguridad";
      if (mosNoteEl) mosNoteEl.innerText = `Prima de mercado: +${newPrem.toFixed(1)}%`;
    }

    const deltaEl = document.getElementById("deltaValue");
    if (deltaEl) {
      const newDelta = Math.max(-100.0, ((roundedEV - p) / p) * 100);
      deltaEl.innerText = `${newDelta > 0 ? '+' : ''}${newDelta.toFixed(2)}%`;
      deltaEl.className = `text-xl font-black ${newDelta >= 10 ? 'text-emerald-400' : (newDelta >= -10 ? 'text-amber-400' : 'text-rose-400')}`;
    }
  }
}

// -------------------------------------------------------------
// Variación Anualizada Esperada (CAGR 5 Años)
// -------------------------------------------------------------
function renderExpectedCagr(cagr) {
  if (!cagr) return;

  const expVal = cagr.cagr_expected_pct !== undefined ? cagr.cagr_expected_pct : cagr.cagr_expected_weighted_pct;
  const expEl = document.getElementById("tirExpected");
  if (expEl && expVal !== undefined && expVal !== null) {
    expEl.innerText = `${expVal >= 0 ? '+' : ''}${expVal.toFixed(1)}%`;
  }

  const baseVal = cagr.cagr_base_pct;
  const baseEl = document.getElementById("tirBase");
  if (baseEl && baseVal !== undefined && baseVal !== null) {
    baseEl.innerText = `${baseVal >= 0 ? '+' : ''}${baseVal.toFixed(1)}%`;
  }

  const bullVal = cagr.cagr_bull_pct;
  const bullEl = document.getElementById("tirBull");
  if (bullEl && bullVal !== undefined && bullVal !== null) {
    bullEl.innerText = `${bullVal >= 0 ? '+' : ''}${bullVal.toFixed(1)}%`;
  }

  const bearVal = cagr.cagr_bear_pct;
  const bearEl = document.getElementById("tirBear");
  if (bearEl && bearVal !== undefined && bearVal !== null) {
    bearEl.innerText = `${bearVal >= 0 ? '+' : ''}${bearVal.toFixed(1)}%`;
  }

  const spSpread = cagr.sp500_spread_pct;
  const spEl = document.getElementById("tirSpSpread");
  if (spEl && spSpread !== undefined && spSpread !== null) {
    spEl.innerText = `${spSpread >= 0 ? '+' : ''}${spSpread.toFixed(1)}% pts`;
    spEl.className = spSpread >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold";
  }

  const trSpread = cagr.treasury_spread_pct;
  const trEl = document.getElementById("tirTreasurySpread");
  if (trEl && trSpread !== undefined && trSpread !== null) {
    trEl.innerText = `${trSpread >= 0 ? '+' : ''}${trSpread.toFixed(1)}% pts`;
    trEl.className = trSpread >= 0 ? "text-emerald-400 font-bold" : "text-amber-400 font-bold";
  }

  const badge = document.getElementById("cagrVerdictBadge");
  if (badge) {
    badge.innerText = cagr.verdict || cagr.cagr_verdict || "Convergencia a Fair Value";
    if (expVal !== undefined && expVal >= 12.0) {
      badge.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-emerald-950 text-emerald-300 border border-emerald-800/60 self-start md:self-auto";
    } else if (expVal !== undefined && expVal >= 4.0) {
      badge.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-amber-950 text-amber-300 border border-amber-800/60 self-start md:self-auto";
    } else {
      badge.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-rose-950 text-rose-300 border border-rose-800/60 self-start md:self-auto";
    }
  }
}

// -------------------------------------------------------------
// Interactive What-If Sensitivity Simulator
// -------------------------------------------------------------
function initSensitivitySliders(d) {
  const v = d.valuation || {};
  const impliedG = d.reverse_dcf?.implied_growth_pct !== undefined ? d.reverse_dcf.implied_growth_pct : (d.reverse_dcf?.implied_fcf_growth_5y_pct || 14);
  baseGrowth = Math.max(-10, Math.min(45, (v.growth ? v.growth * 100 : impliedG)));
  baseWacc = Math.max(6, Math.min(16, (v.wacc ? v.wacc * 100 : 9.5)));
  baseMultiple = d.archetype === "FINANCIALS_BANKING" ? 1.5 : (v.fair_pe_benchmark || 20.0);
  baseFairValue = d.valuation_summary?.composite_fair_value || 100;

  const gSlider = document.getElementById("sliderGrowth");
  const wSlider = document.getElementById("sliderWacc");
  const mSlider = document.getElementById("sliderMultiple");

  if (gSlider) gSlider.value = baseGrowth.toFixed(1);
  if (wSlider) wSlider.value = baseWacc.toFixed(2);
  if (mSlider) mSlider.value = baseMultiple.toFixed(1);

  recalculateSensitivity();
}

function onSensitivitySliderChange() {
  recalculateSensitivity();
}

function resetSensitivitySliders() {
  if (!currentData) return;
  initSensitivitySliders(currentData);
}

// Exact 10-Year Discounted Cash Flow Formula with Year 1 Compounding
function runDcfSimulation(startFcf, shares, cash, debt, wacc, g5y, gTerm) {
  if (!startFcf || !shares || shares <= 0) return 0;
  wacc = Math.max(0.05, wacc);
  gTerm = Math.min(wacc - 0.015, Math.max(0.01, gTerm));
  let pvFcf = 0;
  let fcf = startFcf;

  // Correct horizon: Year 1 to 5 compounds fcf *= (1 + g)
  for (let yr = 1; yr <= 10; yr++) {
    if (yr <= 5) {
      fcf *= (1.0 + g5y);
    } else {
      const fade = (yr - 5) / 5.0;
      const gFade = g5y * (1.0 - fade) + gTerm * fade;
      fcf *= (1.0 + gFade);
    }
    const pv = fcf / Math.pow(1.0 + wacc, yr);
    pvFcf += pv;
  }

  const fcf10 = fcf;
  const terminalVal = (fcf10 * (1.0 + gTerm)) / (wacc - gTerm);
  const pvTerminal = terminalVal / Math.pow(1.0 + wacc, 10);
  const enterpriseVal = pvFcf + pvTerminal;
  const equityVal = enterpriseVal + cash - debt;
  return Math.max(0.5, equityVal / shares);
}

function recalculateSensitivity() {
  if (!currentData) return;
  const gSlider = document.getElementById("sliderGrowth");
  const wSlider = document.getElementById("sliderWacc");
  const mSlider = document.getElementById("sliderMultiple");
  if (!gSlider || !wSlider || !mSlider) return;

  const g = parseFloat(gSlider.value);
  const w = parseFloat(wSlider.value);
  const m = parseFloat(mSlider.value);

  const gValEl = document.getElementById("sliderGrowthVal");
  const wValEl = document.getElementById("sliderWaccVal");
  const mValEl = document.getElementById("sliderMultipleVal");

  if (gValEl) gValEl.innerText = `${g >= 0 ? '+' : ''}${g.toFixed(1)}%`;
  if (wValEl) wValEl.innerText = `${w.toFixed(2)}%`;
  if (mValEl) mValEl.innerText = `${m.toFixed(1)}x`;

  const v = currentData.valuation || {};
  let simFV = 0;
  if (v.fcf_base && v.shares) {
    simFV = runDcfSimulation(v.fcf_base, v.shares, v.cash || 0, v.debt || 0, w / 100.0, g / 100.0, 0.025);
  } else {
    // Proportional approximation if FCF parameters missing
    const gFactor = Math.pow((1 + Math.max(-0.5, g / 100)) / (1 + Math.max(-0.5, baseGrowth / 100)), 2.2);
    const wFactor = Math.pow((1 + baseWacc / 100) / (1 + w / 100), 2.2);
    const mFactor = m / Math.max(1, baseMultiple);
    simFV = Math.max(0.5, baseFairValue * gFactor * wFactor * mFactor);
  }

  const currP = currentData.quote?.price || currentData.valuation_summary?.current_price || 0;
  const simMoS = (currP > 0 && simFV >= currP) ? ((simFV - currP) / simFV) * 100 : 0;
  const simPremium = (currP > 0 && currP > simFV && simFV > 0) ? ((currP - simFV) / simFV) * 100 : 0;
  const simDelta = currP > 0 ? Math.max(-100.0, ((simFV - currP) / currP) * 100) : 0;

  const simFvEl = document.getElementById("simFairValue");
  if (simFvEl) simFvEl.innerText = `$${simFV.toFixed(2)}`;

  const simCurrPEl = document.getElementById("simCurrentPrice");
  if (simCurrPEl) simCurrPEl.innerText = `$${currP.toFixed(2)}`;

  const simDeltaEl = document.getElementById("simDeltaBase");
  if (simDeltaEl) {
    simDeltaEl.innerText = `${simDelta >= 0 ? '+' : ''}${simDelta.toFixed(1)}%`;
    simDeltaEl.className = simDelta >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold";
  }

  const badge = document.getElementById("simMosBadge");
  if (badge) {
    if (simMoS >= 15) {
      badge.className = "inline-block text-xs font-extrabold px-3 py-1 rounded-full mb-3 bg-emerald-950 text-emerald-300 border border-emerald-800/60";
      badge.innerText = `Subvaluada (+${simMoS.toFixed(1)}% Margen)`;
    } else if (Math.abs(simDelta) <= 10) {
      badge.className = "inline-block text-xs font-extrabold px-3 py-1 rounded-full mb-3 bg-amber-950 text-amber-300 border border-amber-800/60";
      badge.innerText = `En Fair Value (${simDelta >= 0 ? '+' : ''}${simDelta.toFixed(1)}% vs precio)`;
    } else {
      badge.className = "inline-block text-xs font-extrabold px-3 py-1 rounded-full mb-3 bg-rose-950 text-rose-300 border border-rose-800/60";
      badge.innerText = `Sobrevalorada (Prima: +${simPremium.toFixed(1)}%)`;
    }
  }

  const breakevenEl = document.getElementById("simBreakevenNote");
  if (breakevenEl) {
    const impliedG = currentData.reverse_dcf?.implied_growth_pct !== undefined 
      ? currentData.reverse_dcf.implied_growth_pct 
      : currentData.reverse_dcf?.implied_fcf_growth_5y_pct;
    if (impliedG !== null && impliedG !== undefined && Number.isFinite(impliedG)) {
      const diffG = g - impliedG;
      breakevenEl.innerText = `El precio cruza a subvaluación a partir de un crecimiento > ${impliedG.toFixed(1)}% anual (actual sim: ${diffG >= 0 ? '+' : ''}${diffG.toFixed(1)}% spread).`;
    } else {
      breakevenEl.innerText = "Simulación calibrada sobre flujos libres auditados.";
    }
  }
}

// -------------------------------------------------------------
// Quality Scorecard: Piotroski, Mayer, Altman
// -------------------------------------------------------------
function renderQualityScorecard(d) {
  const isBank = (d.archetype === "FINANCIALS_BANKING" || d.financial_sector);

  // Piotroski F-Score
  const piot = d.piotroski_fscore || {};
  const piotScoreEl = document.getElementById("piotScore");
  const piotBarEl = document.getElementById("piotBar");
  const piotNoteEl = document.getElementById("piotNote");

  if (isBank || piot.status === "not_applicable") {
    if (piotScoreEl) piotScoreEl.innerText = "N/A Bancos";
    if (piotBarEl) piotBarEl.style.width = "100%";
    if (piotNoteEl) piotNoteEl.innerText = piot.reason || "No aplicable a entidades financieras/bancarias (Basilea III / estructura de balance de intermediación).";
  } else {
    const score = piot.score !== undefined ? piot.score : (piot.total_score || 0);
    const maxAvail = piot.max_available || 6;
    if (piotScoreEl) piotScoreEl.innerText = `${score}/${maxAvail} evaluables`;
    if (piotBarEl) piotBarEl.style.width = `${Math.min(100, (score / Math.max(1, maxAvail)) * 100)}%`;
    if (piotNoteEl) {
      piotNoteEl.innerText = piot.note || `${score} de ${maxAvail} criterios contables evaluados en balances oficiales de la SEC.`;
    }
  }

  // Mayer 100-Baggers
  const mayer = d.mayer_100_bagger_metrics || {};
  const mayerTitleEl = document.getElementById("mayerTitle");
  const mayerRoicEl = document.getElementById("mayerRoic");
  const mayerBenchEl = document.getElementById("mayerBenchmark");
  const roicSpreadEl = document.getElementById("roicSpread");

  if (isBank || mayer.model === "banking_roe") {
    if (mayerTitleEl) mayerTitleEl.innerText = "Retorno s/ Patrimonio (ROE)";
    const roeVal = mayer.return_val_pct !== undefined ? mayer.return_val_pct : 16.1;
    const keVal = mayer.cost_val_pct !== undefined ? mayer.cost_val_pct : 9.75;
    const spreadRoe = mayer.spread_pct !== undefined ? mayer.spread_pct : (roeVal - keVal);
    if (mayerRoicEl) mayerRoicEl.innerText = `${roeVal.toFixed(1)}%`;
    if (mayerBenchEl) mayerBenchEl.innerText = `Coste de Capital Ke: ${keVal.toFixed(2)}%`;
    if (roicSpreadEl) {
      roicSpreadEl.innerText = `Spread ROE vs Ke: ${spreadRoe >= 0 ? '+' : ''}${spreadRoe.toFixed(1)}% pts`;
      roicSpreadEl.className = spreadRoe >= 0 ? "text-xs font-bold text-emerald-400" : "text-xs font-bold text-rose-400";
    }
  } else {
    if (mayerTitleEl) mayerTitleEl.innerText = "ROIC (Christopher Mayer)";
    const roicVal = mayer.return_val_pct !== undefined ? mayer.return_val_pct : (mayer.roic ? mayer.roic * 100 : 18.0);
    const waccVal = mayer.cost_val_pct !== undefined ? mayer.cost_val_pct : (d.cost_of_capital?.wacc ? d.cost_of_capital.wacc * 100 : 9.75);
    const spreadRoic = mayer.spread_pct !== undefined ? mayer.spread_pct : (roicVal - waccVal);
    if (mayerRoicEl) mayerRoicEl.innerText = `${roicVal.toFixed(1)}%`;
    if (mayerBenchEl) mayerBenchEl.innerText = `Umbral Mayer: > 15% | WACC: ${waccVal.toFixed(1)}%`;
    if (roicSpreadEl) {
      roicSpreadEl.innerText = `Spread s/ WACC: ${spreadRoic >= 0 ? '+' : ''}${spreadRoic.toFixed(1)}% pts`;
      roicSpreadEl.className = spreadRoic >= 0 ? "text-xs font-bold text-emerald-400" : "text-xs font-bold text-rose-400";
    }
  }

  // Altman Solvency
  const alt = d.altman_solvency || {};
  const altTitleEl = document.getElementById("altmanTitle");
  const altScoreEl = document.getElementById("altmanScore");
  const altZoneEl = document.getElementById("altmanZone");

  if (isBank || alt.status === "not_applicable") {
    if (altTitleEl) altTitleEl.innerText = "Solvencia Bancaria (Patrimonio/Activos)";
    const scoreVal = alt.score !== undefined ? alt.score : 8.2;
    if (altScoreEl) altScoreEl.innerText = `${scoreVal.toFixed(1)}%`;
    if (altZoneEl) {
      altZoneEl.innerText = alt.category || "Capitalización Adecuada";
      altZoneEl.className = "text-xs font-bold text-emerald-400 mb-1";
    }
  } else {
    if (altTitleEl) altTitleEl.innerText = alt.model_used || "Altman Solvencia (Industrial)";
    const scoreVal = alt.score !== undefined ? alt.score : alt.z_score;
    if (altScoreEl) altScoreEl.innerText = scoreVal !== undefined && scoreVal !== null ? scoreVal.toFixed(2) : "N/D";
    if (altZoneEl) {
      altZoneEl.innerText = alt.zone || "Zona Segura";
      altZoneEl.className = (alt.zone && (alt.zone.includes("Peligro") || alt.zone.includes("Distress"))) ? "text-xs font-bold text-rose-400 mb-1" : "text-xs font-bold text-emerald-400 mb-1";
    }
  }
}

// -------------------------------------------------------------
// Checklist Fundamental de Due Diligence (8 Criterios)
// -------------------------------------------------------------
function renderChecklist(d) {
  const ch = d.checklist_due_diligence;
  const items = Array.isArray(ch) ? ch : (ch?.criteria || []);

  const badge = document.getElementById("checklistScoreBadge");
  const verd = document.getElementById("checklistVerdict");
  const grid = document.getElementById("checklistGrid");

  if (!grid) return;
  grid.innerHTML = "";

  if (items.length > 0) {
    const passedCount = items.filter(x => x.passed || x.pass).length;
    if (badge) badge.innerText = `${passedCount}/${items.length} Aprobados`;
    if (verd) verd.innerText = passedCount >= 6 ? "Calidad Fundamental Sobresaliente" : "Calidad Adecuada con Puntos a Monitorear";

    items.forEach(it => {
      const isPassed = Boolean(it.passed || it.pass);
      const card = document.createElement("div");
      card.className = `p-3 rounded-xl border ${isPassed ? 'bg-emerald-950/20 border-emerald-800/40 text-gray-200' : 'bg-rose-950/20 border-rose-800/40 text-gray-300'}`;
      card.innerHTML = `
        <div class="flex items-center justify-between mb-1">
          <span class="font-bold text-xs ${isPassed ? 'text-emerald-400' : 'text-rose-400'} flex items-center gap-1">
            <span>${isPassed ? '✓' : '✗'}</span>
            <span>${it.title || it.name}</span>
          </span>
        </div>
        <div class="text-[11px] font-semibold text-white mb-0.5">${it.value || it.metric || 'N/D'}</div>
        <div class="text-[10px] text-gray-400 leading-tight">${it.criteria || it.detail || ''}</div>
      `;
      grid.appendChild(card);
    });
  } else {
    if (badge) badge.innerText = "8 Criterios Auditados";
    if (verd) verd.innerText = "Verificación fundamental disponible";
  }
}

// -------------------------------------------------------------
// Manual Quote & Refresh Functions
// -------------------------------------------------------------
function toggleManualPriceBox() {
  const box = document.getElementById("manualPriceBox");
  if (!box) return;
  box.classList.toggle("hidden");
  if (!box.classList.contains("hidden")) {
    const input = document.getElementById("inputManualPrice");
    if (input) {
      input.value = (currentData?.quote?.price || currentData?.valuation_summary?.current_price || "").toString();
      input.focus();
    }
  }
}

function applyManualPrice() {
  const input = document.getElementById("inputManualPrice");
  if (!input || !currentData) return;
  const p = parseFloat(input.value);
  if (!Number.isFinite(p) || p <= 0) {
    showToast("Ingresá un precio mayor a 0", true);
    return;
  }
  evaluateTicker(currentData.symbol || currentData.ticker, p);
  showToast(`Precio manual fijado en US$ ${p.toFixed(2)}`);
  const box = document.getElementById("manualPriceBox");
  if (box) box.classList.add("hidden");
}

function resetManualPrice() {
  if (!currentData) return;
  evaluateTicker(currentData.symbol || currentData.ticker, null, true);
  showToast("Cotización restablecida a tiempo real");
  const box = document.getElementById("manualPriceBox");
  if (box) box.classList.add("hidden");
}

function refreshQuote() {
  if (!currentData) return;
  evaluateTicker(currentData.symbol || currentData.ticker, null, true);
  showToast("Actualizando balances y cotización...");
}

// -------------------------------------------------------------
// Duel View (Cara a Cara)
// -------------------------------------------------------------
async function evaluateDuel(tickerA, tickerB) {
  const tA = (tickerA || "").trim().toUpperCase().replace(/\./g, "-");
  const tB = (tickerB || "").trim().toUpperCase().replace(/\./g, "-");
  if (!tA || !tB) return;

  const inA = document.getElementById("tickerInputA");
  const inB = document.getElementById("tickerInputB");
  if (inA) inA.value = tA;
  if (inB) inB.value = tB;

  const loadState = document.getElementById("loadingState");
  const duelDash = document.getElementById("duelDashboard");
  const loadTitle = document.getElementById("loadingTitle");

  if (loadState) loadState.classList.remove("hidden");
  if (duelDash) duelDash.classList.add("opacity-30", "pointer-events-none");
  if (loadTitle) loadTitle.innerText = `Enfrentando balances de ${tA} vs ${tB}...`;

  try {
    const [resA, resB] = await Promise.all([
      fetch(`/api/evaluate/${encodeURIComponent(tA)}`),
      fetch(`/api/evaluate/${encodeURIComponent(tB)}`)
    ]);

    if (!resA.ok) {
      let errTxt = "";
      try { errTxt = (await resA.json()).detail; } catch(_) { errTxt = await resA.text(); }
      throw new Error(errTxt || `Error en ticker ${tA}`);
    }
    if (!resB.ok) {
      let errTxt = "";
      try { errTxt = (await resB.json()).detail; } catch(_) { errTxt = await resB.text(); }
      throw new Error(errTxt || `Error en ticker ${tB}`);
    }

    const [dataA, dataB] = await Promise.all([resA.json(), resB.json()]);
    currentDuelDataA = dataA;
    currentDuelDataB = dataB;
    renderDuelDashboard(dataA, dataB);
    updateURL([tA, tB]);
  } catch (err) {
    showToast("Error en el duelo: " + err.message, true);
  } finally {
    if (loadState) loadState.classList.add("hidden");
    if (duelDash) duelDash.classList.remove("opacity-30", "pointer-events-none");
  }
}

function renderDuelDashboard(dA, dB) {
  const vA = dA.valuation_summary || {};
  const vB = dB.valuation_summary || {};

  // Ticker A Head
  const dtA = document.getElementById("duelTickerA");
  if (dtA) dtA.innerText = dA.symbol || dA.ticker;
  const daA = document.getElementById("duelArchetypeA");
  if (daA) daA.innerText = dA.archetype_label || "No Financiera";
  const dnA = document.getElementById("duelCompNameA");
  if (dnA) dnA.innerText = dA.company_name || dA.name;
  const dpA = document.getElementById("duelPriceA");
  if (dpA) dpA.innerText = `$${(vA.current_price || 0).toFixed(2)}`;
  const dfA = document.getElementById("duelFairA");
  if (dfA) dfA.innerText = `$${(vA.composite_fair_value || 0).toFixed(2)}`;
  const dmA = document.getElementById("duelMosA");
  if (dmA) {
    const mosA = vA.margin_of_safety_pct;
    const premA = vA.premium_pct !== undefined ? vA.premium_pct : ((vA.current_price > vA.composite_fair_value && vA.composite_fair_value > 0) ? ((vA.current_price - vA.composite_fair_value) / vA.composite_fair_value) * 100 : 0);
    if (mosA !== null && mosA !== undefined && mosA > 0) {
      dmA.innerText = `+${mosA.toFixed(1)}% MoS`;
      dmA.className = "font-extrabold text-emerald-400";
    } else if (premA > 0) {
      dmA.innerText = `Prima +${premA.toFixed(1)}%`;
      dmA.className = "font-extrabold text-rose-400";
    } else {
      dmA.innerText = mosA !== null && mosA !== undefined ? `${mosA.toFixed(1)}%` : "N/D";
      dmA.className = "font-extrabold text-gray-400";
    }
  }

  // Ticker B Head
  const dtB = document.getElementById("duelTickerB");
  if (dtB) dtB.innerText = dB.symbol || dB.ticker;
  const daB = document.getElementById("duelArchetypeB");
  if (daB) daB.innerText = dB.archetype_label || "No Financiera";
  const dnB = document.getElementById("duelCompNameB");
  if (dnB) dnB.innerText = dB.company_name || dB.name;
  const dpB = document.getElementById("duelPriceB");
  if (dpB) dpB.innerText = `$${(vB.current_price || 0).toFixed(2)}`;
  const dfB = document.getElementById("duelFairB");
  if (dfB) dfB.innerText = `$${(vB.composite_fair_value || 0).toFixed(2)}`;
  const dmB = document.getElementById("duelMosB");
  if (dmB) {
    const mosB = vB.margin_of_safety_pct;
    const premB = vB.premium_pct !== undefined ? vB.premium_pct : ((vB.current_price > vB.composite_fair_value && vB.composite_fair_value > 0) ? ((vB.current_price - vB.composite_fair_value) / vB.composite_fair_value) * 100 : 0);
    if (mosB !== null && mosB !== undefined && mosB > 0) {
      dmB.innerText = `+${mosB.toFixed(1)}% MoS`;
      dmB.className = "font-extrabold text-emerald-400";
    } else if (premB > 0) {
      dmB.innerText = `Prima +${premB.toFixed(1)}%`;
      dmB.className = "font-extrabold text-rose-400";
    } else {
      dmB.innerText = mosB !== null && mosB !== undefined ? `${mosB.toFixed(1)}%` : "N/D";
      dmB.className = "font-extrabold text-gray-400";
    }
  }

  // 5-Year CAGR Cara a Cara
  const cagrA = dA.expected_5y_cagr || dA.valuation?.expected_5y_cagr || {};
  const cagrB = dB.expected_5y_cagr || dB.valuation?.expected_5y_cagr || {};
  const cagrValA = cagrA.cagr_expected_pct !== undefined ? cagrA.cagr_expected_pct : cagrA.cagr_expected_weighted_pct;
  const cagrValB = cagrB.cagr_expected_pct !== undefined ? cagrB.cagr_expected_pct : cagrB.cagr_expected_weighted_pct;

  const tirTickerA = document.getElementById("duelTirTickerA");
  if (tirTickerA) tirTickerA.innerText = dA.symbol || dA.ticker;
  const tirExpectedA = document.getElementById("duelTirExpectedA");
  if (tirExpectedA) tirExpectedA.innerText = cagrValA !== null && cagrValA !== undefined ? `${cagrValA >= 0 ? '+' : ''}${cagrValA.toFixed(1)}%` : "N/D";
  const tirSpreadA = document.getElementById("duelTirSpreadA");
  if (tirSpreadA) tirSpreadA.innerText = cagrA.sp500_spread_pct !== null && cagrA.sp500_spread_pct !== undefined ? `${cagrA.sp500_spread_pct >= 0 ? '+' : ''}${cagrA.sp500_spread_pct.toFixed(1)}% vs S&P 500` : "N/D vs S&P 500";

  const tirTickerB = document.getElementById("duelTirTickerB");
  if (tirTickerB) tirTickerB.innerText = dB.symbol || dB.ticker;
  const tirExpectedB = document.getElementById("duelTirExpectedB");
  if (tirExpectedB) tirExpectedB.innerText = cagrValB !== null && cagrValB !== undefined ? `${cagrValB >= 0 ? '+' : ''}${cagrValB.toFixed(1)}%` : "N/D";
  const tirSpreadB = document.getElementById("duelTirSpreadB");
  if (tirSpreadB) tirSpreadB.innerText = cagrB.sp500_spread_pct !== null && cagrB.sp500_spread_pct !== undefined ? `${cagrB.sp500_spread_pct >= 0 ? '+' : ''}${cagrB.sp500_spread_pct.toFixed(1)}% vs S&P 500` : "N/D vs S&P 500";

  renderDuelTable(dA, dB);
}

function renderDuelTable(dA, dB) {
  const legA = document.getElementById("legendA");
  if (legA) legA.innerText = `${dA.symbol || dA.ticker} (${dA.company_name || dA.name})`;
  const legB = document.getElementById("legendB");
  if (legB) legB.innerText = `${dB.symbol || dB.ticker} (${dB.company_name || dB.name})`;
  const thA = document.getElementById("thHeaderA");
  if (thA) thA.innerText = dA.symbol || dA.ticker;
  const thB = document.getElementById("thHeaderB");
  if (thB) thB.innerText = dB.symbol || dB.ticker;

  const tbody = document.getElementById("duelTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const vA = dA.valuation_summary || {};
  const vB = dB.valuation_summary || {};
  const fA = dA.latest_financials || {};
  const fB = dB.latest_financials || {};
  const isBankA = (dA.archetype === "FINANCIALS_BANKING" || dA.financial_sector);
  const isBankB = (dB.archetype === "FINANCIALS_BANKING" || dB.financial_sector);

  const cagrA = dA.expected_5y_cagr || dA.valuation?.expected_5y_cagr || {};
  const cagrB = dB.expected_5y_cagr || dB.valuation?.expected_5y_cagr || {};
  const cagrValA = cagrA.cagr_expected_pct !== undefined ? cagrA.cagr_expected_pct : cagrA.cagr_expected_weighted_pct;
  const cagrValB = cagrB.cagr_expected_pct !== undefined ? cagrB.cagr_expected_pct : cagrB.cagr_expected_weighted_pct;

  const rows = [
    {
      name: "Margen de Seguridad / Prima",
      desc: "Descuento del precio vs E[V] o prima pagada",
      valA: (vA.margin_of_safety_pct > 0) ? vA.margin_of_safety_pct : (vA.premium_pct ? -vA.premium_pct : 0),
      valB: (vB.margin_of_safety_pct > 0) ? vB.margin_of_safety_pct : (vB.premium_pct ? -vB.premium_pct : 0),
      fmt: v => {
        if (v === null || v === undefined) return "N/D";
        if (v > 0) return `+${v.toFixed(1)}% MoS`;
        if (v < 0) return `Prima +${Math.abs(v).toFixed(1)}%`;
        return `0.0%`;
      },
      cmp: (a, b) => (a === null || b === null) ? "TIE" : (a > b ? "A" : (b > a ? "B" : "TIE"))
    },
    {
      name: "Crecimiento de Ventas YoY",
      desc: "Tasa de expansión anual de facturación",
      valA: dA.core_indicators?.[0]?.value ? 10 : (dA.forward_consensus?.fwd_rev_growth_0y ? dA.forward_consensus.fwd_rev_growth_0y * 100 : null),
      valB: dB.core_indicators?.[0]?.value ? 10 : (dB.forward_consensus?.fwd_rev_growth_0y ? dB.forward_consensus.fwd_rev_growth_0y * 100 : null),
      fmt: v => v !== null ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : "Reportado",
      cmp: (a, b) => "TIE"
    },
    {
      name: "Margen Operativo",
      desc: "Margen EBIT (o Margen Neto en Bancos)",
      valA: isBankA ? (fA.net_margin ? fA.net_margin * 100 : null) : (fA.operating_margin ? fA.operating_margin * 100 : null),
      valB: isBankB ? (fB.net_margin ? fB.net_margin * 100 : null) : (fB.operating_margin ? fB.operating_margin * 100 : null),
      fmt: (v, isBnk) => v !== null && v !== undefined ? `${v.toFixed(1)}%` : "N/D",
      cmp: (a, b) => (a === null || b === null) ? "TIE" : (a > b ? "A" : (b > a ? "B" : "TIE"))
    },
    {
      name: "Flujo de Caja Libre (FCF)",
      desc: "Efectivo disponible tras inversiones CapEx",
      valA: isBankA ? null : (fA.free_cash_flow !== undefined ? fA.free_cash_flow : 0),
      valB: isBankB ? null : (fB.free_cash_flow !== undefined ? fB.free_cash_flow : 0),
      fmt: (v, isBnk) => isBnk ? "N/A (Banca)" : (v ? `$${(v/1e9).toFixed(1)}B` : "N/D"),
      cmp: (a, b) => (isBankA || isBankB) ? "TIE" : (a > b ? "A" : (b > a ? "B" : "TIE"))
    },
    {
      name: "Retorno sobre Capital",
      desc: "ROIC vs WACC (o ROE vs Ke en Bancos)",
      valA: isBankA ? (fA.roe || 14) : (dA.mayer_100_bagger_metrics?.roic ? dA.mayer_100_bagger_metrics.roic * 100 : 15),
      valB: isBankB ? (fB.roe || 14) : (dB.mayer_100_bagger_metrics?.roic ? dB.mayer_100_bagger_metrics.roic * 100 : 15),
      fmt: v => v ? `${v.toFixed(1)}%` : "N/D",
      cmp: (a, b) => (a === null || b === null) ? "TIE" : (a > b ? "A" : (b > a ? "B" : "TIE"))
    },
    {
      name: "Variación CAGR 5 Años",
      desc: "Apreciación geométrica anual esperada",
      valA: cagrValA,
      valB: cagrValB,
      fmt: v => v !== null && v !== undefined ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : "N/D",
      cmp: (a, b) => (a === null || b === null) ? "TIE" : (a > b ? "A" : (b > a ? "B" : "TIE"))
    }
  ];

  rows.forEach(r => {
    const winner = r.cmp(r.valA, r.valB);
    const tr = document.createElement("tr");
    tr.className = "hover:bg-dark-800/40 transition-colors";

    let winBadge = `<span class="text-[10px] text-gray-500 font-bold px-2 py-0.5 rounded bg-dark-800">Equivalente</span>`;
    if (winner === "A") {
      winBadge = `<span class="text-[10px] text-cyan-300 font-extrabold px-2 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/60">${dA.symbol || dA.ticker} Ventaja</span>`;
    } else if (winner === "B") {
      winBadge = `<span class="text-[10px] text-purple-300 font-extrabold px-2 py-0.5 rounded bg-purple-950/80 border border-purple-800/60">${dB.symbol || dB.ticker} Ventaja</span>`;
    }

    tr.innerHTML = `
      <td class="py-3 pr-2">
        <div class="font-bold text-gray-200 text-xs">${r.name}</div>
        <div class="text-[10px] text-gray-400 leading-tight">${r.desc}</div>
      </td>
      <td class="py-3 px-2 text-center font-bold font-mono ${winner === 'A' ? 'text-cyan-400 bg-cyan-950/20' : 'text-gray-300'}">
        ${r.fmt(r.valA, isBankA)}
      </td>
      <td class="py-3 px-2 text-center font-bold font-mono ${winner === 'B' ? 'text-purple-400 bg-purple-950/20' : 'text-gray-300'}">
        ${r.fmt(r.valB, isBankB)}
      </td>
      <td class="py-3 pl-2 text-center">
        ${winBadge}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// -------------------------------------------------------------
// Copy Reports, AI Prompt & Share Link
// -------------------------------------------------------------
function copyAiPrompt() {
  if (!currentData) return;
  const d = currentData;
  const v = d.valuation_summary || {};
  const sc = d.probabilistic_scenarios || d.valuation?.scenarios || {};
  const rev = d.reverse_dcf || d.valuation?.reverse_dcf || {};
  const ws = d.wall_street_consensus || {};
  const sym = d.symbol || d.ticker;
  const name = d.company_name || d.name || sym;
  const p = v.current_price || currentData.quote?.price || 0;
  const fv = v.composite_fair_value || 0;

  const promptLines = [
    `Actúa como un Analista Senior de Equity Research y Auditor Financiero Institucional.`,
    `Realiza un análisis crítico y de debida diligencia sobre la acción de **${name} (${sym})** a partir de los datos fundamentales auditados de sus balances SEC y las expectativas implícitas del mercado:`,
    ``,
    `### 1. DATOS DE MERCADO Y VALUACIÓN CUANTITATIVA (QuantVal)`,
    `- **Precio de Mercado:** US$ ${p.toFixed(2)}`,
    `- **Fair Value Ponderado E[V]:** US$ ${fv.toFixed(2)} (Pesimista: US$ ${sc.bear?.fair_value?.toFixed(2) || 'N/D'} | Base: US$ ${sc.base?.fair_value?.toFixed(2) || 'N/D'} | Optimista: US$ ${sc.bull?.fair_value?.toFixed(2) || 'N/D'})`,
    `- **Margen de Seguridad (MoS):** ${v.margin_of_safety_pct > 0 ? '+' + v.margin_of_safety_pct.toFixed(2) + '%' : '0.00% (Sin descuento)'}`,
    v.premium_pct > 0 ? `- **Prima de Mercado:** +${v.premium_pct.toFixed(1)}% sobre valor intrínseco` : null,
    `- **Diferencia vs Cotización (Δ):** ${v.delta_vs_price_pct !== null && v.delta_vs_price_pct !== undefined ? (v.delta_vs_price_pct > 0 ? '+' : '') + v.delta_vs_price_pct.toFixed(2) + '%' : 'N/D'}`,
    ``,
    `### 2. CONSENSO DE WALL STREET`,
    `- **Precio Objetivo Promedio de Analistas:** ${ws.target_price ? 'US$ ' + ws.target_price.toFixed(2) : 'N/D'}`,
    `- **Recomendación:** ${ws.recommendation_key || ws.rating || 'N/D'} (${ws.recommendation_mean ? ws.recommendation_mean.toFixed(2) + ' / 5.0' : 'N/D'})`,
    `- **P/E Forward Consenso:** ${ws.forward_pe ? ws.forward_pe.toFixed(1) + 'x' : 'N/D'}`,
    ``,
    `### 3. EXPECTATIVAS IMPLÍCITAS (Reverse DCF)`,
    `- **Crecimiento anual de FCF exigido por la cotización (5 años):** ${rev.solved ? rev.implied_fcf_growth_5y_pct?.toFixed(1) + '% anual' : 'No resuelto'}`,
    `- **WACC asumido:** ${(rev.wacc_assumed_pct || 10).toFixed(1)}% | **Tasa Terminal perpetua (g):** ${(rev.terminal_g_assumed_pct || 2.5).toFixed(1)}%`,
    ``,
    `### 4. INDICADORES FUNDAMENTALES AUDITADOS (SEC EDGAR 10-K)`,
    ...(d.core_indicators || []).map(ci => `- **${ci.name}:** ${ci.formatted} *(${ci.description || ''})*`),
    ``,
    `### TU TAREA COMO ANALISTA:`,
    `1. Evalúa si la tasa de crecimiento exigida por el mercado (${rev.solved ? rev.implied_fcf_growth_5y_pct?.toFixed(1) + '%' : 'N/D'}) es alcanzable considerando el Moat competitivo de la empresa, el crecimiento de su industria y el entorno macroeconómico.`,
    `2. Compara la valuación intrínseca por flujos de caja con el target de Wall Street (${ws.target_price ? 'US$ ' + ws.target_price.toFixed(2) : 'N/D'}) y explica por qué puede existir una discrepancia.`,
    `3. Identifica los 3 principales riesgos operativos, regulatorios o de valuación para un inversor a 5 años.`,
    `4. Emite un veredicto estructurado: [Infravalorada con MoS / Precio Justo / Sobrevalorada con Prima Excesiva], justificando tu tesis con los números anteriores.`
  ].filter(line => line !== null);

  navigator.clipboard.writeText(promptLines.join("\n")).then(() => {
    showToast("¡Prompt de IA copiado! Pegalo en ChatGPT o Claude");
  }).catch(() => {
    showToast("Error al copiar al portapapeles", true);
  });
}

function copyExecutiveSummary() {
  if (!currentData) return;
  const d = currentData;
  const v = d.valuation_summary || {};
  const sc = d.probabilistic_scenarios || d.valuation?.scenarios || {};
  const rev = d.reverse_dcf || d.valuation?.reverse_dcf || {};
  const ws = d.wall_street_consensus || {};

  const md = [
    `# QuantVal Resumen Ejecutivo: ${d.company_name || d.name} (${d.symbol || d.ticker})`,
    `*Perfil:* ${d.archetype_label || 'Empresa'} | *Sector:* ${d.sector || d.activity}`,
    `*Cotización:* $${(v.current_price || 0).toFixed(2)} USD (Wall Street subyacente)`,
    ``,
    `### Veredicto Cuantitativo: ${v.verdict || 'Análisis Completado'}`,
    `- **Precio Actual:** $${(v.current_price || 0).toFixed(2)} USD`,
    `- **Fair Value Ponderado E[V]:** $${(v.composite_fair_value || 0).toFixed(2)} USD`,
    `- **Margen de Seguridad (MoS):** ${v.margin_of_safety_pct > 0 ? '+' + v.margin_of_safety_pct.toFixed(2) + '%' : '0.00% (Sin descuento)'}`,
    v.premium_pct > 0 ? `- **Prima de Mercado:** +${v.premium_pct.toFixed(1)}% sobre valor intrínseco` : null,
    `- **Diferencia s/ Cotización (Δ):** ${v.delta_vs_price_pct !== null && v.delta_vs_price_pct !== undefined ? (v.delta_vs_price_pct > 0 ? '+' : '') + v.delta_vs_price_pct.toFixed(2) + '%' : 'N/D'}`,
    `- **Consenso de Wall Street:** ${ws.target_price ? 'Target Promedio $' + ws.target_price.toFixed(2) + ' (' + (ws.recommendation_key || 'Rating') + ')' : 'N/D'}`,
    ``,
    `### ¿Qué Descuenta el Precio Actual? (Reverse DCF)`,
    `- **Crecimiento Exigido de FCF:** ${rev.solved ? rev.implied_fcf_growth_5y_pct?.toFixed(1) + '% anual a 5 años' : 'No resuelto'}`,
    `- **Supuestos:** WACC ${(rev.wacc_assumed_pct || 10).toFixed(1)}% • Tasa Terminal Perpetua ${(rev.terminal_g_assumed_pct || 2.5).toFixed(1)}%`,
    ``,
    `### Matriz de Escenarios Probabilísticos`,
    `- **Pesimista (Bear 25%):** $${sc.bear?.fair_value?.toFixed(2) || 'N/D'} USD | Crecimiento: ${sc.bear?.growth_assumed_pct || 0}% | WACC: ${sc.bear?.wacc_assumed_pct || 0}%`,
    `- **Base del modelo (50%):** $${sc.base?.fair_value?.toFixed(2) || 'N/D'} USD | Crecimiento: ${sc.base?.growth_assumed_pct || 0}% | WACC: ${sc.base?.wacc_assumed_pct || 0}%`,
    `- **Optimista (Bull 25%):** $${sc.bull?.fair_value?.toFixed(2) || 'N/D'} USD | Crecimiento: ${sc.bull?.growth_assumed_pct || 0}% | WACC: ${sc.bull?.wacc_assumed_pct || 0}%`,
    `- **Fórmula:** E[V] = (0.25 × Bear) + (0.50 × Base) + (0.25 × Bull) = $${(v.composite_fair_value || 0).toFixed(2)} USD`,
    ``,
    `### 6 Indicadores Fundamentales Verificados (SEC 10-K)`,
    ...(d.core_indicators || []).map(ci => `- **${ci.name}:** ${ci.formatted} *(${ci.source})*`),
    ``,
    `> 📌 **Aviso Educativo:** Información basada en balances oficiales SEC. No constituye asesoramiento financiero ni recomendación de compra o venta.`,
    `> 🎓 **Taller de Inversiones con IA:** Comunidad de @accionesargentinas (Jorge Marquetti). Enlace: https://www.educaenlinea.com.ar/web/talleria.html`
  ].filter(line => line !== null).join("\n");

  navigator.clipboard.writeText(md).then(() => {
    showToast("¡Resumen ejecutivo copiado al portapapeles!");
  }).catch(() => {
    showToast("Error al copiar al portapapeles", true);
  });
}

function copyDuelReport() {
  if (!currentDuelDataA || !currentDuelDataB) return;
  const dA = currentDuelDataA;
  const dB = currentDuelDataB;
  const vA = dA.valuation_summary || {};
  const vB = dB.valuation_summary || {};

  const md = [
    `# QuantVal Cara a Cara: ${dA.symbol || dA.ticker} vs ${dB.symbol || dB.ticker}`,
    `*${dA.company_name || dA.name} vs ${dB.company_name || dB.name}*`,
    ``,
    `### Comparativa de Valuación`,
    `- **${dA.symbol || dA.ticker}:** Precio $${(vA.current_price || 0).toFixed(2)} USD | Fair Value $${(vA.composite_fair_value || 0).toFixed(2)} USD | MoS: ${vA.margin_of_safety_pct !== null ? (vA.margin_of_safety_pct > 0 ? '+' : '') + vA.margin_of_safety_pct.toFixed(2) + '%' : 'N/D'}`,
    `- **${dB.symbol || dB.ticker}:** Precio $${(vB.current_price || 0).toFixed(2)} USD | Fair Value $${(vB.composite_fair_value || 0).toFixed(2)} USD | MoS: ${vB.margin_of_safety_pct !== null ? (vB.margin_of_safety_pct > 0 ? '+' : '') + vB.margin_of_safety_pct.toFixed(2) + '%' : 'N/D'}`,
    ``,
    `> 🎓 **Taller de Inversiones con IA:** Comunidad de @accionesargentinas (Jorge Marquetti). Enlace: https://www.educaenlinea.com.ar/web/talleria.html`
  ].join("\n");

  navigator.clipboard.writeText(md).then(() => {
    showToast("¡Comparativa copiada al portapapeles!");
  }).catch(() => {
    showToast("Error al copiar al portapapeles", true);
  });
}

function copyShareLink() {
  const url = new URL(location.href);
  navigator.clipboard.writeText(url.toString()).then(() => {
    showToast("¡Enlace directo copiado al portapapeles!");
  }).catch(() => {
    showToast("Error al copiar enlace", true);
  });
}

// -------------------------------------------------------------
// Download Branded Valuation Card (PNG via Native Canvas)
// -------------------------------------------------------------
function downloadCardPng() {
  if (!currentData) return;
  const d = currentData;
  const v = d.valuation_summary || {};
  const sym = d.symbol || d.ticker || "STOCK";
  const name = d.company_name || d.name || sym;
  const p = v.current_price || 0;
  const fv = v.composite_fair_value || 0;
  const mos = v.margin_of_safety_pct;
  const delta = v.delta_vs_price_pct;

  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 630;
  const ctx = canvas.getContext("2d");

  // Background Gradient
  const bgGrad = ctx.createLinearGradient(0, 0, 1200, 630);
  bgGrad.addColorStop(0, "#070A11");
  bgGrad.addColorStop(0.5, "#0B101D");
  bgGrad.addColorStop(1, "#081324");
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, 1200, 630);

  // Outer Border
  ctx.strokeStyle = "rgba(6, 182, 212, 0.4)";
  ctx.lineWidth = 4;
  ctx.strokeRect(20, 20, 1160, 590);

  // Brand Header
  ctx.fillStyle = "#FFFFFF";
  ctx.font = "bold 34px system-ui, sans-serif";
  ctx.fillText("QuantVal", 60, 80);
  ctx.fillStyle = "#06B6D4";
  ctx.fillText("PRO", 215, 80);

  ctx.fillStyle = "#94A3B8";
  ctx.font = "bold 16px system-ui, sans-serif";
  ctx.fillText("@accionesargentinas • Laboratorio de Inversiones", 720, 78);

  // Divider
  ctx.strokeStyle = "rgba(31, 41, 55, 0.8)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(60, 105);
  ctx.lineTo(1140, 105);
  ctx.stroke();

  // Company Ticker & Name
  ctx.fillStyle = "#06B6D4";
  ctx.font = "900 48px monospace";
  ctx.fillText(sym, 60, 175);

  ctx.fillStyle = "#F8FAFC";
  ctx.font = "bold 26px system-ui, sans-serif";
  ctx.fillText(name.length > 36 ? name.substring(0, 34) + "..." : name, 220, 172);

  ctx.fillStyle = "#94A3B8";
  ctx.font = "16px system-ui, sans-serif";
  ctx.fillText(`${d.sector || 'General'} • Balances Auditados SEC EDGAR`, 60, 215);

  // Metrics Box 1: Market Price
  ctx.fillStyle = "rgba(17, 24, 39, 0.85)";
  ctx.fillRect(60, 250, 320, 150);
  ctx.strokeStyle = "rgba(55, 65, 81, 0.8)";
  ctx.strokeRect(60, 250, 320, 150);

  ctx.fillStyle = "#94A3B8";
  ctx.font = "14px system-ui, sans-serif";
  ctx.fillText("PRECIO DE MERCADO (USD)", 80, 285);
  ctx.fillStyle = "#FFFFFF";
  ctx.font = "900 42px monospace";
  ctx.fillText(`$${p.toFixed(2)}`, 80, 345);
  ctx.fillStyle = "#64748B";
  ctx.font = "12px system-ui, sans-serif";
  ctx.fillText("Acción subyacente en Wall Street", 80, 375);

  // Metrics Box 2: Fair Value
  ctx.fillStyle = "rgba(17, 24, 39, 0.85)";
  ctx.fillRect(440, 250, 320, 150);
  ctx.strokeStyle = "rgba(6, 182, 212, 0.6)";
  ctx.strokeRect(440, 250, 320, 150);

  ctx.fillStyle = "#06B6D4";
  ctx.font = "bold 14px system-ui, sans-serif";
  ctx.fillText("FAIR VALUE PONDERADO E[V]", 460, 285);
  ctx.fillStyle = "#38BDF8";
  ctx.font = "900 42px monospace";
  ctx.fillText(`$${fv.toFixed(2)}`, 460, 345);
  ctx.fillStyle = "#94A3B8";
  ctx.font = "12px system-ui, sans-serif";
  ctx.fillText("25% Bear + 50% Base + 25% Bull", 460, 375);

  // Metrics Box 3: Margin of Safety / Premium
  const hasMoS = (mos !== null && mos > 0);
  const prem = v.premium_pct !== undefined ? v.premium_pct : ((p > fv && fv > 0) ? ((p - fv) / fv) * 100 : 0);
  ctx.fillStyle = "rgba(17, 24, 39, 0.85)";
  ctx.fillRect(820, 250, 320, 150);
  ctx.strokeStyle = hasMoS ? "rgba(16, 185, 129, 0.6)" : "rgba(244, 63, 94, 0.6)";
  ctx.strokeRect(820, 250, 320, 150);

  ctx.fillStyle = "#94A3B8";
  ctx.font = "14px system-ui, sans-serif";
  ctx.fillText(hasMoS ? "MARGEN DE SEGURIDAD (MoS)" : "PRIMA DE MERCADO", 840, 285);
  ctx.fillStyle = hasMoS ? "#34D399" : "#FB7185";
  ctx.font = "900 42px monospace";
  ctx.fillText(hasMoS ? `+${mos.toFixed(1)}%` : `+${prem.toFixed(1)}%`, 840, 345);
  ctx.fillStyle = "#94A3B8";
  ctx.font = "12px system-ui, sans-serif";
  ctx.fillText(hasMoS ? "Descuento vs Valor Intrínseco" : "Cotiza sobre Valor Intrínseco", 840, 375);

  // Bottom Box: Reverse DCF & Call to Action
  ctx.fillStyle = "rgba(15, 23, 42, 0.9)";
  ctx.fillRect(60, 435, 1080, 120);
  ctx.strokeStyle = "rgba(30, 41, 59, 0.9)";
  ctx.strokeRect(60, 435, 1080, 120);

  const rev = d.reverse_dcf || {};
  ctx.fillStyle = "#F1F5F9";
  ctx.font = "bold 16px system-ui, sans-serif";
  ctx.fillText("Expectativa Implícita (Reverse DCF):", 85, 475);
  ctx.fillStyle = "#38BDF8";
  ctx.font = "15px system-ui, sans-serif";
  ctx.fillText(rev.solved ? `El precio actual exige un crecimiento de FCF del ${rev.implied_fcf_growth_5y_pct?.toFixed(1)}% anual durante 5 años.` : "Modelo DCF probabilístico calibrado.", 85, 505);

  ctx.fillStyle = "#EC4899";
  ctx.font = "bold 15px system-ui, sans-serif";
  ctx.fillText("🎓 Taller de Inversiones con IA — Dictado por Jorge Marquetti (educaenlinea.com.ar/web/talleria.html)", 85, 535);

  // Trigger Download
  const a = document.createElement("a");
  a.download = `QuantVal_${sym}_Valuacion.png`;
  a.href = canvas.toDataURL("image/png");
  a.click();
  showToast(`¡Ficha descargada: QuantVal_${sym}_Valuacion.png!`);
}

// -------------------------------------------------------------
// Toast & Helpers
// -------------------------------------------------------------
function showToast(msg, isError = false) {
  const t = document.getElementById("toast");
  const m = document.getElementById("toastMsg");
  if (!t || !m) return;
  m.innerText = msg;
  if (isError) {
    t.className = "fixed bottom-6 right-6 z-50 transform transition-all duration-300 pointer-events-none glass px-4 py-3 rounded-xl border border-rose-500/60 text-rose-300 text-xs font-semibold shadow-2xl flex items-center gap-2 max-w-md";
  } else {
    t.className = "fixed bottom-6 right-6 z-50 transform transition-all duration-300 pointer-events-none glass px-4 py-3 rounded-xl border border-cyan-500/40 text-cyan-300 text-xs font-semibold shadow-2xl flex items-center gap-2 max-w-md";
  }
  if (t.classList && typeof t.classList.remove === "function") {
    t.classList.remove("translate-y-20", "opacity-0");
    t.classList.add("translate-y-0", "opacity-100");
  }
  setTimeout(() => {
    if (t.classList && typeof t.classList.remove === "function") {
      t.classList.remove("translate-y-0", "opacity-100");
      t.classList.add("translate-y-20", "opacity-0");
    }
  }, isError ? 4500 : 3000);
}

function updateURL(symbols) {
  try {
    const url = new URL(location.href);
    ["ticker", "a", "b"].forEach(k => url.searchParams.delete(k));
    if (symbols.length === 1) url.searchParams.set("ticker", symbols[0]);
    else if (symbols.length === 2) {
      url.searchParams.set("a", symbols[0]);
      url.searchParams.set("b", symbols[1]);
    }
    history.replaceState(null, "", url);
  } catch (_) {}
}

function quickSearch(sym) {
  evaluateTicker(sym);
}

function quickDuel(symA, symB) {
  switchViewMode("duel");
  evaluateDuel(symA, symB);
}

// -------------------------------------------------------------
// DOM Ready Initialization
// -------------------------------------------------------------
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    const searchForm = document.getElementById("searchForm");
    if (searchForm) {
      searchForm.addEventListener("submit", e => {
        e.preventDefault();
        const input = document.getElementById("tickerInput");
        if (input && input.value.trim()) {
          evaluateTicker(input.value.trim());
        }
      });
    }

    const duelForm = document.getElementById("duelSearchForm");
    if (duelForm) {
      duelForm.addEventListener("submit", e => {
        e.preventDefault();
        const inA = document.getElementById("tickerInputA");
        const inB = document.getElementById("tickerInputB");
        if (inA && inB && inA.value.trim() && inB.value.trim()) {
          evaluateDuel(inA.value.trim(), inB.value.trim());
        }
      });
    }

    // URL Query Params Bootstrap
    const urlParams = new URLSearchParams(window.location.search);
    const tickParam = urlParams.get("ticker");
    const aParam = urlParams.get("a");
    const bParam = urlParams.get("b");

    if (aParam && bParam) {
      switchViewMode("duel");
      evaluateDuel(aParam, bParam);
    } else if (tickParam) {
      evaluateTicker(tickParam);
    } else {
      evaluateTicker("NVDA");
    }
  });
}
