"use strict";
const $ = id => document.getElementById(id);
const KIND = {reported:"Dato reportado",calculated:"Cálculo histórico"};
let mode = "single", generation = 0, requestController, current = [];
const nf = new Intl.NumberFormat("es-AR",{maximumFractionDigits:2});
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
  const timeout = setTimeout(()=>controller.abort("timeout"),70000);
  try {
    const data = await Promise.all(symbols.map(s=>getData(s,controller.signal)));
    if(id!==generation) return;
    current = data;
    if(data.length===1) renderSingle(data[0]); else renderComparison(data);
    $("result-tools").hidden = false; updateURL(symbols);
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
  details.append(el("p",d.valuation?.reason||"Análisis histórico con datos públicos."));
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
function renderSingle(d) {
  const section=$("results"); section.replaceChildren(); const panel=el("div",undefined,"panel");
  panel.append(companyHead(d),quoteBlock(d));
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
  panel.append(grid,notices,sourceBlock(d));section.append(panel);section.hidden=false;
}
function comparisonRows(data) {
  const ids=[...new Set(data.flatMap(d=>d.metrics.map(m=>m.id)))];
  return ids.map(id=>({id,metrics:data.map(d=>d.metrics.find(m=>m.id===id)||null)}));
}
function renderComparison(data) {
  const section=$("comparison");section.replaceChildren();const panel=el("div",undefined,"panel"),heads=el("div",undefined,"compare-heads");
  data.forEach(d=>heads.append(companyHead(d)));
  panel.append(heads,el("p","Comparación descriptiva: no declara una empresa ganadora. Los importes absolutos dependen del tamaño y los cierres fiscales pueden diferir. Revisá las definiciones y fuentes.","hint"),el("p","Deslizá la tabla hacia los lados si no entra en tu pantalla.","hint"));
  const wrap=el("div",undefined,"table-wrap");wrap.tabIndex=0;wrap.setAttribute("aria-label","Tabla comparativa con desplazamiento horizontal");
  const table=el("table"),thead=el("thead"),head=el("tr");["Indicador",...data.map(d=>d.symbol)].forEach(t=>head.append(el("th",t)));
  thead.append(head);table.append(thead);const body=el("tbody");
  comparisonRows(data).forEach(({metrics})=>{
    const m=metrics.find(Boolean),tr=el("tr"),label=el("td",m.label);label.append(el("small",m.formula));tr.append(label);
    metrics.forEach(x=>tr.append(el("td",x?formatMetric(x):"No comparable","value")));body.append(tr);
  });
  table.append(body);wrap.append(table);const sources=el("div",undefined,"compare-sources");data.forEach(d=>sources.append(sourceBlock(d)));
  panel.append(wrap,sources);section.append(panel);section.hidden=false;
}
function summary(data) {
  return data.map(d=>{
    const lines=["QuantVal Pro — "+d.name+" ("+d.symbol+")","Ejercicio anual: "+d.period.start+" al "+d.period.end,"Datos en USD; no son TTM ni estimaciones.",""];
    if(validNumber(d.quote?.price)) lines.push("Cotización informativa: "+d.quote.currency+" "+nf.format(d.quote.price)+" · "+timeLabel(d.quote.as_of),d.quote.note||"","Fuente de cotización: "+d.quote.url,"");
    d.metrics.forEach(m=>{
      lines.push(m.label+": "+formatMetric(m)+" ["+(KIND[m.kind]||m.kind)+"]", "Fórmula: "+m.formula);
      (m.sources||[]).forEach(s=>lines.push("Input: "+s.tag+" = USD "+nf.format(s.value)+" · cierre "+s.period_end+" · "+s.url));
    });
    lines.push("","Fuentes:");(d.sources||[]).forEach(s=>lines.push(s.form+" · "+s.filed_at+" · "+s.url));
    lines.push("Consulta: "+d.retrieved_at,"",d.valuation?.reason||"Sin estimaciones de valor intrínseco.");
    return lines.join("\n");
  }).join("\n\n---\n\n")+"\n\nInformación educativa; no constituye asesoramiento ni recomendación de inversión.\n@accionesargentinas — Taller de Inversiones con IA.";
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text);$("copy-status").textContent="Copiado."; }
  catch (_) {$("copy-status").textContent="El navegador no permitió copiar. Podés seleccionar el texto de la pantalla.";}
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
fetch("/api/config").then(r=>r.ok?r.json():Promise.reject()).then(c=>{
  $("taller-link").href=c.taller_url;$("taller-link").textContent=c.taller_label;$("taller-note").textContent=c.taller_note;
  $("release").textContent="Versión "+c.version+" · "+c.model_version+" · Commit "+String(c.commit).slice(0,12);
}).catch(()=>{});
const params=new URLSearchParams(location.search);
if(params.get("a")&&params.get("b")){$("ticker-a").value=params.get("a");$("ticker-b").value=params.get("b");setMode("compare");$("compare-form").requestSubmit();}
else if(params.get("ticker")){$("ticker").value=params.get("ticker");submitSingle();}
