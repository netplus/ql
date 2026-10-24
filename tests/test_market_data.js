/* Synthetic mechanics fixtures only. They are never published as market records. */
const test=require('node:test'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const M=require('../web/market-data.js'),L=require('../web/market-loader.js');
function fixture(n=2,count=12){
 const days=[];let d=new Date('2026-01-01T00:00:00Z');while(days.length<count){if(d.getUTCDay()>0&&d.getUTCDay()<6)days.push(d.toISOString().slice(0,10));d.setUTCDate(d.getUTCDate()+1);}
 return {schema:'ql.market-bundle/2',version:'synthetic-test-only',timezone:'Asia/Shanghai',audience:'private-review',auto_updated:false,observed_at:'2099-01-01T00:00:00Z',asof:days.at(-1),benchmark_code:'000001',calendar:{version:'SYNTHETIC-not-official',source_url:'https://www.sse.com.cn/disclosure/dealinstruc/closed/',coverage_start:days[0],coverage_end:days.at(-1),sessions:days},sources:{'synthetic-source':{provider:'SYNTHETIC test data',url:'https://www.chinaamc.com/fund/510330/index.shtml',recorded_at:'2098-01-01T00:00:00Z',published_at:null,mode:'web_text_transcription',raw_response_archived:false,evidence_sha256:null}},products:Array.from({length:n},(_,p)=>({code:String(p+1).padStart(6,'0'),exchange:'SSE',label:'测试'+p,name:'SYNTHETIC-'+p,group:'宽基',basis:'unadjusted_nav',currency:'CNY',observations:Object.fromEntries(days.map((d,i)=>[d,{nav:((100+i+p)/100).toFixed(2),shares:String(1000000+i*500000),nav_source:'synthetic-source',shares_source:'synthetic-source'}]))}))};
}
test('1, 3, 7 and 10 products, multiple dates; not six-by-six',()=>{for(const n of [1,3,7,10])assert.equal(M.model(fixture(n,12)).products.length,n);});
test('append an observation date without code changes',()=>{assert.equal(M.model(fixture(3,13)).dates.length,13);});
test('20 and 60 day windows work with sufficient synthetic history',()=>{const d=M.model(fixture(2,61));assert.notEqual(d.products[0].windows[d.asof]['60'].value,null);assert.equal(d.products[0].windows[d.asof]['60'].value,'60.000000');});
test('actual short history cannot produce 20d',()=>{const d=M.model(fixture());assert.equal(d.products[0].windows[d.asof]['20'].value,null);});
test('a missing middle date is not bridged',()=>{let b=fixture(2,6);delete b.products[0].observations[b.calendar.sessions[2]];let d=M.model(b);assert.equal(d.products[0].windows[d.asof]['5'].value,null);});
test('missing benchmark does not suppress independent return',()=>{let b=fixture(2,6);delete b.products[0].observations[b.calendar.sessions[2]];let d=M.model(b),m=d.products[1].windows[d.asof]['5'];assert.notEqual(m.value,null);assert.equal(m.relative_pp,null);});
test('base share units and CNY ten-thousands display',()=>{let d=M.model(fixture(1,2));assert.equal(d.products[0].shares_wan[0],'100.00000000');assert.equal(d.products[0].flow_windows[d.asof]['1'],'50.50');});
test('missing shares do not carry forward',()=>{let b=fixture(1,6),o=b.products[0].observations[b.asof];o.shares=null;let d=M.model(b);assert.equal(d.products[0].flow_windows[d.asof]['5'],null);});
test('zero flow differs from missing flow',()=>{let b=fixture(1,6);Object.values(b.products[0].observations).forEach(o=>o.shares='0');let d=M.model(b);assert.equal(d.products[0].flow_windows[d.asof]['5'],'0.00');assert.equal(d.accepted_flow_cny,null);});
test('duplicate code rejected',()=>{let b=fixture();b.products[1].code=b.products[0].code;assert.throws(()=>M.model(b));});
test('missing benchmark rejected',()=>{let b=fixture();b.benchmark_code='999999';assert.throws(()=>M.model(b));});
test('invalid and duplicate calendar dates rejected',()=>{for(const value of ['2026-02-30','2026-01-01']){let b=fixture();b.calendar.sessions[1]=value;assert.throws(()=>M.model(b));}});
test('date outside independent calendar rejected',()=>{let b=fixture();b.products[0].observations['2026-12-31']={};assert.throws(()=>M.model(b));});
test('negative, float, NaN, Infinity and zero NAV rejected',()=>{for(const value of ['-1','NaN','Infinity','0',1.2]){let b=fixture();b.products[0].observations[b.asof].nav=value;assert.throws(()=>M.model(b));}});
test('mixed basis or currency rejected',()=>{for(const [key,value] of [['basis','close'],['currency','USD']]){let b=fixture();b.products[0][key]=value;assert.throws(()=>M.model(b));}});
test('unregistered source rejected',()=>{let b=fixture();b.products[0].observations[b.asof].nav_source='missing';assert.throws(()=>M.model(b));});
test('malicious text and source links rejected',()=>{let b=fixture();b.products[0].label='<img>';assert.throws(()=>M.model(b));b=fixture();b.sources['synthetic-source'].url='https://example.com/';assert.throws(()=>M.model(b));});
test('future source timestamp rejected',()=>{let b=fixture();b.sources['synthetic-source'].recorded_at='2099-01-02T00:00:00Z';assert.throws(()=>M.model(b));});
test('unknown private fields and supplied calculated flow are not rendered',()=>{let b=fixture();b.holdings='PRIVATE';b.accepted_flow_cny='1000';b.products[0].cost='PRIVATE';assert(!JSON.stringify(M.model(b)).includes('PRIVATE'));assert.equal(M.model(b).accepted_flow_cny,null);});
test('all fields can be missing without inventing values',()=>{let b=fixture();b.products[0].observations={};let d=M.model(b);assert.equal(d.products[0].nav[0],null);});
test('numeric rounding avoids negative zero',()=>{assert.equal(M.round(-1n,1000000000n,2),'0.00');assert.equal(M.round(49996n,10000000n,2),'0.00');});
test('budget enforced before JSON parse',()=>assert.throws(()=>M.parse(' '.repeat(M.MAX_BYTES+1))));
test('more than 64 products rejected',()=>assert.throws(()=>M.model(fixture(65,2))));
test('model deterministic',()=>assert.deepEqual(M.model(fixture()),M.model(fixture())));
async function setup(b=fixture()){
 b.audience='public-market';const raw=Buffer.from(JSON.stringify(b));const sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');
 const manifest={schema:'ql.market-manifest/2',state:'ready',file:`market.${sha}.json`,sha256:sha,bytes:raw.length,version:b.version,asof:b.asof};return {b,raw,manifest};
}
function responder(m,raw,overrides={}){return async(u,opts)=>{assert.equal(opts.credentials,'omit');assert.equal(opts.redirect,'error');return new Response(u.endsWith('market.manifest.json')?JSON.stringify(m):raw,{headers:{'Content-Type':'application/json',...overrides}});};}
test('same-origin manifest data and digest verified',async()=>{const {b,raw,manifest}=await setup();assert.deepEqual(await L.latest('https://site.test/ql/',responder(manifest,raw),webcrypto),M.validate(b));});
test('tampered dataset rejected',async()=>{const {raw,manifest}=await setup();const bad=Buffer.from(raw);bad[50]^=1;await assert.rejects(L.latest('https://site.test/ql/',responder(manifest,bad),webcrypto));});
test('traversal or remote data path rejected',async()=>{const {raw,manifest}=await setup();manifest.file='../private.json';await assert.rejects(L.latest('https://site.test/ql/',responder(manifest,raw),webcrypto));});
test('HTML instead of JSON rejected',async()=>{const {raw,manifest}=await setup();await assert.rejects(L.latest('https://site.test/ql/',responder(manifest,raw,{'Content-Type':'text/html'}),webcrypto));});
test('unpublished is not a successful empty dataset',async()=>{const {raw}=await setup();await assert.rejects(L.latest('https://site.test/ql/',responder({schema:'ql.market-manifest/2',state:'unpublished'},raw),webcrypto));});
test('manifest asof mismatch rejected',async()=>{const {raw,manifest}=await setup();manifest.asof='2025-01-01';await assert.rejects(L.latest('https://site.test/ql/',responder(manifest,raw),webcrypto));});
test('private review data is never accepted as public feed',async()=>{const b=fixture(),{raw,manifest}=await setup();const privateRaw=Buffer.from(JSON.stringify(b));manifest.sha256=Buffer.from(await webcrypto.subtle.digest('SHA-256',privateRaw)).toString('hex');manifest.file=`market.${manifest.sha256}.json`;manifest.bytes=privateRaw.length;await assert.rejects(L.latest('https://site.test/ql/',responder(manifest,privateRaw),webcrypto));});
test('network failure is explicit',async()=>{await assert.rejects(L.latest('https://site.test/ql/',async()=>{throw Error('network failure');},webcrypto));});
module.exports={fixture};
