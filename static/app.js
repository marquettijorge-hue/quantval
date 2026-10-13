"use strict";
const $ = id => document.getElementById(id);
const KIND = {reported:"Dato reportado",calculated:"Cálculo histórico"};
let mode = "single", generation = 0, requestController, current = [];
let simState = null;
const nf = new Intl.NumberFormat("es-AR",{maximumFractionDigits:2});

function trackEvent(name, data) {
  try {
    const payload = { event: name, ...(data||{}), timestamp: new Date().toISOString() };
    if (typeof window !== "undefined" && window.dataLayer && Array.isArray(window.dataLayer)) {
      window.dataLayer.push(payload);
    }
    if (typeof sessionStorage !== "undefined") {
      const existing = JSON.parse(sessionStorage.getItem("quantval_events") || "[]");
      existing.push(payload);
      sessionStorage.setItem("quantval_events", JSON.stringify(existing.slice(-50)));
    }
  } catch (_) {}
}

function validNumber(value) { return typeof value === "number" && Number.isFinite(value); }

function formatMetric(m) {
  if (!m || m.status !== "available" || !validNumber(m.value)) return "No disponible";
  if (m.unit === "percent") return nf.format(m.value * 100) + "%";
  if (m.unit === "USD") {
    const n = m.value, abs = Math.abs(n);
    return "US$ " + nf.format(n / (abs >= 1e9 ? 1e9 : abs >= 1e6 ? 1e6 : 1)) + (abs >= 1e9 ? " mil millones" : abs >= 1e6 ? " millones" : "");
  }
  return nf.format(m.value);
}

function dateLabel(value) {
  if (!value) return "Fecha no disponible";
  const parsed = new Date(value.length === 10 ? value + "T12:00:00Z" : value);
  return Number.isNaN(parsed.getTime()) ? "Fecha no disponible" : parsed.toLocaleDateString("es-AR",{timeZone:"UTC"});
}

function timeLabel(value) {
  if (!value) return "Fecha no disponible";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "Fecha no disponible" : d.toLocaleString("es-AR",{timeZone:"UTC"}) + " UTC";
}

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function safeLink(text,url) {
  const a = el("a",text);
  try { const u = new URL(url); if (u.protocol === "https:") {a.href = u.href; a.target="_blank"; a.rel="noopener noreferrer";} }
  catch (_) {}
  return a;
}

function showError(message) {
  generation++; if(requestController) requestController.abort(); current=[];
  $("results").hidden=$("comparison").hidden=$("result-tools").hidden=$("loading").hidden=true;
  $("error").textContent=message; $("error").hidden=false;
  trackEvent("analysis_failed", { error: message });
}

function setMode(next) {
  mode = next;
  $("single-form").hidden = next !== "single"; $("compare-form").hidden = next !== "compare";
  ["single","compare"].forEach(m => { $("tab-"+m).classList.toggle("selected",m===next); $("tab-"+m).setAttribute("aria-pressed",String(m===next)); });
}

function normalizeInput(value) {
  const sym = value.trim().toUpperCase().replaceAll(".","-");
  if (!/^[A-Z][A-Z0-9]{0,7}(?:-[A-Z0-9]{1,2})?$/.test(sym)) throw new Error("Ingresá un ticker válido. Ejemplos: AAPL, MSFT o BRK-B.");
  return sym;
}

async function getData(symbol,signal) {
  const response = await fetch("/api/evaluate/"+encodeURIComponent(symbol),{signal});
  let data; try { data = await response.json(); } catch (_) { throw new Error("El servicio no respondió correctamente. Probá nuevamente."); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No pudimos completar el análisis.");
  if (!Array.isArray(data.metrics) || !data.period || data.symbol !== symbol) throw new Error("El resultado no coincide con la empresa solicitada.");
  return data;
}

function updateURL(symbols) {
  const url = new URL(location.href);
  ["ticker","a","b"].forEach(k=>url.searchParams.delete(k));
  if (symbols.length===1) url.searchParams.set("ticker",symbols[0]);
  else {url.searchParams.set("a",symbols[0]);url.searchParams.set("b",symbols[1]);}
  try {history.replaceState(null,"",url);} catch (_) {}
}

async function analyze(symbols) {
  const id = ++generation;
  if(requestController) requestController.abort();
  requestController = new AbortController();
  const controller = requestController;
  current = [];
  $("results").hidden = $("comparison").hidden = $("result-tools").hidden = true;
  $("error").hidden = true; $("copy-status").textContent = ""; $("loading").hidden = false;
  $("loading").textContent = "Consultando "+symbols.join(" y ")+" en balances públicos…";
  trackEvent("analysis_started", { symbols });
  const timeout = setTimeout(()=>controller.abort("timeout"),70000);
  try {
    const data = await Promise.all(symbols.map(s=>getData(s,controller.signal)));
    if(id!==generation) return;
    current = data;
    if(data.length===1) renderSingle(data[0]); else renderComparison(data);
    $("result-tools").hidden = false; updateURL(symbols);
    trackEvent("analysis_completed", { symbols });
  } catch(error) {
    if(id!==generation) return;
    showError(controller.signal.aborted ? "La consulta tardó demasiado. Volvé a intentar en unos segundos." : error.message || "No pudimos completar el análisis.");
  } finally {clearTimeout(timeout); if(id===generation) $("loading").hidden=true;}
}

function sourceBlock(d) {
  const details = el("details",undefined,"sources"); details.append(el("summary","Fuentes, fechas y alcance"));
  details.append(el("p","Ejercicio: "+dateLabel(d.period.start)+" al "+dateLabel(d.period.end)+". Consulta: "+timeLabel(d.retrieved_at)+"."));
  const list = el("ul");
  (d.sources||[]).forEach(s=>{const li=el("li");li.append(safeLink(s.form+" publicado el "+dateLabel(s.filed_at),s.url));li.append(el("small","Datos con cierre "+dateLabel(s.period_end)));list.append(li);});
  details.append(list, safeLink("Datos estructurados SEC usados en el cálculo",d.facts_url));
  if(d.cache?.hit) details.append(el("p","Respuesta en caché: "+Math.round(d.cache.age_seconds/60)+" minutos desde la consulta. La fecha del precio se informa por separado."));
  details.append(el("p",d.valuation?.reason||"Análisis histórico con datos públicos de la SEC."));
  return details;
}

function companyHead(d) {
  const head=el("div",undefined,"company-head"), left=el("div");
  left.append(el("span",d.symbol,"ticker-tag"),el("h2",d.name),el("p",d.activity,"activity"));
  head.append(left,el("span","Ejercicio al "+dateLabel(d.period.end),"period-badge"));return head;
}

function quoteBlock(d) {
  const box=el("div",undefined,"quote"),q=d.quote||{};
  const text=validNumber(q.price)?(q.currency+" "+nf.format(q.price)):"Cotización no disponible";
  box.append(el("strong",text));const info=el("div");
  info.append(el("small",validNumber(q.price)?"Precio al "+timeLabel(q.as_of)+" · "+(q.status==="stale"?"Dato antiguo · ":"")+q.note:q.note||"Los balances pueden analizarse aunque no haya cotización."));
  if(q.url)info.append(safeLink("Ver cotización en Yahoo Finance",q.url));box.append(info);return box;
}

// Client-side exact financial math engine
function runDcfModel(startFcf, shares, cash, debt, wacc, growth5y, gTerm) {
  if (!startFcf || !shares || shares <= 0) return 0;
  wacc = Math.max(0.05, wacc);
  gTerm = Math.min(wacc - 0.015, Math.max(0.01, gTerm));
  let pvFcf = 0;
  let fcf = startFcf;
  const flows = [];
  for (let yr = 1; yr <= 10; yr++) {
    if (yr > 1 && yr <= 5) {
      fcf *= (1.0 + growth5y);
    } else if (yr > 5) {
      const fade = (yr - 5) / 5.0;
      const gFade = growth5y * (1.0 - fade) + 0.025 * fade;
      fcf *= (1.0 + gFade);
    }
    const pv = fcf / Math.pow(1.0 + wacc, yr);
    pvFcf += pv;
    if (yr <= 5) flows.push({ year: yr, fcf, pv });
  }
  const tv = (fcf * (1.0 + gTerm)) / Math.max(0.015, wacc - gTerm);
  const pvTv = tv / Math.pow(1.0 + wacc, 10);
  const ev = pvFcf + pvTv;
  const equity = ev + (cash || 0) - (debt || 0);
  const perShare = Math.max(0, equity / shares);
  return { perShare: Math.round(perShare * 100) / 100, flows, pvTv, ev, tv };
}

function reverseDcfBox(d) {
  const v = d.valuation || {};
  const box = el("section", undefined, "reverse-dcf-box");
  const title = el("div", undefined, "rdcf-header");
  title.append(el("span", "✦ EXPERIENCIA PRINCIPAL", "rdcf-eyebrow"), el("h3", "¿Qué está descontando el precio de mercado?"));
  box.append(title);

  if (v.status === "available" && v.reverse_dcf) {
    const rd = v.reverse_dcf;
    const body = el("div", undefined, "rdcf-content");
    const quoteTxt = el("blockquote", rd.text, "rdcf-quote");
    const sub = el("p", "Esta cifra representa la expectativa implícita que el modelo requiere para igualar la cotización actual, manteniendo constantes los demás supuestos. No es una predicción ni consenso.", "rdcf-note");
    body.append(quoteTxt, sub);
    box.append(body);
  } else if (v.model_type === "banking_valuation") {
    const body = el("div", undefined, "rdcf-content");
    const note = el("blockquote", v.reason, "rdcf-quote");
    const pbText = el("p", "Valor libro por acción: US$ " + nf.format(v.book_value_per_share) + " · P/B Justificado: " + nf.format(v.justified_pb) + "x · Valor Patrimonial Estimado: US$ " + nf.format(v.fair_value), "rdcf-note");
    body.append(note, pbText);
    box.append(body);
  } else {
    const body = el("div", undefined, "rdcf-content");
    body.append(el("p", v.reason || "Valoración no disponible para este emisor con los balances actuales.", "rdcf-note"));
    box.append(body);
  }
  return box;
}

function scenariosRangeBlock(d) {
  const v = d.valuation;
  if (!v || v.status !== "available" || !v.scenarios) return el("div");
  const block = el("section", undefined, "scenarios-section");
  const head = el("div", undefined, "scenarios-head");
  head.append(el("h3", "Rango de Valoración Probabilístico (3 Escenarios)"));
  
  const evVal = v.composite_fair_value;
  const p = d.quote?.price;
  const mos = validNumber(p) && evVal > 0 ? Math.round(((evVal - p) / evVal) * 1000) / 10 : null;
  const evBadge = el("div", undefined, "composite-ev-badge");
  evBadge.append(el("span", "Valor Estimado Ponderado: US$ " + nf.format(evVal)), el("strong", mos !== null ? (mos >= 0 ? "+" : "") + mos + "% Margen de Seguridad" : "Sin cotización", mos !== null && mos >= 0 ? "mos-positive" : "mos-negative"));
  head.append(evBadge);
  block.append(head);

  const cards = el("div", undefined, "scenarios-grid");
  const sc = v.scenarios;
  [
    { key: "bear", data: sc.bear, color: "bear" },
    { key: "base", data: sc.base, color: "base" },
    { key: "bull", data: sc.bull, color: "bull" }
  ].forEach(({ data, color }) => {
    if (!data) return;
    const card = el("div", undefined, "scenario-card " + color);
    card.append(el("span", data.label + " (" + (data.probability * 100) + "%)", "sc-tag"));
    card.append(el("div", "US$ " + nf.format(data.fair_value), "sc-price"));
    const details = el("div", undefined, "sc-params");
    details.append(el("span", "Crecimiento: " + nf.format(data.growth_assumed_pct) + "%"), el("span", "WACC: " + nf.format(data.wacc_assumed_pct) + "%"), el("span", "Terminal: " + nf.format(data.terminal_g_pct) + "%"));
    card.append(details, el("p", data.hypothesis, "sc-hypo"));
    cards.append(card);
  });
  block.append(cards);
  return block;
}

function simulatorLabBlock(d) {
  const v = d.valuation;
  if (!v || v.status !== "available") return el("div");
  const lab = el("section", undefined, "simulator-lab");
  const head = el("div", undefined, "sim-header");
  head.append(el("div", undefined, "sim-title-group"));
  head.querySelector("div").append(el("span", "✦ LABORATORIO INTERACTIVO", "sim-eyebrow"), el("h3", "Simulador de Sensibilidad What-If"));
  
  const resetBtn = el("button", "Restablecer escenario base", "reset-sim-btn");
  resetBtn.type = "button";
  head.append(resetBtn);
  lab.append(head);

  // Initialize simulation state
  const baseGrowth = v.growth || 0.12;
  const baseWacc = v.wacc || 0.10;
  const baseGTerm = v.terminal_growth || 0.025;
  simState = {
    startFcf: v.fcf_base,
    shares: v.shares,
    cash: v.cash || 0,
    debt: v.debt || 0,
    currentPrice: d.quote?.price,
    growth: baseGrowth,
    wacc: baseWacc,
    gTerm: baseGTerm,
    baseGrowth, baseWacc, baseGTerm
  };

  const simBody = el("div", undefined, "sim-body");

  // Controls container
  const controls = el("div", undefined, "sim-controls");

  // Slider 1: Growth
  const c1 = el("div", undefined, "sim-slider-row");
  const l1 = el("div", undefined, "slider-label-wrap");
  l1.append(el("label", "Crecimiento de FCF (Años 1 a 5)"), el("strong", (baseGrowth * 100).toFixed(1) + "%", "slider-val-g"));
  const inputG = el("input", undefined, "sim-slider");
  inputG.type = "range"; inputG.min = "-10"; inputG.max = "45"; inputG.step = "0.5"; inputG.value = (baseGrowth * 100).toFixed(1);
  c1.append(l1, inputG);

  // Slider 2: WACC
  const c2 = el("div", undefined, "sim-slider-row");
  const l2 = el("div", undefined, "slider-label-wrap");
  l2.append(el("label", "Tasa de Descuento (WACC)"), el("strong", (baseWacc * 100).toFixed(2) + "%", "slider-val-w"));
  const inputW = el("input", undefined, "sim-slider");
  inputW.type = "range"; inputW.min = "6"; inputW.max = "16"; inputW.step = "0.25"; inputW.value = (baseWacc * 100).toFixed(2);
  c2.append(l2, inputW);

  // Slider 3: Terminal growth
  const c3 = el("div", undefined, "sim-slider-row");
  const l3 = el("div", undefined, "slider-label-wrap");
  l3.append(el("label", "Crecimiento Terminal Perpetuo (g)"), el("strong", (baseGTerm * 100).toFixed(1) + "%", "slider-val-t"));
  const inputT = el("input", undefined, "sim-slider");
  inputT.type = "range"; inputT.min = "1.0"; inputT.max = "3.5"; inputT.step = "0.1"; inputT.value = (baseGTerm * 100).toFixed(1);
  c3.append(l3, inputT);

  controls.append(c1, c2, c3);

  // Output cards
  const output = el("div", undefined, "sim-output-card");
  const outTitle = el("span", "Valoración Simulada Resultante", "out-title");
  const outVal = el("div", "US$ --", "out-price-val");
  const outSpread = el("div", "--", "out-spread-val");
  const breakevenNote = el("p", "", "out-breakeven-note");
  output.append(outTitle, outVal, outSpread, breakevenNote);

  simBody.append(controls, output);
  lab.append(simBody);

  // Chart Container
  const chartSection = el("div", undefined, "sim-chart-wrap");
  chartSection.append(el("h4", "Flujos de Caja Proyectados y Descontados (Años 1-5 + Valor Terminal)"));
  const chartBars = el("div", undefined, "fcf-bars-row");
  chartSection.append(chartBars);
  lab.append(chartSection);

  // 2D Sensitivity Matrix
  const matrixWrap = el("div", undefined, "matrix-section");
  matrixWrap.append(el("h4", "Matriz 2D de Sensibilidad: Crecimiento vs Tasa de Descuento"));
  const matrixTableWrap = el("div", undefined, "matrix-table-wrap");
  matrixWrap.append(matrixTableWrap);
  lab.append(matrixWrap);

  function updateSimulation() {
    const res = runDcfModel(simState.startFcf, simState.shares, simState.cash, simState.debt, simState.wacc, simState.growth, simState.gTerm);
    outVal.textContent = "US$ " + nf.format(res.perShare);
    const p = simState.currentPrice;
    if (validNumber(p) && res.perShare > 0) {
      const mos = Math.round(((res.perShare - p) / res.perShare) * 1000) / 10;
      outSpread.textContent = (mos >= 0 ? "+" : "") + mos + "% frente a cotización (US$ " + nf.format(p) + ")";
      outSpread.className = "out-spread-val " + (mos >= 0 ? "mos-positive" : "mos-negative");
    } else {
      outSpread.textContent = "Sin cotización de mercado para comparar";
      outSpread.className = "out-spread-val";
    }

    // Breakeven growth note
    const beGrowth = ((p && simState.shares) ? ((p * simState.shares - simState.cash + simState.debt) / (v.fcf_base * 10)) : null);
    if (validNumber(p)) {
      if (res.perShare >= p) {
        breakevenNote.textContent = "✓ Supera el precio de mercado bajo estos supuestos.";
        breakevenNote.className = "out-breakeven-note text-green";
      } else {
        breakevenNote.textContent = "⚠ Por debajo del precio actual. Requiere mayor crecimiento o menor tasa para justificar la cotización.";
        breakevenNote.className = "out-breakeven-note text-amber";
      }
    }

    // Render Bars
    chartBars.replaceChildren();
    const maxVal = Math.max(...res.flows.map(f => f.fcf), res.pvTv);
    res.flows.forEach(f => {
      const col = el("div", undefined, "chart-col");
      const bar = el("div", undefined, "bar-fill");
      const pct = Math.max(8, Math.min(100, (f.fcf / maxVal) * 100));
      bar.style.height = pct + "%";
      bar.title = "Año " + f.year + ": US$ " + nf.format(f.fcf / 1e9) + "B";
      col.append(bar, el("span", "Año " + f.year, "bar-label"), el("small", "US$ " + nf.format(f.fcf / 1e9) + "B"));
      chartBars.append(col);
    });
    // Terminal PV bar
    const tvCol = el("div", undefined, "chart-col tv-col");
    const tvBar = el("div", undefined, "bar-fill tv-fill");
    tvBar.style.height = Math.max(8, Math.min(100, (res.pvTv / maxVal) * 100)) + "%";
    tvCol.append(tvBar, el("span", "Valor Term. (PV)", "bar-label"), el("small", "US$ " + nf.format(res.pvTv / 1e9) + "B"));
    chartBars.append(tvCol);

    // Render Matrix Table
    matrixTableWrap.replaceChildren();
    const gRange = [simState.growth - 0.04, simState.growth - 0.02, simState.growth, simState.growth + 0.02, simState.growth + 0.04];
    const wRange = [simState.wacc - 0.01, simState.wacc - 0.005, simState.wacc, simState.wacc + 0.005, simState.wacc + 0.01];
    const tbl = el("table", undefined, "matrix-table");
    const thead = el("thead");
    const hr = el("tr");
    hr.append(el("th", "Crec. / WACC"));
    wRange.forEach(w => hr.append(el("th", (w * 100).toFixed(2) + "%")));
    thead.append(hr);
    tbl.append(thead);

    const tbody = el("tbody");
    gRange.forEach(g => {
      const tr = el("tr");
      tr.append(el("th", (g * 100).toFixed(1) + "%"));
      wRange.forEach(w => {
        const cellVal = runDcfModel(simState.startFcf, simState.shares, simState.cash, simState.debt, w, g, simState.gTerm).perShare;
        const td = el("td", "US$ " + nf.format(cellVal), "matrix-cell");
        if (validNumber(p)) {
          if (cellVal >= p) td.classList.add("cell-above");
          else td.classList.add("cell-below");
        }
        if (Math.abs(g - simState.growth) < 0.001 && Math.abs(w - simState.wacc) < 0.001) {
          td.classList.add("cell-active");
        }
        tr.append(td);
      });
      tbody.append(tr);
    });
    tbl.append(tbody);
    matrixTableWrap.append(tbl);
  }

  inputG.addEventListener("input", e => {
    simState.growth = parseFloat(e.target.value) / 100.0;
    c1.querySelector(".slider-val-g").textContent = e.target.value + "%";
    updateSimulation();
    trackEvent("simulator_used", { param: "growth", value: e.target.value });
  });

  inputW.addEventListener("input", e => {
    simState.wacc = parseFloat(e.target.value) / 100.0;
    c2.querySelector(".slider-val-w").textContent = e.target.value + "%";
    updateSimulation();
    trackEvent("simulator_used", { param: "wacc", value: e.target.value });
  });

  inputT.addEventListener("input", e => {
    simState.gTerm = parseFloat(e.target.value) / 100.0;
    c3.querySelector(".slider-val-t").textContent = e.target.value + "%";
    updateSimulation();
    trackEvent("simulator_used", { param: "terminal_growth", value: e.target.value });
  });

  resetBtn.addEventListener("click", () => {
    simState.growth = simState.baseGrowth;
    simState.wacc = simState.baseWacc;
    simState.gTerm = simState.baseGTerm;
    inputG.value = (simState.baseGrowth * 100).toFixed(1);
    c1.querySelector(".slider-val-g").textContent = inputG.value + "%";
    inputW.value = (simState.baseWacc * 100).toFixed(2);
    c2.querySelector(".slider-val-w").textContent = inputW.value + "%";
    inputT.value = (simState.baseGTerm * 100).toFixed(1);
    c3.querySelector(".slider-val-t").textContent = inputT.value + "%";
    updateSimulation();
    trackEvent("simulator_reset", {});
  });

  updateSimulation();
  return lab;
}

function renderSingle(d) {
  const section=$("results"); section.replaceChildren(); const panel=el("div",undefined,"panel");
  panel.append(companyHead(d), quoteBlock(d));

  // 1. Primary Reverse DCF & Expectations
  panel.append(reverseDcfBox(d));

  // 2. Probabilistic Scenarios Range
  panel.append(scenariosRangeBlock(d));

  // 3. Interactive Sensitivity Lab
  panel.append(simulatorLabBlock(d));

  // 4. Core Verified Fundamental Metrics
  const coreTitle = el("h3", "Indicadores Fundamentales Reportados y Auditados (SEC)", "sec-metrics-title");
  panel.append(coreTitle);
  const grid=el("div",undefined,"grid");
  d.metrics.forEach(m=>{
    const card=el("article",undefined,"metric");
    card.append(el("span",KIND[m.kind]||"Indicador","kind"),el("h3",m.label),el("div",formatMetric(m),"metric-value"+(m.status!=="available"?" missing":"")));
    const def=el("details");def.append(el("summary","Cómo se calcula y fuente"),el("p",m.formula));
    if(m.note)def.append(el("p",m.note));
    (m.sources||[]).forEach(s=>{def.append(safeLink(s.form+" · "+dateLabel(s.filed_at),s.url),el("p",s.tag+" · USD "+nf.format(s.value)+" · "+(s.period_start?dateLabel(s.period_start)+" al ":"")+dateLabel(s.period_end)));});
    if(m.status!=="available")def.append(el("p","No hay datos suficientes para este indicador. No se sustituyen por cero."));
    card.append(def);grid.append(card);
  });
  const notices=el("div",undefined,"notices");(d.warnings||[]).forEach(w=>notices.append(el("p",w)));
  panel.append(grid,notices,sourceBlock(d));
  section.append(panel);
  section.hidden=false;
}

function comparisonRows(data) {
  const ids=[...new Set(data.flatMap(d=>d.metrics.map(m=>m.id)))];
  return ids.map(id=>({id,metrics:data.map(d=>d.metrics.find(m=>m.id===id)||null)}));
}

function renderComparison(data) {
  const section=$("comparison");section.replaceChildren();const panel=el("div",undefined,"panel"),heads=el("div",undefined,"compare-heads");
  data.forEach(d=>heads.append(companyHead(d)));
  panel.append(heads,el("p","Comparación descriptiva de expectativas y fundamentos. Los importes absolutos dependen del tamaño y los cierres fiscales pueden diferir. Revisá las definiciones y fuentes.","hint"),el("p","Deslizá la tabla hacia los lados si no entra en tu pantalla.","hint"));
  
  // Expectations Comparison Block
  const expWrap = el("div", undefined, "compare-exp-block");
  expWrap.append(el("h3", "Expectativas de Mercado Comparadas (Reverse DCF)"));
  const expGrid = el("div", undefined, "compare-exp-grid");
  data.forEach(d => {
    const col = el("div", undefined, "compare-exp-col");
    col.append(el("h4", d.name + " (" + d.symbol + ")"));
    if (d.valuation?.reverse_dcf?.implied_growth_pct !== undefined) {
      col.append(el("p", "Crecimiento exigido por el precio: " + nf.format(d.valuation.reverse_dcf.implied_growth_pct) + "% anual a 5 años.", "compare-exp-val"));
    } else {
      col.append(el("p", d.valuation?.reason || "Modelo DCF no disponible.", "compare-exp-val"));
    }
    if (d.valuation?.composite_fair_value) {
      col.append(el("p", "Valor Intrínseco Estimado: US$ " + nf.format(d.valuation.composite_fair_value)));
    }
    expGrid.append(col);
  });
  expWrap.append(expGrid);
  panel.append(expWrap);

  const wrap=el("div",undefined,"table-wrap");wrap.tabIndex=0;wrap.setAttribute("aria-label","Tabla comparativa con desplazamiento horizontal");
  const table=el("table"),thead=el("thead"),head=el("tr");["Indicador",...data.map(d=>d.symbol)].forEach(t=>head.append(el("th",t)));
  thead.append(head);table.append(thead);const body=el("tbody");
  comparisonRows(data).forEach(({metrics})=>{
    const m=metrics.find(Boolean),tr=el("tr"),label=el("td",m.label);label.append(el("small",m.formula));tr.append(label);
    metrics.forEach(x=>tr.append(el("td",x?formatMetric(x):"No comparable","value")));body.append(tr);
  });
  table.append(body);wrap.append(table);const sources=el("div",undefined,"compare-sources");data.forEach(d=>sources.append(sourceBlock(d)));
  panel.append(wrap,sources);section.append(panel);section.hidden=false;
  trackEvent("comparison_viewed", { symbols: data.map(d=>d.symbol) });
}

function summary(data) {
  return data.map(d=>{
    const lines=["QuantVal Pro — "+d.name+" ("+d.symbol+")","Ejercicio anual: "+d.period.start+" al "+d.period.end,"Datos oficiales en USD de SEC EDGAR.",""];
    if(validNumber(d.quote?.price)) lines.push("Cotización actual: "+d.quote.currency+" "+nf.format(d.quote.price)+" · "+timeLabel(d.quote.as_of),d.quote.note||"","Fuente de cotización: "+d.quote.url,"");
    if(d.valuation?.status === "available") {
      lines.push("### Valuación DCF y Expectativas de Mercado");
      if (d.valuation.reverse_dcf?.text) lines.push(d.valuation.reverse_dcf.text);
      if (d.valuation.scenarios) {
        lines.push("Escenario Pesimista: US$ " + nf.format(d.valuation.scenarios.bear.fair_value));
        lines.push("Escenario Base: US$ " + nf.format(d.valuation.scenarios.base.fair_value));
        lines.push("Escenario Optimista: US$ " + nf.format(d.valuation.scenarios.bull.fair_value));
        lines.push("Valor Estimado Ponderado: US$ " + nf.format(d.valuation.composite_fair_value) + " (MoS: " + nf.format(d.valuation.margin_of_safety_pct) + "%)");
      }
      lines.push("");
    } else if (d.valuation?.model_type === "banking_valuation") {
      lines.push("### Valuación Bancaria (Gordon-Shapiro)");
      lines.push("Valor Libro por Acción: US$ " + nf.format(d.valuation.book_value_per_share));
      lines.push("P/B Justificado: " + nf.format(d.valuation.justified_pb) + "x");
      lines.push("Valor Patrimonial Estimado: US$ " + nf.format(d.valuation.fair_value));
      lines.push("");
    }
    lines.push("### Indicadores Fundamentales:");
    d.metrics.forEach(m=>{
      lines.push(m.label+": "+formatMetric(m)+" ["+(KIND[m.kind]||m.kind)+"]", "Fórmula: "+m.formula);
      (m.sources||[]).forEach(s=>lines.push("Input: "+s.tag+" = USD "+nf.format(s.value)+" · cierre "+s.period_end+" · "+s.url));
    });
    lines.push("","Fuentes:");(d.sources||[]).forEach(s=>lines.push(s.form+" · "+s.filed_at+" · "+s.url));
    lines.push("Consulta: "+d.retrieved_at,"",d.valuation?.reason||"Análisis fundamental independiente.");
    return lines.join("\n");
  }).join("\n\n---\n\n")+"\n\nInformación educativa; no constituye asesoramiento ni recomendación de inversión.\n@accionesargentinas — Taller de Inversiones con IA.";
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text);$("copy-status").textContent="Copiado."; trackEvent("report_copied", {}); }
  catch (_) {$("copy-status").textContent="El navegador no permitió copiar. Podés seleccionar el texto de la pantalla.";}
}

function downloadCardPng() {
  if (!current.length || typeof document === "undefined") return;
  const d = current[0];
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 675;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  // Background
  const grad = ctx.createLinearGradient(0, 0, 1200, 675);
  grad.addColorStop(0, "#0b101b");
  grad.addColorStop(1, "#152238");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 1200, 675);

  // Border
  ctx.strokeStyle = "#2b3850";
  ctx.lineWidth = 3;
  ctx.strokeRect(20, 20, 1160, 635);

  // Header Logo & Branding
  ctx.fillStyle = "#5ce3eb";
  ctx.font = "bold 28px sans-serif";
  ctx.fillText("↗ QuantVal PRO", 50, 70);

  ctx.fillStyle = "#a899ff";
  ctx.font = "bold 20px sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("@accionesargentinas", 1150, 70);
  ctx.textAlign = "left";

  // Company Name & Ticker
  ctx.fillStyle = "#edf4ff";
  ctx.font = "bold 38px sans-serif";
  ctx.fillText(d.name + " (" + d.symbol + ")", 50, 130);

  // Quote & Date
  const qPrice = validNumber(d.quote?.price) ? ("USD " + nf.format(d.quote.price)) : "Cotización N/D";
  ctx.fillStyle = "#5ce3eb";
  ctx.font = "bold 32px sans-serif";
  ctx.fillText(qPrice, 50, 180);

  ctx.fillStyle = "#b5c2d7";
  ctx.font = "16px sans-serif";
  ctx.fillText("Ejercicio al " + dateLabel(d.period.end) + " · Fuente: SEC EDGAR", 50, 215);

  // Horizontal divider
  ctx.strokeStyle = "#2b3850";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(50, 235);
  ctx.lineTo(1150, 235);
  ctx.stroke();

  // Reverse DCF Callout Box
  ctx.fillStyle = "#121b2b";
  ctx.fillRect(50, 255, 1100, 110);
  ctx.strokeStyle = "#5ce3eb";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(50, 255, 1100, 110);

  ctx.fillStyle = "#5ce3eb";
  ctx.font = "bold 16px sans-serif";
  ctx.fillText("EXPECTATIVA IMPLÍCITA DE MERCADO (REVERSE DCF)", 70, 285);

  ctx.fillStyle = "#edf4ff";
  ctx.font = "18px sans-serif";
  const rdText = d.valuation?.reverse_dcf?.text || (d.valuation?.reason || "Valuación no disponible.");
  ctx.fillText(rdText.length > 105 ? rdText.slice(0, 102) + "..." : rdText, 70, 320);

  // Scenarios Box
  const v = d.valuation || {};
  if (v.scenarios) {
    const scY = 395;
    ctx.fillStyle = "#edf4ff";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText("Rango de Valoración Intrínseca:", 50, scY);

    // Bear
    ctx.fillStyle = "#fda4af";
    ctx.font = "18px sans-serif";
    ctx.fillText("Pesimista: US$ " + nf.format(v.scenarios.bear.fair_value), 50, scY + 35);

    // Base
    ctx.fillStyle = "#5ce3eb";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText("Base: US$ " + nf.format(v.scenarios.base.fair_value), 320, scY + 35);

    // Bull
    ctx.fillStyle = "#6ee7b7";
    ctx.font = "18px sans-serif";
    ctx.fillText("Optimista: US$ " + nf.format(v.scenarios.bull.fair_value), 580, scY + 35);

    // Fair value weighted
    ctx.fillStyle = "#edf4ff";
    ctx.font = "bold 22px sans-serif";
    ctx.fillText("Valor Ponderado: US$ " + nf.format(v.composite_fair_value), 830, scY + 35);
  }

  // Fundamentals row
  const fundY = 490;
  ctx.fillStyle = "#b5c2d7";
  ctx.font = "bold 16px sans-serif";
  ctx.fillText("Fundamentos SEC:", 50, fundY);

  ctx.font = "16px sans-serif";
  let curX = 50;
  (d.metrics || []).slice(0, 4).forEach(m => {
    ctx.fillStyle = "#edf4ff";
    ctx.fillText(m.label + ": " + formatMetric(m), curX, fundY + 30);
    curX += 280;
  });

  // Footer Disclaimer
  ctx.fillStyle = "#64748b";
  ctx.font = "13px sans-serif";
  ctx.fillText("Contenido educativo. No constituye recomendación de inversión. Realizá tu propio análisis.", 50, 600);
  ctx.fillText("Taller de Inversiones con IA · Jorge Marquetti", 50, 625);

  // Trigger download
  const a = document.createElement("a");
  a.download = "QuantVal_" + d.symbol + "_Ficha.png";
  a.href = canvas.toDataURL("image/png");
  a.click();
  trackEvent("card_downloaded", { symbol: d.symbol });
}

function submitSingle() {
  const value=$("ticker").value;
  const pair=value.match(/^\s*([A-Za-z0-9.-]+)\s+(?:vs\.?|contra)\s+([A-Za-z0-9.-]+)\s*$/i);
  try {
    if(pair){const a=normalizeInput(pair[1]),b=normalizeInput(pair[2]);setMode("compare");$("ticker-a").value=a;$("ticker-b").value=b;analyze([a,b]);}
    else {const symbol=normalizeInput(value);$("ticker").value=symbol;setMode("single");analyze([symbol]);}
  }catch(error){showError(error.message);}
}

$("single-form").addEventListener("submit",e=>{e.preventDefault();submitSingle();});
$("compare-form").addEventListener("submit",e=>{e.preventDefault();try{const a=normalizeInput($("ticker-a").value),b=normalizeInput($("ticker-b").value);if(a===b)throw new Error("Elegí dos empresas diferentes.");$("ticker-a").value=a;$("ticker-b").value=b;analyze([a,b]);}catch(error){showError(error.message);}});
["single","compare"].forEach(m=>$("tab-"+m).addEventListener("click",()=>{generation++;if(requestController)requestController.abort();current=[];$("loading").hidden=$("results").hidden=$("comparison").hidden=$("result-tools").hidden=true;$("error").hidden=true;setMode(m);}));
document.querySelectorAll("[data-ticker]").forEach(b=>b.addEventListener("click",()=>{setMode("single");$("ticker").value=b.dataset.ticker;analyze([b.dataset.ticker]);}));
$("copy").addEventListener("click",()=>{if(current.length)copyText(summary(current));});
$("share").addEventListener("click",()=>{if(current.length)copyText(location.href);});
const downloadBtn = $("download-card");
if (downloadBtn) downloadBtn.addEventListener("click", downloadCardPng);

const tallerLink = $("taller-link");
if (tallerLink) tallerLink.addEventListener("click", () => trackEvent("taller_clicked", { href: tallerLink.href }));

fetch("/api/config").then(r=>r.ok?r.json():Promise.reject()).then(c=>{
  if($("taller-link")){ $("taller-link").href=c.taller_url;$("taller-link").textContent=c.taller_label;}
  if($("taller-note")) $("taller-note").textContent=c.taller_note;
  if($("release")) $("release").textContent="Versión "+c.version+" · "+c.model_version+" · Commit "+String(c.commit).slice(0,12);
}).catch(()=>{});

const params=new URLSearchParams(location.search);
if(params.get("a")&&params.get("b")){$("ticker-a").value=params.get("a");$("ticker-b").value=params.get("b");setMode("compare");$("compare-form").requestSubmit();}
else if(params.get("ticker")){$("ticker").value=params.get("ticker");submitSingle();}
