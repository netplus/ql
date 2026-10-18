/* Load only our own application code after local data validation. */
QLRelease.start(()=>{
 const s=document.createElement('script');s.src='./app.js';
 s.onerror=()=>{document.querySelector('#bundle-message').textContent='应用脚本载入失败，请刷新重试；本地数据没有上传。';};
 document.body.appendChild(s);
});
