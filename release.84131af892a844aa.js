/* Local review-bundle loader. No fetching, upload, authentication or trading. */
(() => {
'use strict';
const LIMIT=2*1024*1024, KEY='ql.dataset.tab.v1', SCALE=100000000n;
const LABELS={'159995':'半导体芯片','515030':'新能源汽车','510330':'沪深300','512010':'沪深300医药','159819':'人工智能','510030':'180价值'};
const GROUPS={'159995':'行业相关','515030':'主题','510330':'宽基','512010':'行业相关','159819':'主题','510030':'风格'};
const HOSTS=new Set(['www.chinaamc.com','www.efunds.com.cn','www.fsfund.com','www.sse.com.cn']);
const $=s=>document.querySelector(s);
function fail(message){throw new Error(message);}
function text(x,n=160){if(typeof x!=='string'||!x.length||x.length>n||/[<>"'&\u0000-\u001f]/.test(x))fail('文本字段不安全');return x;}
function date(x){if(typeof x!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(x)||!Number.isFinite(Date.parse(x+'T00:00:00Z'))||new Date(x+'T00:00:00Z').toISOString().slice(0,10)!==x)fail('日期无效');return x;}
function fixed(x,positive){
 if(typeof x!=='string'||!/^\d{1,12}(?:\.\d{1,8})?$/.test(x))fail('数值必须是有限十进制字符串');
 const [a,b='']=x.split('.'),n=BigInt(a)*SCALE+BigInt(b.padEnd(8,'0'));
 if(positive&&n<=0n)fail('净值必须大于零');return n;
}
function rounded(n,d,p=6){
 if(d<=0n)fail('分母无效');const negative=n<0n;if(negative)n=-n;
 const scale=10n**BigInt(p),q=n*scale/d,r=n*scale%d,z=q+(r*2n>=d?1n:0n);
 const s=z.toString().padStart(p+1,'0');return (negative?'-':'')+(p?s.slice(0,-p)+'.'+s.slice(-p):s);
}
function equal(a,b){return JSON.stringify(a)===JSON.stringify(b);}
function cleanPayload(p){
 if(!p||p.schema!=='ql.page/1'||p.timezone!=='Asia/Shanghai'||p.public_export_allowed!==false||p.auto_updated!==false||p.report_status!=='historical_sample'||p.accepted_flow_cny!==null)fail('不是受支持的私人评审数据包');
 // v1 intentionally remains the six-product/six-observation P0 preview contract.
 if(!Array.isArray(p.dates)||p.dates.length!==6||!Array.isArray(p.products)||p.products.length!==6)fail('本版仅接受六产品、六观察日评审包');
 const days=p.dates.map(date);if(new Set(days).size!==6||!equal([...days].sort(),days)||p.asof!==days.at(-1))fail('日期顺序、重复或截止日错误');
 if(!/^[0-9a-f]{40}$/.test(p.evidence_commit)||!/^[-a-zA-Z0-9._/]{1,80}$/.test(p.version))fail('版本字段错误');
 if(!p.sources||Array.isArray(p.sources)||Object.keys(p.sources).length>12)fail('来源登记错误');
 const sources=Object.create(null);
 for(const [id,s] of Object.entries(p.sources)){
  if(!/^[a-z0-9]+(?:-[a-z0-9]+)+$/.test(id)||!s)fail('来源标识错误');
  const u=new URL(s.url);if(u.protocol!=='https:'||!HOSTS.has(u.hostname)||u.port||u.username||u.password||u.hash||s.url.length>500)fail('来源链接不在允许范围');
  if(typeof s.recorded_at!=='string'||!/(?:Z|[+-]\d{2}:\d{2})$/.test(s.recorded_at)||!Number.isFinite(Date.parse(s.recorded_at))||s.published_at!==null||s.raw_response_archived!==false)fail('取证口径不符合评审包');
  sources[id]={provider:text(s.provider),url:u.href,recorded_at:s.recorded_at,published_at:null,raw_response_archived:false};
 }
 const codes=p.products.map(x=>x?.code);if(new Set(codes).size!==6||codes.some(c=>!Object.hasOwn(LABELS,c)))fail('产品代码无效或重复');
 const products=p.products.map(x=>{
  if(x.label!==LABELS[x.code]||x.group!==GROUPS[x.code])fail('产品分类与预览范围不符');
  if(!Array.isArray(x.nav)||!Array.isArray(x.shares_wan)||x.nav.length!==6||x.shares_wan.length!==6)fail('序列长度错误');
  x.nav.forEach(v=>{if(v!==null)fixed(v,true);});x.shares_wan.forEach(v=>{if(v!==null)fixed(v,false);});
  if(x.code!=='510030'&&x.shares_wan.some(v=>v!==null))fail('此预览只准入510030份额字段');
  if(!Array.isArray(x.source_ids)||!x.source_ids.length||x.source_ids.some(s=>!Object.hasOwn(sources,s)))fail('产品来源未登记');
  return {code:x.code,label:x.label,name:text(x.name),group:x.group,source_ids:[...new Set(x.source_ids)],nav:[...x.nav],shares_wan:[...x.shares_wan],windows:{},daily:[]};
 });
 const b=products.find(x=>x.code==='510330');
 for(const x of products){
  const original=p.products.find(o=>o.code===x.code);
  for(let i=0;i<days.length;i++){
   const wm={};
   for(const h of [1,5,20,60]){
    let m={value:null,relative_pp:null,rebased:[],start:null,reason:'insufficient_history',display:null,relative_display:null};
    if(i>=h){
     const v=x.nav.slice(i-h,i+1),bv=b.nav.slice(i-h,i+1);
     if([...v,...bv].some(z=>z===null))m.reason='missing_trading_date';
     else{
      const start=fixed(v[0],true),end=fixed(v.at(-1),true),bs=fixed(bv[0],true),be=fixed(bv.at(-1),true);
      const n=(end-start)*100n,rn=(end*bs-be*start)*100n,rd=start*bs;
      m={value:rounded(n,start),relative_pp:rounded(rn,rd),rebased:v.map(z=>rounded(fixed(z,true)*100n,start)),start:i-h,reason:null,display:rounded(n,start,2),relative_display:rounded(rn,rd,2)};
     }
    }
    const supplied=original.windows?.[days[i]]?.[String(h)];
    if(!supplied||Object.keys(m).some(k=>!equal(m[k],supplied[k])))fail('净值指标与原始序列不一致');
    wm[String(h)]=m;
   }
   x.windows[days[i]]=wm;x.daily.push(wm['1'].value);
  }
  if(!equal(x.daily,original.daily))fail('单日序列与复算不一致');
 }
 const sh=products.find(x=>x.code==='510030'),flows={};
 for(let i=0;i<days.length;i++){
  flows[days[i]]={};
  for(const h of [1,5,20,60]){
   let f=null;
   if(i>=h){let n=0n,valid=true;for(let j=i-h+1;j<=i;j++){
    if(sh.shares_wan[j]===null||sh.shares_wan[j-1]===null||sh.nav[j]===null){valid=false;break;}
    n+=(fixed(sh.shares_wan[j],false)-fixed(sh.shares_wan[j-1],false))*fixed(sh.nav[j],true);
   }if(valid)f=rounded(n,SCALE*SCALE,2);}
   if(p.flow_windows?.[days[i]]?.[String(h)]!==f)fail('条件申赎与原始字段不一致');flows[days[i]][String(h)]=f;
  }
 }
 // Rebuild an allowlisted object: unknown/private fields and supplied markup never enter the renderer.
 return {schema:'ql.page/1',version:p.version,evidence_commit:p.evidence_commit,timezone:'Asia/Shanghai',dates:days,asof:p.asof,report_status:'historical_sample',public_export_allowed:false,auto_updated:false,sources,products,flow_windows:flows,share_daily:[],accepted_flow_cny:null,scope:'六只ETF验证观察池；不是全A股或正式行业横截面。',warnings:[]};
}
function parseBundle(raw){if(typeof raw!=='string'||new TextEncoder().encode(raw).length>LIMIT)fail('文件超过2MB');const b=JSON.parse(raw);if(!b||b.schema!=='ql.review-bundle/1'||Object.keys(b).some(k=>!['schema','payload'].includes(k)))fail('文件不是ql市场数据包；自选备注请在自选页导入');return cleanPayload(b.payload);}
function shanghaiToday(){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const v=k=>parts.find(p=>p.type===k).value;return `${v('year')}-${v('month')}-${v('day')}`;}
let mounted=false,current=null,pending=null,launch,embedded=null;
function message(s,error=false){const el=$('#bundle-message');el.textContent=s;el.dataset.error=String(error);}
function freshness(){const el=$('#dataset-status');if(!el)return;el.textContent=current?`历史样例 · 截至 ${current.asof} · 上海日期 ${shanghaiToday()} · 无自动采集`:'页面已就绪 · 未载入市场数据';}
function mount(p){current=p;$('#ql-data').textContent=JSON.stringify(p);mounted=true;launch();freshness();$('#bundle-clear').disabled=false;}
function blank(){
 $('#asof').disabled=true;$('#crumb').textContent='载入数据';$('#notice-text').textContent='此发布页不包含市场数值、持仓或备注。导入文件只在本地浏览器处理，不上传。';
 $('#app').innerHTML='<section class="card release-welcome"><div class="eyebrow">QL / YOUR RESEARCH WORKSPACE</div><h1>页面与数据，分开管理。</h1><p class="sub">公开页面保留交互能力；你的评审数据留在本机。载入经校验的市场数据包，开始查看图表、比较产品和记录观察。</p><button class="primary" id="welcome-import">载入本地数据包 ↑</button><div class="healthgrid"><div class="healthitem"><h3>不会显示虚构行情</h3><p>未载入数据时不画走势、不填排名，不把缺失记为零。</p></div><div class="healthitem"><h3>不会上传你的文件</h3><p>没有数据请求、追踪脚本或账户登录。文件不进入公开发布目录。</p></div><div class="healthitem"><h3>每个数字都有边界</h3><p>显示原始日期与来源，重新核对计算。格式校验不等于源站真实性认证。</p></div></div></section>';
 $('#app').setAttribute('aria-busy','false');$('#welcome-import').onclick=()=>$('#bundle-file').click();
 document.querySelectorAll('[data-route]').forEach(a=>a.addEventListener('click',e=>{if(!mounted){e.preventDefault();message('先载入本地市场数据包，再进入研究视图。');}}));
 freshness();
}
function start(startApp){
 launch=startApp;let error='';
 try{const p=JSON.parse($('#ql-data').textContent);if(p!==null)embedded=cleanPayload(p);}catch(e){error='内置数据未通过校验：'+e.message;}
 try{const saved=sessionStorage.getItem(KEY);if(saved)current=parseBundle(saved);}catch{error='本标签页未能恢复数据；不会用零值代替。';}
 $('#bundle-open').onclick=()=>$('#bundle-file').click();
 $('#bundle-file').onchange=async e=>{
  const file=e.target.files?.[0];if(!file)return;
  try{if(file.size>LIMIT)fail('文件超过2MB');pending=parseBundle(await file.text());
   $('#bundle-confirm-text').textContent=`将载入截至 ${pending.asof} 的六产品历史评审包。${current&&pending.asof<current.asof?'注意：它比当前数据更旧，属于历史回看。':''}正式资金指标仍停用；文件不会上传。${mounted?'已加载页面将刷新，请先保存或导出尚未保存的备注。':''}`;
   $('#bundle-dialog').showModal();
  }catch(err){pending=null;message('导入失败：'+err.message+'。现有数据未改变。',true);}finally{e.target.value='';}
 };
 $('#bundle-cancel').onclick=()=>$('#bundle-dialog').close();
 $('#bundle-accept').onclick=()=>{
  if(!pending)return;const p=pending,raw=JSON.stringify({schema:'ql.review-bundle/1',payload:p});
  // Re-add verified derived fields only. Stored text is still a private review bundle.
  if(mounted){
   try{sessionStorage.setItem(KEY,raw);}catch{message('浏览器不允许标签页存储，无法安全刷新替换；原数据保持不变。',true);$('#bundle-dialog').close();return;}
   $('#bundle-dialog').close();message('已校验并暂存于本标签页，即将刷新；未上传。');location.reload();
  }else{
   let saved=true;try{sessionStorage.setItem(KEY,raw);}catch{saved=false;}
   $('#bundle-dialog').close();$('#asof').disabled=false;mount(p);message(saved?'已在本地载入；刷新可在当前标签页恢复，关闭标签页后需重新导入。':'已载入内存；存储不可用，刷新或关闭后需重新导入。');
  }
 };
 $('#bundle-dialog').addEventListener('close',()=>pending=null);
 $('#bundle-clear').onclick=()=>{
  if(!confirm('移除当前标签页的市场数据并刷新？不会删除自选和已保存备注。私人单文件预览会恢复其内置样例。'))return;
  try{sessionStorage.removeItem(KEY);}catch{message('未能移除标签页数据，页面未刷新。',true);return;}location.reload();
 };
 if(current||embedded)mount(current||embedded);else blank();if(error)message(error,true);
 setInterval(freshness,60000);
}
window.QLRelease=Object.freeze({start,parseBundle,cleanPayload,rounded});
})();
