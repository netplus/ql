/* Generic ETF observation renderer. Receives only the validated market-view/2 model. */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const app = $('#app');
let D;
try {
 D=JSON.parse($('#ql-data').textContent);
 if(D.schema!=='ql.market-view/2'||!Array.isArray(D.products)||D.public_export_allowed!==false) throw Error('schema');
} catch {
 app.innerHTML='<div class="empty"><h3>页面数据未能载入</h3><p>内置数据缺失或版本不兼容。请重新取得完整页面，不会用零值替代失败数据。</p></div>';
 app.setAttribute('aria-busy','false'); $('#notice-text').textContent='加载失败 · 未生成研究判断'; return;
}
const titles={overview:'观察概览',compare:'方向比较',detail:'产品详情',watch:'自选复盘',methods:'数据方法'};
const palette=['#24888b','#d19445','#63758f','#8971aa','#cf7270','#688e52','#496aa5','#a4643e','#83624b'];
const byCode=Object.assign(Object.create(null),Object.fromEntries(D.products.map(p=>[p.code,p])));
const state={route:'overview',date:D.asof,h:5,code:D.benchmark_code,group:'全部',query:'',sort:'desc',point:D.dates.length-1,flow:false,visible:new Set(D.products.map(p=>p.code))};
const drafts={};
const KEY='ql.personal.v1'; let storageOK=true,personal={schema:'ql.personal/1',favorites:[],notes:{}};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,n=2)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:n,maximumFractionDigits:n});
const signed=v=>v==null?'—':(Number(v)>0?'+':'')+v;
const cls=v=>v==null?'':Number(v)>0?'up':Number(v)<0?'down':'';
const idx=()=>D.dates.indexOf(state.date);
const metric=(p,h=state.h)=>p.windows[state.date][String(h)];
const pct=m=>m.display==null?'—':signed(m.display)+'%';
const tag=(text,type='')=>`<span class="tag ${type}">${esc(text)}</span>`;
const empty=(title,body)=>`<div class="empty"><span class="emptyicon">⌁</span><h3>${esc(title)}</h3><p>${esc(body)}</p></div>`;
const pageHeading=(eyebrow,title,sub,extra='')=>`<div class="pageheading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p class="sub">${sub}</p></div>${extra}</div>`;
function validatePersonal(v){
 if(!v||v.schema!=='ql.personal/1'||!Array.isArray(v.favorites)||v.favorites.length>256||!v.notes||typeof v.notes!=='object'||Array.isArray(v.notes))throw Error('文件结构不正确');
 if(v.favorites.some(c=>typeof c!=='string'||!/^\d{6}$/.test(c))||new Set(v.favorites).size!==v.favorites.length)throw Error('含未知或重复产品');
 if(Object.keys(v.notes).some(k=>!/^\d{6}$/.test(k)||typeof v.notes[k]!=='string'||v.notes[k].length>2000))throw Error('备注无效或过长');
 return {schema:'ql.personal/1',favorites:[...v.favorites],notes:Object.fromEntries(Object.entries(v.notes))};
}
try {const old=localStorage.getItem(KEY); if(old)personal=validatePersonal(JSON.parse(old));}
catch {storageOK=false;}
function save(){try{localStorage.setItem(KEY,JSON.stringify(personal));storageOK=true;return true;}catch{storageOK=false;return false;}}
let toastTimer;
function toast(msg){$('#toast').textContent=msg;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,3800);}
function go(route,code){
 const q=new URLSearchParams({date:state.date,w:String(state.h)}); if(code||route==='detail')q.set('code',code||state.code);
 const hash=`#/${route}?${q}`;
 if(location.hash===hash)render();else {history.pushState(null,'',hash);routeFromHash();}
}
function routeFromHash(){
 const parts=location.hash.replace(/^#\//,'').split('?');
 state.route=Object.hasOwn(titles,parts[0])?parts[0]:'overview';const q=new URLSearchParams(parts[1]||'');
 if(D.dates.includes(q.get('date')))state.date=q.get('date');
 if([1,5,20,60].includes(Number(q.get('w'))))state.h=Number(q.get('w'));
 if(byCode[q.get('code')])state.code=q.get('code');state.point=idx();state.flow=false;render();
}
function updateURL(){history.replaceState(null,'',`#/${state.route}?${new URLSearchParams({date:state.date,w:String(state.h),code:state.code})}`);}
function star(p){const on=personal.favorites.includes(p.code);return `<button class="star" data-action="star" data-code="${p.code}" aria-pressed="${on}" aria-label="${on?'移出自选':'加入自选'} ${p.label}">${on?'★':'☆'}</button>`;}
function windows(){return `<div class="windows" role="group" aria-label="观察窗口">${[1,5,20,60].map(h=>`<button data-action="window" data-h="${h}" class="${state.h===h?'active':''}" aria-pressed="${state.h===h}">${h===1?'当日':h+'日'}</button>`).join('')}</div>`;}
function chartCard(products,heading='净值走势对比'){
 const available=idx()>=state.h;
 return `<section class="card"><div class="cardhead"><div><h2>${heading}</h2><p class="sub">${available?D.dates[idx()-state.h]+' = 100':'归一化净值'} · 未复权数值</p></div>${windows()}</div>
 ${products.length>1?`<div class="legend">${products.map(p=>`<button data-action="legend" data-code="${p.code}" aria-pressed="${state.visible.has(p.code)}"><span class="swatch" style="--series:${palette[D.products.indexOf(p)%palette.length]}"></span>${p.label}</button>`).join('')}</div>`:''}
 ${available?`<div data-plot="nav" data-codes="${products.map(p=>p.code).join(',')}"></div><div class="readout" data-readout="nav"></div>`:empty('历史不足，暂不计算',`${state.h}日窗口需要${state.h+1}个连续交易日观察值；截至所选日期仅有${idx()+1}个。`)}
 <div class="cardfoot">点击图中日期或用键盘查看读数。仅为产品比较，非行业资金迁移或投资总收益。</div></section>`;
}
function filtered(){return D.products.filter(p=>(state.group==='全部'||p.group===state.group)&&(`${p.label}${p.name}${p.code}`.includes(state.query))).sort((a,b)=>{const x=metric(a).value,y=metric(b).value;return x==null&&y==null?a.code.localeCompare(b.code):x==null?1:y==null?-1:(Number(y)-Number(x))*(state.sort==='desc'?1:-1);});}
function filterBar(){return `<div class="toolbar"><div class="filters" role="group" aria-label="产品分类">${['全部','行业相关','主题','宽基','风格'].map(g=>`<button data-action="group" data-group="${g}" aria-pressed="${state.group===g}">${g}</button>`).join('')}</div><input class="searchbox" type="search" id="search" aria-label="搜索产品名称或代码" placeholder="搜索名称或代码" value="${esc(state.query)}"></div>`;}
function productTable(){const ps=filtered();return `<section class="card"><div class="cardhead"><div><h2>观察池表现</h2><p class="sub">按${state.h===1?'当日':state.h+'日'}净值变化排列 · 不是正式行业排名</p></div><button class="linkbutton" data-action="sort">${state.sort==='desc'?'↓ 从强到弱':'↑ 从弱到强'}</button></div>${filterBar()}
 ${ps.length?`<div class="scrolltable desktopproducts"><table><thead><tr><th>产品 / 分类</th><th>单位净值（元）</th><th>当日变化</th><th>${state.h}日变化</th><th>相对宽基（百分点）</th><th>自选</th></tr></thead><tbody>${ps.map(p=>{const m=metric(p),d=metric(p,1);return `<tr><td><button class="rowname" data-action="detail" data-code="${p.code}">${p.label} ↗</button><span class="mono">${p.code}</span>${tag(p.group,'neutral')}</td><td>${p.nav[idx()]??'—'}</td><td class="${cls(d.value)}">${pct(d)}</td><td class="${cls(m.value)}">${pct(m)}</td><td class="${cls(m.relative_pp)}">${signed(m.relative_display)}</td><td>${star(p)}</td></tr>`;}).join('')}</tbody></table></div><div class="mobileproducts">${ps.map(p=>{const m=metric(p);return `<article class="mobileproduct"><div class="mobileproducttop"><button class="linkbutton" data-action="detail" data-code="${p.code}"><strong>${p.label} ↗</strong><span class="mono">${p.code} · ${p.group}</span></button>${star(p)}</div><div class="mobilemetrics"><div><small>${state.h}日变化</small><strong class="${cls(m.value)}">${pct(m)}</strong></div><div><small>相对宽基 / 百分点</small><strong class="${cls(m.relative_pp)}">${signed(m.relative_display)}</strong></div><div><small>单位净值 / 元</small><strong>${p.nav[idx()]??'—'}</strong></div></div></article>`;}).join('')}</div>`:empty('没有匹配的产品','调整分类或搜索条件；当前观察池范围见顶部。')}
 <div class="tablecaption">参照：${D.benchmark_code} ${esc(byCode[D.benchmark_code].label)} ETF，非官方指数。分类为产品标签；未接入完整历史行业成分。</div></section>`;}
function overview(){const sh=D.products.filter(p=>p.shares_wan[idx()]!==null).length;const nv=D.products.filter(p=>p.nav[idx()]!==null).length;
 return pageHeading('DAILY RESEARCH / 01','观察池概览','新数据接入同一页面；可用证据与缺口分别展示。',`<span class="minor">${state.date} · 取证快照</span>`)+
 `<div class="stats"><div class="stat"><div class="statlabel">研究范围</div><div class="statvalue">${D.products.length}<small>只 ETF</small></div><div class="statnote">数量来自数据包，不是固定样例</div></div><div class="stat"><div class="statlabel">当日净值 / 份额覆盖</div><div class="statvalue small">${nv}/${D.products.length} · ${sh}/${D.products.length}</div><div class="statnote">数量口径；过期份额不冒充当日覆盖</div></div><div class="stat"><div class="statlabel">日历观察窗口</div><div class="statvalue">${idx()+1}<small>个交易日</small></div><div class="statnote">缺失记录留空，不压缩交易日历</div></div><div class="stat"><div class="statlabel">行业资金判断</div><div class="statvalue small">证据不足</div><div class="statnote">不发布资金排名与买卖信号</div></div></div>
 <div class="mainrow">${chartCard(D.products)}<section class="card signalbox"><div class="signalintro"><div class="eyebrow">EVIDENCE FIRST</div><h2>当前可用证据</h2>${tag('产品观察，不是行业结论','warn')}<h3>先比较表现，<br>再核对资金证据。</h3><p>新增产品、日期与参照都来自数据配置。净值和份额分开校验；不以价格强弱替代真实资金证据。</p></div><div class="evidencerow"><span>价格维度</span>${tag('原始净值可复算')}</div><div class="evidencerow"><span>资金维度</span>${tag(sh?'事件尚未验收':'当日份额缺失','warn')}</div><div class="evidencerow"><span>行业广度</span>${tag('尚未接入','neutral')}</div><button class="linkbutton" data-route="methods">查看数据与方法 →</button></section></div>${productTable()}`;}
function compare(){const ps=filtered();return pageHeading('CROSS-SECTION / 02','方向比较','先区分行业相关、跨行业主题与风格；暂不将产品表现等同于行业资金。')+
 `<section class="card"><div class="cardhead"><div><h2>逐日净值变化</h2><p class="sub">单位：% · 最多显示最近60个交易日 · 点击进入详情</p></div>${tag('真实样例 · 未复权')}</div>${filterBar()}${ps.length?`<div class="scrolltable"><table class="heat"><thead><tr><th>产品</th>${D.dates.slice(Math.max(0,idx()-59),idx()+1).map(d=>`<th>${d.slice(5)}</th>`).join('')}</tr></thead><tbody>${ps.map(p=>`<tr><td><button class="rowname" data-action="detail" data-code="${p.code}">${p.label}</button><span class="mono">${p.code} · ${p.group}</span></td>${D.dates.slice(Math.max(0,idx()-59),idx()+1).map(d=>{const m=p.windows[d]['1'],n=m.value==null?null:Number(m.value);const c=n==null?'#f3f5f7':n<0?`rgba(35,121,110,${.07+Math.min(Math.abs(n)/5,1)*.22})`:`rgba(180,71,60,${.07+Math.min(n/5,1)*.22})`;return `<td><button class="heatcell ${cls(m.value)}" style="--cell:${c}" data-action="heat" data-code="${p.code}" data-date="${d}" aria-label="${p.label} ${d} ${pct(m)}">${pct(m)}</button></td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`:empty('没有匹配产品','请调整分类或关键词。')}<div class="tablecaption">红色为正、绿色为负，同时保留数字与正负号。首日缺前值，显示“—”，不记为0。</div></section>
 <div class="gap two"><section class="card"><div class="cardhead"><h2>资金 × 价格</h2>${tag('尚未启用','neutral')}</div>${empty('不绘制缺少依据的散点','缺完整行业映射、已验收申赎金额及同日行业价格。不会用估算大单或净值变化补造资金轴。')}</section><section class="card"><div class="cardhead"><h2>从比较到观察</h2></div><div class="cardbody"><div class="methodrow"><h3>① 识别相对变化</h3><p>切换窗口，查看表现差异是否持续。单日颜色不代表趋势。</p></div><div class="methodrow"><h3>② 查找相同日期的证据</h3><p>点开产品，核对净值、份额、时点和公式；缺项单列。</p></div><div class="methodrow"><h3>③ 留下可证伪条件</h3><p>将对象加入自选，记录支持与反对证据，而不是预设机构意图。</p></div></div></section></div>`;}
function detail(){const p=byCode[state.code],m=metric(p),isShare=p.shares_wan.slice(0,idx()+1).some(v=>v!==null),flow=p.flow_windows[state.date][String(state.h)];return pageHeading('INSTRUMENT / 03',p.label,`${p.name} · ${p.code}`,star(p))+
 `<div class="detailcontrols"><label for="product-select" class="minor">切换产品</label><select id="product-select" aria-label="选择产品">${D.products.map(x=>`<option value="${x.code}" ${x.code===p.code?'selected':''}>${x.code} ${x.label}</option>`).join('')}</select>${tag(p.group,'neutral')}<button class="linkbutton" data-action="evidence" data-code="${p.code}">来源与原始字段 ↗</button></div>
 <div class="stats gap"><div class="stat"><div class="statlabel">单位净值 / 元</div><div class="statvalue">${p.nav[idx()]??'—'}</div><div class="statnote">${state.date} · 未复权</div></div><div class="stat"><div class="statlabel">${state.h}日净值变化</div><div class="statvalue ${cls(m.value)}">${pct(m)}</div><div class="statnote">${m.value==null?'完整窗口不足':'按原始字段直接复算'}</div></div><div class="stat"><div class="statlabel">总份额 / 万份</div><div class="statvalue">${isShare?num(p.shares_wan[idx()]):'—'}</div><div class="statnote">${isShare?'字段来源见数据依据；缺值不前填':'尚未取得连续份额'}</div></div><div class="stat"><div class="statlabel">正式资金指标</div><div class="statvalue small">未通过</div><div class="statnote">${isShare?'事件基础待核验':'缺连续份额与事件依据'}</div></div></div>
 <div class="two">${chartCard([p],'产品净值')}<section class="card"><div class="cardhead"><div><h2>总份额变化</h2><p class="sub">单位：万份 · 非零起点纵轴</p></div>${isShare?tag('已披露摘录'):tag('未取得','neutral')}</div>${isShare&&idx()>=state.h?`<div data-plot="shares" data-codes="${p.code}"></div><div class="readout" data-readout="shares"></div>`:empty(isShare?'窗口历史不足':'暂无份额数据',isShare?'缩短观察窗口或选择更晚的样本日期。':'没有连续总份额，不能以PCF申赎上限或基金规模替代。')}<div class="cardfoot">份额变化≠机构净买卖；显示精度下的数值比较。</div></section></div>
 <div class="gap two"><section class="card"><div class="cardhead"><h2>申赎估值核验</h2>${tag('未进入正式资金指标','warn')}</div><div class="cardbody"><p class="sub">正式金额为缺失，不是0。只有事件口径、相邻交易日份额和同日净值全部通过，才允许进入资金比较。</p>${isShare?`<button class="linkbutton" data-action="flow" aria-expanded="${state.flow}">${state.flow?'收起':'查看'}条件试算 ${state.flow?'−':'+'}</button>${state.flow?`<div class="personalhint"><strong>假设无折算、合并等非申赎份额变化（未核实）</strong><p>${state.h}日条件申赎估值：<strong>${num(flow)} 万元</strong>。${flow==null?'窗口不足，未计算。':'这不是精确现金流，也不是机构净买卖。'}</p></div><code class="formula">Fₜ = (Sₜ − Sₜ₋₁) × NAVₜ<br>输入总份额单位为份；图表换算为万份。k=1仅为待验证假设。</code>`:''}`:''}</div></section>
 <section class="card"><div class="cardhead"><h2>观察与复盘</h2>${tag('保存在此浏览器','neutral')}</div><div class="cardbody"><p class="sub">记录下一步需要看到的证据，以及原判断何时失效。不会上传或自动生成操作指令。</p><textarea id="detail-note" class="notes" maxlength="2000" aria-label="产品观察备注" placeholder="例如：等待同日份额与行业广度，核验相对表现是否持续。">${esc(drafts[p.code]??personal.notes[p.code]??'')}</textarea><div class="notebar"><span>最多2000字 · 不跨设备同步</span><button class="primary" data-action="save-note" data-code="${p.code}">保存观察</button></div></div></section></div>`;}
function watch(){return pageHeading('PERSONAL / 04','自选与复盘','记录观察条件，逐步建立自己的复盘线索。')+
 `<div class="personaltools"><button data-action="export">导出自选与备注 ↓</button><button data-action="import">导入本地文件 ↑</button><input id="personal-file" type="file" accept=".json,application/json" hidden><button data-action="clear">清空本地记录</button></div><div class="personalhint">${storageOK?'记录仅存于当前浏览器；不上传，不与其他设备同步。清理浏览器数据后可能丢失，请自行备份。':'浏览器存储不可用或旧记录无效；当前记录仅在内存中，关闭页面会丢失。请导出备份。'}</div>
 <p class="minor">${personal.favorites.filter(c=>!byCode[c]).length}个池外关注对象仍保留在本地，可导出；切换观察池不会删除。</p><section class="card">${personal.favorites.filter(c=>byCode[c]).length?personal.favorites.filter(c=>byCode[c]).map(c=>{const p=byCode[c],m=metric(p);return `<div class="watchrow"><div class="watchheading"><div><button class="rowname linkbutton" data-action="detail" data-code="${c}">${p.label} ↗</button><div class="mono">${c} · ${p.group}</div></div><div><strong class="${cls(m.value)}">${pct(m)}</strong>${star(p)}</div></div><p class="sub">${esc(personal.notes[c]||'尚未记录观察条件。打开详情即可添加。')}</p></div>`;}).join(''):empty('先加入一个值得跟踪的方向','在观察池或产品详情点击星标。自选列表默认为空，不替你预设持仓或投资偏好。')}</section>`;}
function sourceRows(ids){return ids.map(id=>{const s=D.sources[id];return `<div class="sourceitem"><div><h3>${esc(s.provider)}</h3><p>${esc(id)} · ${s.published_at?'披露 '+esc(s.published_at):'原始披露时刻未知'}</p><p>获取 ${esc(s.recorded_at)}<br>${s.mode==='http_response'?'HTTP响应':s.mode==='prior_repository_fixture'?'沿用历史取证':'官方页面文本摘录'} · ${s.raw_response_archived?'已归档响应':'非HTTP原始响应归档'}</p></div><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">来源 ↗</a></div>`;}).join('');}
function methods(){return pageHeading('PROVENANCE / 05','数据与方法','每个字段有来源；新增日期不改变计算规则。')+
 `<div class="healthgrid"><div class="healthitem"><h3>净值观察</h3>${tag(D.products.length+'只产品 · '+D.products.reduce((n,p)=>n+p.nav.filter(v=>v!==null).length,0)+'条净值')}<p>数据截至 ${D.asof}；取证截止 ${esc(D.observed_at)}。未复权净值数值不是总收益。</p></div><div class="healthitem"><h3>资金证据</h3>${tag('未正式验收','warn')}<p>各产品独立检查连续份额。条件试算不等于机构净买卖；行业广度和事件核验仍缺失。</p></div><div class="healthitem"><h3>运行状态</h3>${tag('取证快照，未接通定时采集','neutral')}<p>本站可读取经校验的数据包；此能力不等于数据源已持续自动更新。文件校验也不认证来源真实性。</p></div></div>
 <div class="gap two"><section class="card"><div class="cardhead"><h2>计算口径</h2></div><div class="cardbody"><div class="methodrow"><h3>独立价格与相对表现</h3><code class="formula">(NAVₜ / NAVₜ₋ₕ − 1) × 100%</code><p>浏览器使用十进制定点整数和有理数运算，最后才舍入。参照缺失只停用相对值，不抹去产品自身完整表现。</p></div><div class="methodrow"><h3>参照配置</h3><p>${esc(D.benchmark_code)} ${esc(byCode[D.benchmark_code].label)}。同窗口、同口径相减为百分点；不冒充官方行业指数。</p></div><div class="methodrow"><h3>份额与条件估值</h3><code class="formula">Σ (Sₜ − Sₜ₋₁) × NAVₜ</code><p>原始份额单位为份；展示换算为万份。假设k=1未核实。缺任一交易日份额或对应净值则不计算，不前填。</p></div><div class="methodrow"><h3>时间和历史</h3><p>按显式交易日历计算；h日需h+1个完整观察值。当前日历${D.dates.length}日；有足够真实历史后20/60日自动启用。历史回看不代表当时已知。</p></div></div></section><section class="card"><div class="cardhead"><h2>来源登记</h2></div><div class="cardbody">${sourceRows(Object.keys(D.sources))}</div></section></div>
 <section class="card gap"><div class="cardhead"><h2>版本与边界</h2></div><div class="cardbody"><p>${esc(D.scope)}</p><code class="formula">${esc(D.version)} / ql.market-bundle/2<br>截至 ${D.asof} / Asia/Shanghai<br>正式资金金额 null</code><p class="sub">私人备注不上网；没有自动交易、预测概率或仓位指令。版权与来源用途必须在发布端另行审核。</p></div></section>`;}
function render(){
 const active=document.activeElement,id=active?.id,selection=id==='search'?active.selectionStart:null;
 $('#asof').innerHTML=D.dates.map(d=>`<option ${state.date===d?'selected':''}>${d}</option>`).join('');
 $('#crumb').textContent=titles[state.route];document.title=`ql · ${titles[state.route]}`;
 document.querySelectorAll('[data-route]').forEach(a=>{if(a.dataset.route===state.route)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('#notice-text').textContent=`取证快照 · 数据截止 ${D.asof} · 本次查看 ${state.date} · 持续自动采集尚未接通。`;
 app.innerHTML=({overview,compare,detail,watch,methods}[state.route])();app.setAttribute('aria-busy','false');drawCharts();
 if(id==='search'&&$('#search')){$('#search').focus();$('#search').setSelectionRange(selection,selection);}
}
function drawCharts(){
 document.querySelectorAll('[data-plot]').forEach(el=>{
  const kind=el.dataset.plot, all=el.dataset.codes.split(',').map(c=>byCode[c]);
  const ps=kind==='nav'&&all.length>1?all.filter(p=>state.visible.has(p.code)):all;
  if(!ps.length){el.innerHTML=empty('已隐藏全部曲线','点击上方图例恢复比较。');const r=el.nextElementSibling;if(r)r.textContent='未选择产品';return;}
  const start=idx()-state.h,days=D.dates.slice(start,idx()+1);
  const series=ps.map(p=>({p,values:kind==='shares'?p.shares_wan.slice(start,idx()+1):metric(p).rebased}));
  if(series.some(s=>s.values.length!==days.length||s.values.some(v=>v===null))){el.innerHTML=empty('数据不足','缺失值不插值、不前填。');return;}
  const width=Math.max(280,el.clientWidth),height=innerWidth<=760?240:274,L=kind==='shares'?65:42,R=23,T=22,B=34;
  const vals=series.flatMap(s=>s.values.map(Number));let min=Math.min(...vals),max=Math.max(...vals);const pad=Math.max((max-min)*.18,kind==='shares'?1:.2);min-=pad;max+=pad;
  const x=i=>L+i*(width-L-R)/Math.max(days.length-1,1),y=v=>T+(max-Number(v))*(height-T-B)/(max-min);
  let svg=`<svg class="plot" viewBox="0 0 ${width} ${height}" aria-label="${kind==='shares'?'总份额（万份）':'归一化净值'}，${days[0]}至${days.at(-1)}"><title>点击日期查看读数；也可查看来源中的表格</title>`;
  for(let k=0;k<5;k++){let v=min+(max-min)*k/4;svg+=`<line class="grid" x1="${L}" x2="${width-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end">${num(v,kind==='shares'?0:1)}</text>`;}
  const pt=Math.max(start,Math.min(state.point,idx()));svg+=`<line class="selectedline" x1="${x(pt-start)}" x2="${x(pt-start)}" y1="${T}" y2="${height-B}"/>`;
  series.forEach(s=>{const color=palette[D.products.indexOf(s.p)%palette.length],ds=s.p.code===D.benchmark_code?'7 4':'';svg+=`<path class="series" style="--series:${color}" stroke-dasharray="${ds}" d="${s.values.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v)}`).join(' ')}"/>`;s.values.forEach((v,i)=>{svg+=`<circle cx="${x(i)}" cy="${y(v)}" r="${i===pt-start?4:2.6}" fill="${color}" stroke="white" stroke-width="1.5"/>`;});});
  days.forEach((d,i)=>{let l=i? (x(i-1)+x(i))/2:L-5,r=i===days.length-1?width-R+5:(x(i)+x(i+1))/2;svg+=`${(i===0||i===days.length-1||i%Math.max(1,Math.ceil(days.length/6))===0)?`<text x="${x(i)}" y="${height-12}" text-anchor="${i===0?'start':i===days.length-1?'end':'middle'}">${d.slice(5)}</text>`:''}<rect class="hit" data-action="point" data-index="${start+i}" x="${l}" y="${T}" width="${r-l}" height="${height-T-B}" tabindex="0" role="button" aria-label="查看 ${d} 读数"/>`;});
  el.innerHTML=svg+'</svg>';const read=el.nextElementSibling;read.innerHTML=`<strong>${D.dates[pt]}</strong>`+series.map(s=>`<span>${s.p.label} <strong>${num(s.values[pt-start],2)}${kind==='shares'?' 万份':''}</strong></span>`).join('');
 });
}
function evidence(code){const p=byCode[code];$('#dialog-title').textContent=`${p.label} · 数据依据`;$('#dialog-content').innerHTML=`<p class="sub">当前查看 ${state.date}；来源与获取方式逐字段记录；取证时间不等于原始披露时间，权益事件尚未核验。</p>${sourceRows(p.source_ids)}<div class="scrolltable"><table><thead><tr><th>交易日期</th><th>单位净值 / 元</th><th>总份额 / 万份</th></tr></thead><tbody>${D.dates.slice(0,idx()+1).map((d,i)=>`<tr><td>${d}</td><td>${p.nav[i]??'—'}</td><td>${num(p.shares_wan[i])}</td></tr>`).join('')}</tbody></table></div><p class="sub">归一化：NAV ÷ 窗口首日NAV × 100。份额缺失不按0处理；此处不能推断机构身份或行业资金迁移。</p>`;$('#evidence-dialog').showModal();}
let pendingImport=null;
function confirmation(title,text,action){$('#dialog-title').textContent=title;$('#dialog-content').innerHTML=`<p>${esc(text)}</p><div class="personaltools gap"><button data-action="cancel-dialog">取消</button><button class="primary" data-action="${action}">确认</button></div>`;$('#evidence-dialog').showModal();}
document.addEventListener('click',ev=>{
 const a=ev.target.closest('[data-route]');if(a){ev.preventDefault();go(a.dataset.route);return;}
 const b=ev.target.closest('[data-action]');if(!b)return;const action=b.dataset.action,c=b.dataset.code;
 if(action==='window'){state.h=Number(b.dataset.h);state.point=idx();updateURL();render();}
 else if(action==='group'){state.group=b.dataset.group;render();}
 else if(action==='sort'){state.sort=state.sort==='desc'?'asc':'desc';render();}
 else if(action==='legend'){state.visible.has(c)?state.visible.delete(c):state.visible.add(c);render();}
 else if(action==='detail'){go('detail',c);}
 else if(action==='heat'){state.date=b.dataset.date;state.h=1;go('detail',c);}
 else if(action==='star'){const i=personal.favorites.indexOf(c);if(i<0)personal.favorites.push(c);else personal.favorites.splice(i,1);const ok=save();render();toast(ok?(i<0?'已加入本地自选':'已移出本地自选'):'暂存于内存，浏览器存储不可用');}
 else if(action==='evidence')evidence(c);
 else if(action==='flow'){state.flow=!state.flow;render();}
 else if(action==='point'){state.point=Number(b.dataset.index);drawCharts();}
 else if(action==='save-note'){personal.notes[c]=$('#detail-note').value;delete drafts[c];if(!personal.favorites.includes(c))personal.favorites.push(c);toast(save()?'观察已保存，并加入自选':'暂存于内存，请导出备份');}
 else if(action==='export'){const blob=new Blob([JSON.stringify(personal,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='ql-personal.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 else if(action==='import')$('#personal-file').click();
 else if(action==='clear')confirmation('清空本地记录','这会删除当前浏览器的自选和备注。建议先导出备份。','confirm-clear');
 else if(action==='confirm-clear'){personal={schema:'ql.personal/1',favorites:[],notes:{}};Object.keys(drafts).forEach(k=>delete drafts[k]);save();$('#evidence-dialog').close();render();toast('当前记录已清空');}
 else if(action==='confirm-import'){if(pendingImport)personal=pendingImport;Object.keys(drafts).forEach(k=>delete drafts[k]);pendingImport=null;const ok=save();$('#evidence-dialog').close();render();toast(ok?'已导入本地记录':'已导入内存，浏览器存储不可用');}
 else if(action==='cancel-dialog')$('#evidence-dialog').close();
});
document.addEventListener('keydown',ev=>{const b=ev.target.closest('rect[data-action="point"]');if(b&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();state.point=Number(b.dataset.index);drawCharts();}});
document.addEventListener('input',ev=>{if(ev.target.id==='detail-note'){drafts[state.code]=ev.target.value;}if(ev.target.id==='search'){state.query=ev.target.value;render();}});
document.addEventListener('change',async ev=>{
 if(ev.target.id==='asof'){state.date=ev.target.value;state.point=idx();updateURL();render();}
 else if(ev.target.id==='product-select')go('detail',ev.target.value);
 else if(ev.target.id==='personal-file'){
  const file=ev.target.files?.[0];if(!file)return;
  try{if(file.size>100000)throw Error('文件超过100KB');const text=await file.text();pendingImport=validatePersonal(JSON.parse(text));confirmation('导入本地记录',`将用文件中的 ${pendingImport.favorites.length} 个自选和备注替换当前记录。`,'confirm-import');}
  catch{pendingImport=null;toast('导入失败：文件格式、产品代码或大小不符合要求；原记录未改变。');}finally{ev.target.value='';}
 }
});
$('#close-dialog').addEventListener('click',()=>$('#evidence-dialog').close());
$('#evidence-dialog').addEventListener('close',()=>pendingImport=null);
let resizeTimer;addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(drawCharts,100);});
addEventListener('hashchange',routeFromHash);routeFromHash();
})();
