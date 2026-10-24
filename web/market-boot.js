/* Startup diagnostics for the actual multi-resource Page; no data or secrets. */
(function(root){
'use strict';
let timer=null, failed=false;
function fail(){
 if(failed)return;failed=true;clearTimeout(timer);
 const app=document.querySelector('#app'),status=document.querySelector('#market-status');
 if(status)status.textContent='页面组件加载失败';
 if(app){
  app.replaceChildren();
  const card=document.createElement('section');card.className='card';
  const body=document.createElement('div');body.className='cardbody';
  const h=document.createElement('h1');h.textContent='页面未能完整启动';
  const p=document.createElement('p');p.textContent='脚本可能缺失或版本校验失败。请重新加载；本地自选和备注未被删除。';
  const button=document.createElement('button');button.id='market-reload';button.textContent='重新加载';
  button.addEventListener('click',()=>location.reload());
  body.append(h,p,button);card.append(body);app.append(card);app.setAttribute('aria-busy','false');
 }
 for(const id of ['market-open','market-refresh','asof']){const e=document.getElementById(id);if(e)e.disabled=true;}
}
root.addEventListener('error',e=>{
 if(e.target?.tagName==='SCRIPT'||(e.target===root&&/market-(?:data|loader|app)[.]/.test(e.filename||'')))fail();
},true);
timer=setTimeout(fail,18000);
root.QLMarketBoot=Object.freeze({ready:()=>clearTimeout(timer),fail});
})(globalThis);
