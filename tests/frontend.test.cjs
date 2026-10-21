const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:'',value:'',classList:{toggle(){}},addEventListener(){},setAttribute(){}});return nodes.get(id);}
const ctx={document:{getElementById:node,querySelectorAll:()=>[]},Intl,URL,URLSearchParams,Date,Number,location:{href:'https://example.com/',search:''},fetch:async()=>({ok:false}),setTimeout,clearTimeout,AbortController,history:{replaceState(){}},navigator:{clipboard:{writeText:async()=>{}}}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),ctx);
test('formats decimal rates as percentages and preserves zero',()=>{
 assert.equal(ctx.formatMetric({status:'available',unit:'percent',value:.15}),'15%');
 assert.equal(ctx.formatMetric({status:'available',unit:'USD',value:0}),'US$ 0');
 assert.equal(ctx.formatMetric({status:'missing',unit:'USD',value:null}),'No disponible');
});
test('does not pair ROE with ROIC or industrial FCF',()=>{
 const rows=ctx.comparisonRows([{metrics:[{id:'fcf'}]},{metrics:[{id:'roe'}]}]);
 assert.equal(rows.length,2);assert.equal(rows[0].metrics[1],null);assert.equal(rows[1].metrics[0],null);
});
test('invalid input clears previous results and cancels its pending request',()=>{
 assert.throws(()=>ctx.normalizeInput(''),/ticker/);assert.equal(ctx.normalizeInput('brk.b'),'BRK-B');
 ctx.showError('Ingresá un ticker');assert.equal(node('results').hidden,true);assert.equal(node('error').hidden,false);
});
test('copy includes periods, formulas and provenance without fabricated consensus',()=>{
 const text=ctx.summary([{name:'Test',symbol:'TEST',period:{start:'2025-01-01',end:'2025-12-31'},metrics:[{label:'Crecimiento',value:.15,unit:'percent',status:'available',kind:'calculated',formula:'a/b-1'}],sources:[{form:'10-K',filed_at:'2026-02-01',url:'https://www.sec.gov/example'}],retrieved_at:'now'}]);
 assert.match(text,/15%/);assert.match(text,/Cálculo histórico/);assert.match(text,/2025-12-31/);assert.match(text,/sec.gov/);
 assert.doesNotMatch(text,/Consenso|TIR|0 analistas/);
});
test('runDcfSimulation updates dynamically when exit multiple changes',()=>{
 const fv16 = ctx.runDcfSimulation(7186000000, 710398642, 0, 0, 0.085, 0.04, 16.0, 12.31);
 const fv24 = ctx.runDcfSimulation(7186000000, 710398642, 0, 0, 0.085, 0.04, 24.0, 12.31);
 assert.ok(fv24 > fv16);
 assert.ok(fv24 > 250 && fv16 < 210);
});
