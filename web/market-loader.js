/* Bounded same-origin snapshot transport; local imports remain local. */
(function(root){
'use strict';
const API=typeof module!=='undefined'&&module.exports?require('./market-data.js'):root.QLMarketData;
const KEY='ql.market.tab.v2';
function need(ok,msg){if(!ok)throw new Error(msg);}
async function readBounded(response,limit){
 need(response.ok&&!response.redirected,'站点返回错误或跳转');
 need(/^application\/json(?:;|$)/i.test(response.headers.get('content-type')||''),'响应不是JSON');
 const len=response.headers.get('content-length');if(len!==null)need(/^\d+$/.test(len)&&Number(len)<=limit,'响应超过限制');
 const reader=response.body.getReader(),parts=[];let total=0;
 try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;need(total<=limit,'响应超过限制');parts.push(value);}}catch(e){await reader.cancel();throw e;}finally{reader.releaseLock();}
 const out=new Uint8Array(total);let pos=0;for(const p of parts){out.set(p,pos);pos+=p.length;}return out;
}
async function latest(base,fetcher=root.fetch.bind(root),cryptoAPI=root.crypto){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
 try{
  const options={credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal};
  const m=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await readBounded(await fetcher(new URL('market.manifest.json',base).href,options),8192)));
  need(m.schema==='ql.market-manifest/2','索引版本不支持');
  if(m.state==='unpublished')throw Error('本站市场数据尚未发布；自动采集仍未接通');
  need(m.state==='ready'&&/^[a-f0-9]{64}$/.test(m.sha256)&&m.file===`market.${m.sha256}.json`&&Number.isInteger(m.bytes)&&m.bytes>0&&m.bytes<=API.MAX_BYTES,'索引内容无效');
  const raw=await readBounded(await fetcher(new URL(m.file,base).href,options),m.bytes);
  need(raw.length===m.bytes&&cryptoAPI?.subtle,'响应长度不符或完整性检查不可用');
  const hash=Array.from(new Uint8Array(await cryptoAPI.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('');need(hash===m.sha256,'数据摘要不匹配，旧数据不变');
  const bundle=API.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));need(bundle.audience==='public-market'&&bundle.version===m.version&&bundle.asof===m.asof,'索引与数据版本不一致');
  return bundle;
 }finally{clearTimeout(timer);}
}
function start(launch){
 const $=s=>document.querySelector(s);let current=null,pending=null,mounted=false,busy=false;
 $('#asof').disabled=true;
 function ready(){root.QLMarketBoot?.ready();}
 const msg=(s,error=false)=>{const el=$('#market-message');el.textContent=s;el.dataset.error=String(error);};
 function mount(b){current=b;$('#ql-data').textContent=JSON.stringify(API.model(b));mounted=true;launch();
  $('#market-status').textContent=`${b.products.length}只产品 · 截至 ${b.asof} · 取证 ${b.observed_at} · 未接通定时采集`;$('#asof').disabled=false;ready();}
 function offer(b){pending=b;$('#market-confirm').textContent=`载入${b.products.length}只产品、${b.calendar.sessions.length}个日历观察日，截至${b.asof}。${current&&b.asof<current.asof?'注意：这是较旧的数据。':''}${mounted?'页面将刷新；先保存未提交的备注。':''}文件不会上传，正式资金仍未验收。`;$('#market-dialog').showModal();}
 async function remote(){if(busy)return;busy=true;$('#market-refresh').disabled=true;$('#market-open').disabled=true;try{const b=await latest(location.href);if(!mounted)mount(b);else offer(b);msg('已校验本站数据的版本和摘要；这不是数据源真实性认证。');}catch(e){if(!mounted){$('#market-status').textContent='页面已就绪 · 市场数据尚未接通';$('#notice-text').textContent='市场数据未载入，不生成研究判断。';$('#app').innerHTML='<section class="card"><div class="cardbody"><h1>页面已就绪，市场数据待接通。</h1><p>可载入本地v2数据包查看图表。不会把缺失数据填成零，也不会伪造今日排名。</p></div></section>';$('#app').setAttribute('aria-busy','false');}msg('未取得新数据：'+e.message+'。已有数据与备注不变。',true);}finally{busy=false;$('#market-refresh').disabled=false;$('#market-open').disabled=false;ready();}}
 $('#market-file').onchange=async e=>{const file=e.target.files?.[0];try{if(file){need(file.size<=API.MAX_BYTES,'文件超过2MB');offer(API.parse(await file.text()));}}catch(err){msg('导入失败：'+err.message+'。已有数据不变。',true);}finally{e.target.value='';}};
 $('#market-open').onclick=()=>$('#market-file').click();$('#market-cancel').onclick=()=>$('#market-dialog').close();$('#market-dialog').addEventListener('close',()=>pending=null);
 $('#market-accept').onclick=()=>{if(!pending)return;const b=pending;let saved=true;try{sessionStorage.setItem(KEY,JSON.stringify(b));}catch{saved=false;}
  if(mounted){if(!saved){msg('标签页存储不可用，原数据保留；可另开单文件预览。',true);$('#market-dialog').close();return;}location.reload();return;}
  $('#market-dialog').close();mount(b);msg(saved?'数据仅存于当前标签页。':'数据仅存于内存；刷新后需重新载入。');};
 let embedded=null;try{embedded=JSON.parse($('#market-data').textContent);if(embedded)embedded=API.validate(embedded);}catch(e){msg('内置数据无效：'+e.message,true);}
 let cached=null;try{const raw=sessionStorage.getItem(KEY)||sessionStorage.getItem('ql.dataset.tab.v1');if(raw)cached=API.parse(raw);}catch{msg('浏览器限制存储或旧数据无效；本次快照仍可查看，私人记录不会被删除。',true);}
 if(cached||embedded)mount(cached||embedded);
 const site=document.documentElement.dataset.transport==='same-origin';$('#market-refresh').hidden=!site;$('#market-refresh').onclick=remote;
 if(site&&!mounted)remote();else if(!mounted){$('#market-status').textContent='页面已就绪 · 等待载入本地数据';$('#app').textContent='载入本地v2数据包开始研究。';ready();$('#app').setAttribute('aria-busy','false');}
 // Do not silently overwrite cached data or unsaved notes on a failed/old remote update.
 if(cached)msg('当前为本标签页上次载入的数据；可手动检查本站更新。');
}
const exports=Object.freeze({latest,readBounded,start});if(typeof module!=='undefined'&&module.exports)module.exports=exports;else root.QLMarketLoader=exports;
})(typeof globalThis!=='undefined'?globalThis:this);
