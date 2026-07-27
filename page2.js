
const DEFAULT_WATCHLIST=["513310","501018","518850","161226","159501","513520","513290","513120","513130","159985","160644","159545","159516","515880","159819","511130","159201","588200","159509","161128","511380","562800","159552","561550","520870","159530","515030","159326","159218","513750","513690","515220","162411","160719","501312","161130","161129","161124","160216","161125","160723","501225","501025","501012","160140"];
const LIST_VERSION="20250727";
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentRows=[], sortKey='premium', sortDesc=true;

function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon'); const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){ applyTheme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light'); }
function initTheme(){ let t='dark'; try{ t=localStorage.getItem('arb_theme')||'dark'; }catch(e){} applyTheme(t); }
initTheme();
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function parseWatchlist(){
  const raw=document.getElementById('watchlist').value;
  return [...new Set(raw.split(/[,，\s]+/).map(x=>x.trim()).filter(x=>/^\d{6}$/.test(x)))];
}
function setWatchlist(arr){ document.getElementById('watchlist').value = arr.join('\n'); }
function loadList(){
  let list;
  try{
    const ver = localStorage.getItem('arb_ranking_list_version');
    if(ver === LIST_VERSION) list = JSON.parse(localStorage.getItem('arb_ranking_list'));
  }catch(e){}
  if(!Array.isArray(list) || list.length===0){ list = DEFAULT_WATCHLIST; saveList(); }
  setWatchlist(list);
}
function saveList(){ localStorage.setItem('arb_ranking_list', JSON.stringify(parseWatchlist())); localStorage.setItem('arb_ranking_list_version', LIST_VERSION); }
function addCode(){
  const inp=document.getElementById('addCode'); const c=inp.value.trim();
  if(!/^\d{6}$/.test(c)){ alert('请输入 6 位基金代码'); return; }
  const list=parseWatchlist();
  if(list.includes(c)){ alert('该代码已在清单中'); inp.value=''; return; }
  list.push(c); setWatchlist(list); saveList(); inp.value='';
  load();
}
function removeCode(c){
  const list=parseWatchlist().filter(x=>x!==c); setWatchlist(list); saveList(); load();
}
function resetList(){ setWatchlist(DEFAULT_WATCHLIST); saveList(); load(); }

function today(){ const d=new Date(); const off=(8*60+d.getTimezoneOffset())*60000; const b=new Date(d.getTime()+off); const p=n=>String(n).padStart(2,'0'); return b.getFullYear()+'-'+p(b.getMonth()+1)+'-'+p(b.getDate()); }
function initDate(){
  const d=document.getElementById('rdate');
  let saved; try{ saved=localStorage.getItem('arb_ranking_date'); }catch(e){}
  d.value = saved || today();
}

document.getElementById('addCode').addEventListener('keydown',e=>{ if(e.key==='Enter') addCode(); });

document.getElementById('rdate').addEventListener('change',()=>{
  try{ localStorage.setItem('arb_ranking_date', document.getElementById('rdate').value); }catch(e){}
});

async function load(){
  const date=document.getElementById('rdate').value;
  const threshold=document.getElementById('threshold').value;
  const codes=parseWatchlist();
  if(codes.length===0){ alert('请至少输入一个基金代码'); return; }
  saveList();
  try{ localStorage.setItem('arb_ranking_date', date); }catch(e){}
  const btn=document.getElementById('btn'); btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('rankbar').style.display='none'; document.getElementById('summary2').innerHTML='';
  try{
    const url='/api/ranking?date='+encodeURIComponent(date)+'&codes='+encodeURIComponent(codes.join(','))+'&threshold='+encodeURIComponent(threshold);
    const r=await fetch(url); const d=await r.json();
    if(d.error){ throw new Error(d.error); }
    currentRows=d.rows||[]; sortKey='premium'; sortDesc=true; render(d);
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none'; btn.disabled=false;
  }
}

function sortRows(key){
  if(sortKey===key) sortDesc=!sortDesc; else { sortKey=key; sortDesc=true; }
  const isStr = ['code','name','date','time','subscribe_status','signal'].includes(key);
  currentRows.sort((a,b)=>{
    let av=a[sortKey], bv=b[sortKey];
    if(a.error) av=null; if(b.error) bv=null;
    if(av==null && bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    if(isStr) return sortDesc? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    return sortDesc? (bv-av) : (av-bv);
  });
  renderBody();
}
function render(meta){
  const rows=currentRows;
  const ok=rows.filter(r=>!r.error);
  const premium=ok.filter(r=>r.premium!=null);
  const maxPrem = premium.length? premium.reduce((a,b)=>a.premium>b.premium?a:b) : null;
  const minPrem = premium.length? premium.reduce((a,b)=>a.premium<b.premium?a:b) : null;

  const bar=document.getElementById('rankbar');
  bar.style.display='flex';
  bar.innerHTML='<div class="status-item"><span class="k">查询日期</span><span class="v">'+esc(meta.date)+'</span></div>'
    +'<div class="status-item"><span class="k">基金数</span><span class="v">'+rows.length+'</span></div>'
    +'<div class="status-item"><span class="k">成功</span><span class="v">'+ok.length+'</span></div>'
    +(maxPrem?'<div class="status-item"><span class="k">最高溢价</span><span class="v pos">'+fmtPct(maxPrem.premium)+' '+esc(maxPrem.name)+'</span></div>':'')
    +(minPrem?'<div class="status-item"><span class="k">最高折价</span><span class="v neg">'+fmtPct(minPrem.premium)+' '+esc(minPrem.name)+'</span></div>':'');

  const s2=document.getElementById('summary2');
  const up=ok.filter(r=>r.premium>meta.threshold).length;
  const down=ok.filter(r=>r.premium<-meta.threshold).length;
  s2.innerHTML=[
    '<div class="sitem"><div class="l">溢价 > '+meta.threshold+'%</div><div class="v pos">'+up+'</div></div>',
    '<div class="sitem"><div class="l">折价 < -'+meta.threshold+'%</div><div class="v neg">'+down+'</div></div>',
    '<div class="sitem"><div class="l">可申购套利</div><div class="v">'+ok.filter(r=>r.subscribe_status&&r.subscribe_status!=='暂停申购'&&r.premium>meta.threshold).length+'</div></div>',
    '<div class="sitem"><div class="l">数据异常</div><div class="v">'+(rows.length-ok.length)+'</div></div>',
  ].join('');
  sortKey='premium'; sortDesc=true; sortRows('premium');
}

function renderBody(){
  const head=[
    {k:'code',l:'代码'},{k:'name',l:'名称'},{k:'date',l:'日期'},{k:'time',l:'时间'},
    {k:'price',l:'价格'},{k:'price_change',l:'涨幅%'},{k:'nav',l:'净值'},{k:'nav_date',l:'净值日期'},
    {k:'premium',l:'官方溢价'},{k:'est_nav',l:'估算净值'},{k:'est_premium',l:'估算溢价'},
    {k:'subscribe_status',l:'申购状态'},{k:'purchase_limit',l:'限购金额'},{k:'signal',l:'套利信号'},{k:'',l:'操作'}
  ];
  const hHtml=head.map(h=> h.k? '<th style="cursor:pointer" onclick="sortRows(\''+h.k+'\')" title="点击排序">'+esc(h.l)+'</th>' : '<th>'+esc(h.l)+'</th>').join('');
  const rowsHtml=rows.map(r=>{
    if(r.error) return '<tr><td>'+esc(r.code)+'</td><td colspan="14" style="text-align:left;color:var(--muted)">'+esc(r.name)+' — '+esc(r.error)+'</td></tr>';
    const st=r.subscribe_status||''; const stCol=STATUS_COLORS[st]||'#8c8c8c';
    const limitTxt = r.purchase_limit!=null ? esc(r.purchase_limit+'元') : '—';
    const sigC = r.signal_cls==='premium'?'pos':(r.signal_cls==='discount'?'neg':'');
    return '<tr>'
      +'<td>'+esc(r.code)+'</td>'
      +'<td>'+esc(r.name)+'</td>'
      +'<td>'+esc(r.date)+'</td>'
      +'<td>'+esc(r.time)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+fmtNum(r.nav,4)+'</td>'
      +'<td>'+esc(r.nav_date||'—')+'</td>'
      +'<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st||'—')+'</span></td>'
      +'<td>'+limitTxt+'</td>'
      +'<td class="'+sigC+'">'+esc(r.signal)+'</td>'
      +'<td><button class="del-btn" onclick="removeCode(\''+esc(r.code)+'\')" title="移除">×</button></td>'
      +'</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML='<tr>'+hHtml+'</tr>'+rowsHtml;
  document.getElementById('tablebox').style.display='block';
}

loadList(); initDate(); load();
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{ navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err)); });
}
