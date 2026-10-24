/* ql startup: same-origin resources only; never remove stored user data. */
(() => {
'use strict';
const byId=id=>document.getElementById(id);
const status=byId('boot-status'),text=byId('boot-text'),retry=byId('boot-retry');
let failed=false, started=false, script=null, timer=null;
const stop=()=>{if(timer!==null){clearTimeout(timer);timer=null;}};
function showFailure(message){
 failed=true;stop();status.hidden=false;status.setAttribute('role','alert');
 text.textContent=message+' 本地数据未上传，也未被删除。';retry.hidden=false;
 const output=byId('bundle-message');if(output){output.textContent=text.textContent;output.dataset.error='true';}
}
function ready(){if(!failed){stop();status.hidden=true;}}
retry.addEventListener('click',()=>location.reload());
window.addEventListener('error',event=>{
 if(script&&event.filename&&event.filename.split('?')[0]===script.src.split('?')[0]){
  showFailure('工作台脚本执行失败，请重新载入页面。');
 }
});
function launch(){
 if(started)return;started=true;status.hidden=false;text.textContent='正在载入工作台…';
 script=document.createElement('script');script.src="./app.666b3d3f96e5dfb0.js";
 script.integrity="sha256-Zms9P5bl37D7e95CAtU+6gnYyAF8vT0p0nYEwkFTl6s=";script.crossOrigin='anonymous';
 script.addEventListener('error',()=>showFailure('应用资源未能加载或校验未通过，请重新载入页面。'));
 script.addEventListener('load',ready);
 timer=setTimeout(()=>showFailure('应用资源载入超时，请检查网络后重新载入。'),20000);
 document.body.appendChild(script);
}
try{
 if(!window.QLRelease||typeof window.QLRelease.start!=='function'){
  showFailure('数据加载组件未能启动，请重新载入页面。');return;
 }
 window.QLRelease.start(launch);if(!started)ready();
}catch{showFailure('页面初始化失败，请重新载入页面。');}
})();
