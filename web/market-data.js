/* ql.market-bundle/2. Raw decimal observations -> bounded, deterministic view model.
 * Neither schema validation nor a URL authenticates a source. No network or trading.
 */
(function(root){
'use strict';
const S=100000000n, MAX_BYTES=2*1024*1024, MAX_SOURCES=2048;
const HOSTS=new Set(['www.chinaamc.com','www.efunds.com.cn','www.fsfund.com','www.sse.com.cn','www.szse.cn','fund.szse.cn']);
const GROUPS=new Set(['行业相关','主题','宽基','风格']);
const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
function need(ok,msg){if(!ok)throw new Error(msg);}
function object(o){return o!==null&&typeof o==='object'&&!Array.isArray(o);}
function text(v,n=160){need(typeof v==='string'&&v.length>0&&v.length<=n&&!/[<>"'&\u0000-\u001f]/.test(v),'文本字段无效');return v;}
function day(v){need(typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v),'日期格式无效');const d=new Date(v+'T00:00:00Z');need(Number.isFinite(+d)&&d.toISOString().slice(0,10)===v,'日期不存在');return v;}
function instant(v){need(typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v)),'获取时刻必须包含时区');day(v.slice(0,10));return v;}
function url(v){const u=new URL(v);need(u.protocol==='https:'&&HOSTS.has(u.hostname)&&!u.port&&!u.username&&!u.password&&!u.hash&&u.href.length<600,'来源网址不在已评审范围');return u.href;}
function fixed(v,positive=false){need(typeof v==='string'&&/^\d{1,14}(?:\.\d{1,8})?$/.test(v),'数值须为有限非负十进制字符串');const [a,b='']=v.split('.');const n=BigInt(a)*S+BigInt(b.padEnd(8,'0'));need(!positive||n>0n,'净值必须大于零');return n;}
function round(n,d,p=6){need(d>0n,'分母无效');const neg=n<0n;if(neg)n=-n;const k=10n**BigInt(p),q=n*k/d,r=n*k%d,z=q+(r*2n>=d?1n:0n),s=z.toString().padStart(p+1,'0');return (neg&&z!==0n?'-':'')+(p?s.slice(0,-p)+'.'+s.slice(-p):s);}
function parse(raw){need(typeof raw==='string'&&new TextEncoder().encode(raw).length<=MAX_BYTES,'数据包超过2MB');const b=JSON.parse(raw);return validate(b?.schema==='ql.review-bundle/1'?legacy(b):b);}
function legacy(b){
 const p=b.payload;need(object(p)&&p.schema==='ql.page/1'&&p.public_export_allowed===false&&p.auto_updated===false&&p.accepted_flow_cny===null,'旧版样例声明不符');
 need(Array.isArray(p.products)&&p.products.length===6&&Array.isArray(p.dates)&&p.dates.length===6,'旧版仅迁移已知六产品评审协议');
 const codes=['159995','515030','510330','512010','159819','510030'];need(p.products.every(x=>codes.includes(x.code))&&new Set(p.products.map(x=>x.code)).size===6,'旧版代码范围不符');
 const sources=Object.create(null);need(object(p.sources),'旧版来源缺失');
 for(const [id,s] of Object.entries(p.sources))sources[id]={...s,mode:'prior_repository_fixture',raw_response_archived:false,evidence_sha256:null};
 const observed=Object.values(sources).map(s=>s.recorded_at).sort((a,b)=>Date.parse(a)-Date.parse(b)).at(-1);
 const products=p.products.map(x=>{need(Array.isArray(x.nav)&&x.nav.length===6&&Array.isArray(x.shares_wan)&&x.shares_wan.length===6&&Array.isArray(x.source_ids),'旧版序列无效');
  const navSource=x.source_ids.find(id=>id==='huabao-nav'||id.endsWith('-'+x.code));need(navSource&&own(sources,navSource),'旧版净值来源缺失');
  const obs=Object.create(null);p.dates.forEach((d,i)=>{const sh=x.shares_wan[i];const sid=i===5?'sse-all-shares':'sse-product-shares';need(sh===null||x.code==='510030','旧版份额范围不符');obs[d]={nav:x.nav[i],shares:sh===null?null:round(fixed(sh)*10000n,S,8),nav_source:x.nav[i]===null?null:navSource,shares_source:sh===null?null:sid};});
  return {code:x.code,exchange:x.code.startsWith('159')?'SZSE':'SSE',label:x.label,name:x.name,group:x.group,basis:'unadjusted_nav',currency:'CNY',observations:obs};});
 return {schema:'ql.market-bundle/2',version:'legacy-raw-migration/1',timezone:'Asia/Shanghai',audience:'private-review',auto_updated:false,observed_at:observed,asof:p.asof,benchmark_code:'510330',calendar:{version:'legacy-reviewed-six-days',source_url:'https://www.sse.com.cn/disclosure/dealinstruc/closed/',coverage_start:p.dates[0],coverage_end:p.asof,sessions:p.dates},sources,products};
}
function validate(b){
 need(object(b)&&b.schema==='ql.market-bundle/2'&&b.timezone==='Asia/Shanghai','不支持的数据协议');
 need(['private-review','public-market'].includes(b.audience),'数据用途无效');
 need(b.auto_updated===false,'本阶段不接受未经验收的自动更新声明');
 const observed=instant(b.observed_at),asof=day(b.asof),version=text(b.version,80);
 need(asof<=new Date(Date.parse(observed)+8*3600000).toISOString().slice(0,10),'数据日期晚于获取日期');
 need(object(b.calendar)&&Array.isArray(b.calendar.sessions),'缺少独立交易日历');
 const days=b.calendar.sessions.map(day);
 need(days.length>=1&&days.length<=520&&new Set(days).size===days.length&&days.every((d,i)=>!i||d>days[i-1]),'日历须有序且不重复');
 need(days.at(-1)===asof&&b.calendar.coverage_start===days[0]&&b.calendar.coverage_end===asof,'日历范围与数据截止日不一致');
 const calendar={version:text(b.calendar.version,80),source_url:url(b.calendar.source_url),sessions:days,coverage_start:days[0],coverage_end:asof};
 need(object(b.sources)&&Object.keys(b.sources).length>0&&Object.keys(b.sources).length<=MAX_SOURCES,'来源登记数量无效');
 const sources=Object.create(null);
 for(const [id,s] of Object.entries(b.sources)){
  need(/^[a-z][a-z0-9-]{1,79}$/.test(id)&&object(s),'来源标识无效');
  const at=instant(s.recorded_at);need(Date.parse(at)<=Date.parse(observed),'来源获取时间晚于数据包生成时间');
  need(['web_text_transcription','http_response','prior_repository_fixture'].includes(s.mode),'取证方式无效');
  need(typeof s.raw_response_archived==='boolean'&&(s.mode==='http_response'||!s.raw_response_archived),'原始响应归档声明不一致');
  need(s.published_at===null||Date.parse(instant(s.published_at))<=Date.parse(at),'披露时刻晚于获取时刻');
  need(s.evidence_sha256===null||/^[a-f0-9]{64}$/.test(s.evidence_sha256),'证据摘要无效');
  sources[id]={provider:text(s.provider),url:url(s.url),recorded_at:at,published_at:s.published_at,mode:s.mode,raw_response_archived:s.raw_response_archived,evidence_sha256:s.evidence_sha256};
 }
 need(Array.isArray(b.products)&&b.products.length>=1&&b.products.length<=64&&b.products.length*days.length<=16384,'产品或日期数量超出预算');
 const codes=new Set(),dateSet=new Set(days);
 const products=b.products.map(p=>{
  need(object(p)&&/^\d{6}$/.test(p.code)&&!codes.has(p.code),'产品代码无效或重复');codes.add(p.code);
  need(['SSE','SZSE'].includes(p.exchange)&&GROUPS.has(p.group),'市场或分组无效');
  need(p.basis==='unadjusted_nav'&&p.currency==='CNY','不支持混用币种或收益口径');
  need(object(p.observations)&&Object.keys(p.observations).length<=days.length,'观察记录无效');
  const observations=Object.create(null);
  for(const [d,o] of Object.entries(p.observations)){
   need(dateSet.has(d)&&object(o),'记录不在交易日历中');
   const out={nav:null,shares:null,nav_source:null,shares_source:null};
   for(const f of ['nav','shares']){
    need(o[f]===null||typeof o[f]==='string','缺失字段必须显式为null');
    if(o[f]!==null){fixed(o[f],f==='nav');need(own(sources,o[f+'_source']),'字段来源未登记');out[f]=o[f];out[f+'_source']=o[f+'_source'];}
   }
   observations[d]=out;
  }
  return {code:p.code,exchange:p.exchange,label:text(p.label,50),name:text(p.name),group:p.group,basis:p.basis,currency:p.currency,observations};
 });
 need(codes.has(b.benchmark_code),'参照产品必须在观察池内');
 return {schema:b.schema,version,timezone:b.timezone,audience:b.audience,auto_updated:false,observed_at:observed,asof,calendar,benchmark_code:b.benchmark_code,sources,products};
}
function model(input){
 const b=validate(input),days=b.calendar.sessions;
 const ps=b.products.map(p=>({...p,nav:days.map(d=>p.observations[d]?.nav??null),shares_wan:days.map(d=>p.observations[d]?.shares==null?null:round(fixed(p.observations[d].shares),S*10000n,8)),source_ids:[...new Set(Object.values(p.observations).flatMap(o=>[o.nav_source,o.shares_source]).filter(Boolean))],windows:{},flow_windows:{},daily:[]}));
 const benchmark=ps.find(p=>p.code===b.benchmark_code);
 for(const p of ps){
  for(let i=0;i<days.length;i++){
   p.windows[days[i]]={};p.flow_windows[days[i]]={};
   for(const h of [1,5,20,60]){
    const m={value:null,relative_pp:null,rebased:[],start:null,reason:'insufficient_history',relative_reason:'insufficient_history',display:null,relative_display:null};
    let flow=null;
    if(i>=h){
     const v=p.nav.slice(i-h,i+1),bv=benchmark.nav.slice(i-h,i+1);m.reason='missing_trading_date';
     if(v.every(x=>x!==null)){
      const st=fixed(v[0],true),en=fixed(v.at(-1),true),n=(en-st)*100n;
      Object.assign(m,{value:round(n,st),display:round(n,st,2),rebased:v.map(x=>round(fixed(x,true)*100n,st)),start:i-h,reason:null,relative_reason:'benchmark_missing'});
      if(bv.every(x=>x!==null)){
       const bs=fixed(bv[0],true),be=fixed(bv.at(-1),true),rn=(en*bs-be*st)*100n,rd=st*bs;
       Object.assign(m,{relative_pp:round(rn,rd),relative_display:round(rn,rd,2),relative_reason:null});
      }
     }
     let amount=0n,ok=true;
     for(let j=i-h+1;j<=i;j++){
      const a=p.observations[days[j-1]],z=p.observations[days[j]];
      if(!a||!z||a.shares===null||z.shares===null||z.nav===null){ok=false;break;}
      amount+=(fixed(z.shares)-fixed(a.shares))*fixed(z.nav,true);
     }
     if(ok)flow=round(amount,S*S*10000n,2); // display CNY ten-thousands, never admitted institutional flow
    }
    p.windows[days[i]][String(h)]=m;p.flow_windows[days[i]][String(h)]=flow;
   }
   p.daily.push(p.windows[days[i]]['1'].value);
  }
 }
 return {schema:'ql.market-view/2',version:b.version,evidence_commit:'字段级来源与取证时间见数据方法',timezone:b.timezone,dates:days,asof:b.asof,observed_at:b.observed_at,report_status:'review_snapshot',public_export_allowed:false,auto_updated:false,benchmark_code:b.benchmark_code,sources:b.sources,products:ps,accepted_flow_cny:null,scope:`${ps.length}只ETF观察池；不是全A股或正式行业横截面。`,warnings:[]};
}
const api=Object.freeze({parse,validate,model,round,MAX_BYTES,MAX_SOURCES});
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.QLMarketData=api;
})(typeof globalThis!=='undefined'?globalThis:this);
