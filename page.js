
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon');
  const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){
  const cur = (document.documentElement.getAttribute('data-theme')==='light') ? 'dark' : 'light';
  applyTheme(cur);
}
function initTheme(){
  let t='dark';
  try{ t = localStorage.getItem('arb_theme') || 'dark'; }catch(e){}
  applyTheme(t);
}
initTheme();
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

async function load(){
  const code=document.getElementById('code').value.trim();
  const days=document.getElementById('days').value.trim();
  const und=document.getElementById('und').value.trim();
  const threshold=document.getElementById('threshold').value.trim();
  const btn=document.getElementById('btn');
  btn.disabled=true; document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('summary').innerHTML='';
  document.getElementById('statusbar').style.display='none';
  document.getElementById('fund-title').innerHTML='';
  try{
    let url='/api/data?code='+encodeURIComponent(code)+'&days='+encodeURIComponent(days)
          +'&threshold='+encodeURIComponent(threshold);
    if(und) url+='&underlying='+encodeURIComponent(und);
    const r=await fetch(url); const d=await r.json();
    if(d.error){ throw new Error(d.error); }
    render(d);
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
  }
}

function render(d){
  const code=d.code, name=d.name||('基金'+code);
  // 右侧大标题：基金名称 + 代码
  document.getElementById('fund-title').innerHTML=esc(name)+' <small>'+esc(code)+'</small>';

  // 交易状态条（申购状态、限购、赎回）—— 这是基金当前状态，不是每日变化数据
  const c=d.control||{};
  const st=c.subscribe_status||'';
  const stCol=STATUS_COLORS[st]||'#8c8c8c';
  const bar=document.getElementById('statusbar');
  bar.style.display='flex';
  let barClass='info', barHtml='';
  if(st){
    barClass = st==='暂停申购'?'warn':(st==='限大额申购'?'ok':'ok');
    let hint='';
    if(st==='暂停申购') hint='当前无法做「申购套利」，仅折价赎回套利可行（需看赎回状态）。';
    else if(st==='限大额申购') hint='可做申购套利，但受每日上限约束。';
    else if(st==='开放申购') hint='申购通道正常开放。';
    barHtml='<div class="status-item"><span class="status-label">申购状态</span>'
          +'<span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st)+'</span></div>'
          +'<div class="status-item"><span class="status-label">限购金额</span><span>'+(c.purchase_limit_text?esc(c.purchase_limit_text):'—')+'</span></div>'
          +'<div class="status-item"><span class="status-label">赎回状态</span><span>'+esc(c.redeem_status||'—')+'</span></div>'
          +'<div class="status-item"><span class="status-label">申购起点</span><span>'+(c.purchase_min!=null?esc(c.purchase_min+'元'):'—')+'</span></div>'
          +'<div class="status-item" style="margin-left:auto;color:#8b949e">'+hint+'</div>';
  }else{
    barHtml='<div class="status-item">ℹ️ 申购状态获取失败（可能网络受限），请手动核对基金公告。</div>';
  }
  bar.className='statusbar '+barClass;
  bar.innerHTML=barHtml;

  // 摘要卡片（原油/油气基金才显示 XOP 收盘）
  const s=d.summary||{};
  const showOil = !!d.is_oil_gas;
  const summ=[
    ['最新场内价', fmtNum(s.latest_price,4)],
    ['最新估值溢价', fmtPct(s.latest_premium), s.latest_premium>0?'pos':(s.latest_premium<0?'neg':'')],
    ['最新 USD/CNY', fmtNum(s.latest_fx,4)],
  ];
  if(showOil){
    summ.splice(2,0,['最新 XOP 收盘', fmtNum(s.latest_xop,2)]);
  }
  document.getElementById('summary').innerHTML=summ.map(it=>
    '<div class="sitem"><div class="l">'+it[0]+'</div><div class="v '+(it[2]||'')+'">'+it[1]+'</div></div>'
  ).join('');

  // 表格：日期 价格 涨跌% 净值 净值涨跌幅 估算净值 估值溢价 汇率 汇率涨跌
  //       （原油/油气基金追加 XOP收盘、XOP溢价） 申购状态 限购金额 套利信号
  const head=['日期','价格','涨跌%','净值','净值涨跌幅','估算净值','估值溢价','汇率','汇率涨跌'];
  if(showOil) head.push('XOP收盘','XOP溢价');
  head.push('申购状态','限购金额','套利信号');
  const limitTxt = c.purchase_limit!=null ? esc(c.purchase_limit+'元') : '—';
  let rowsHtml=d.rows.map(r=>{
    const navCell = r.real_nav!=null? fmtNum(r.real_nav,4)
        : '<span class="est">'+fmtNum(r.est_nav,4)+'<br><small>净值待公布</small></span>';
    const sigR = r.est_premium!=null? r.est_premium : r.premium;
    const sigTxt = sigR==null?'—':(sigR>d.threshold?'溢价·可申购':(sigR<-d.threshold?'折价·可赎回':'平价'));
    const sigC = sigR==null?'':(sigR>d.threshold?'pos':(sigR<-d.threshold?'neg':''));
    let cells='<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+navCell+'</td>'
      +'<td class="'+cls(r.nav_change)+'">'+fmtPct(r.nav_change,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td>'+fmtNum(r.fx,4)+'</td>'
      +'<td class="'+cls(r.fx_change)+'">'+fmtPct(r.fx_change,true)+'</td>';
    if(showOil){
      cells += '<td>'+fmtNum(r.xop,2)+'</td>'
             + '<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>';
    }
    const stCol=STATUS_COLORS[c.subscribe_status||'']||'#8c8c8c';
    cells += '<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(c.subscribe_status||'—')+'</span></td>'
           + '<td>'+limitTxt+'</td>'
           + '<td class="'+sigC+'">'+sigTxt+'</td>';
    return '<tr>'+cells+'</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML='<tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+rowsHtml;
  document.getElementById('tablebox').style.display='block';
}
document.getElementById('code').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('days').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('threshold').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
load();
// 注册 Service Worker，支持「添加到主屏幕 / 离线看壳」
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{
    navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err));
  });
}
