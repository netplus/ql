'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../web/market-data.js');
function fixture(n){
 const sessions=[];for(let i=0;i<70;i++){const d=new Date(Date.UTC(2026,0,1+i));sessions.push(d.toISOString().slice(0,10));}
 // Synthetic calendar intentionally explicit, not an exchange-calendar fixture.
 const sources={},observations={};
 for(let i=0;i<n;i++)sources['synthetic-'+i]={provider:'SYNTHETIC ONLY',url:'https://www.chinaamc.com/fund/510330/index.shtml',recorded_at:'2026-10-01T00:00:00Z',published_at:null,mode:'web_text_transcription',raw_response_archived:false,evidence_sha256:null};
 for(let i=0;i<sessions.length;i++)observations[sessions[i]]={nav:'1.0000',shares:null,nav_source:'synthetic-'+(i%n),shares_source:null};
 return {schema:'ql.market-bundle/2',version:'synthetic-history',timezone:'Asia/Shanghai',audience:'private-review',auto_updated:false,observed_at:'2026-10-01T01:00:00Z',asof:sessions.at(-1),benchmark_code:'510330',calendar:{version:'synthetic-only',source_url:'https://www.sse.com.cn/disclosure/dealinstruc/closed/',sessions,coverage_start:sessions[0],coverage_end:sessions.at(-1)},sources,products:[{code:'510330',exchange:'SSE',name:'SYNTHETIC',label:'SYNTHETIC',group:'宽基',basis:'unadjusted_nav',currency:'CNY',observations}]};
}
test('more than 64 temporal evidence records support a 60-session window',()=>{const m=M.model(M.parse(JSON.stringify(fixture(70))));assert.equal(m.products[0].windows[m.asof]['60'].value,'0.000000');});
test('bounded expanded source registry',()=>{assert.equal(M.MAX_SOURCES,2048);assert.doesNotThrow(()=>M.parse(JSON.stringify(fixture(2048))));assert.throws(()=>M.parse(JSON.stringify(fixture(2049))));});
test('two MiB transport budget remains enforced before parsing',()=>assert.throws(()=>M.parse(' '.repeat(M.MAX_BYTES+1))));
