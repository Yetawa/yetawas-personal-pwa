# -*- coding: utf-8 -*-
# 由 fund_arb.py 自动抽取的前端模板（COMMON_CSS / 各页面 HTML / PWA 资源）。
# 目的：把 ~1100 行内嵌前端代码移出主逻辑文件，便于维护且不影响导出契约
# （fund_arb.py 通过 `from fund_arb_tpl import (...)` 重新暴露同名变量）。
# 注意：改动页面请改这里；若独立运行需字符串模板，本文件自包含。

import base64

COMMON_CSS = r"""
:root{color-scheme:dark;
  --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#c9d1d9; --muted:#8b949e; --title:#f0f6fc;
  --input-bg:#0d1117; --input-text:#f0f6fc; --btn:#1f6feb; --btn-hover:#388bfd; --row-hover:#1c2128;
  --th-bg:#1f6feb; --th-text:#fff; --pos:#ff5b5b; --neg:#2ecc71; --est:#f2a900; --lock:#f0a020; --code-bg:#0d1117; --code-text:#79c0ff;
  --sb-warn-bg:#2a1416; --sb-warn-border:#ff4d4f55; --sb-warn-label:#d98b8b;
  --sb-ok-bg:#13251a; --sb-ok-border:#52c41a55; --sb-ok-label:#7ec89a;
  --sb-info-bg:#161b22; --sb-info-border:#30363d; --sb-info-label:#8b949e;
}
:root[data-theme="light"]{color-scheme:light;
  --bg:#ffffff; --panel:#f5f7fa; --border:#e3e8ef; --text:#1f2933; --muted:#6b7280; --title:#111827;
  --input-bg:#ffffff; --input-text:#111827; --btn:#2563eb; --btn-hover:#3b82f6; --row-hover:#f0f4f8;
  --th-bg:#2563eb; --th-text:#ffffff; --pos:#dc2626; --neg:#16a34a; --est:#d97706; --lock:#b45309; --code-bg:#f1f5f9; --code-text:#2563eb;
  --sb-warn-bg:#fef2f2; --sb-warn-border:#fca5a5; --sb-warn-label:#b91c1c;
  --sb-ok-bg:#f0fdf4; --sb-ok-border:#86efac; --sb-ok-label:#15803d;
  --sb-info-bg:#f5f7fa; --sb-info-border:#e3e8ef; --sb-info-label:#6b7280;
}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei","Segoe UI",sans-serif;background:var(--bg);color:var(--text);margin:0;padding:60px 20px 20px;transition:background .2s,color .2s}
.wrap{max-width:1280px;margin:0 auto}
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}
.tzline{font-size:13px;color:var(--muted);background:var(--input-bg);border:1px solid var(--border);border-radius:8px;padding:7px 12px;margin:6px 0 14px}
.tzline b{color:var(--text)}
.titles{flex:1;min-width:0}
h1{font-size:22px;margin:0 0 4px;color:var(--title)}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.top-actions{display:flex;align-items:flex-start;gap:8px;flex:none}
.theme-btn{background:var(--panel);color:var(--title);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;white-space:nowrap;flex:none}
a.theme-btn{text-decoration:none}
/* 主题切换小块：标题行右侧（替代导航栏按钮，避免手机端占一行/挡标题） */
.theme-mini{flex:none;align-self:flex-start;margin-left:auto;border:1px solid var(--border);background:var(--panel);color:var(--title);border-radius:6px;padding:2px 8px;font-size:12px;line-height:1.3;cursor:pointer;font-family:inherit}
.theme-mini:hover{border-color:var(--btn);color:var(--btn)}
.theme-btn:hover{border-color:var(--btn);color:var(--btn)}
/* 全站统一固定顶部导航：6 个入口 + 主题切换，位置固定且各页一致 */
.topnav{position:fixed;top:0;left:0;right:0;z-index:2000;display:flex;align-items:center;gap:6px;padding:7px 10px;background:color-mix(in srgb,var(--bg) 90%,transparent);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);overflow-x:auto;scrollbar-width:none}
.topnav::-webkit-scrollbar{display:none}
.topnav .navlink{display:inline-flex;align-items:center;background:var(--panel);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:13.5px;font-weight:600;text-decoration:none;white-space:nowrap;flex:none;cursor:pointer}
.topnav .navlink:hover{border-color:var(--btn);color:var(--btn)}
.topnav .navlink.active{background:var(--btn);border-color:var(--btn);color:#fff}
.topnav .navspacer{flex:1 1 auto}
.topnav .navtheme{margin-left:6px}
/* 站点品牌（需求12：logo + 套利工具平台，点击回首页） */
.topnav .brand{display:inline-flex;align-items:center;gap:6px;background:transparent;border:none;color:var(--text);text-decoration:none;font-weight:800;font-size:14px;white-space:nowrap;flex:none;cursor:pointer;padding:6px 8px;margin-right:2px}
.topnav .brand:hover{color:var(--btn)}
.topnav .brand svg{width:20px;height:20px;flex:none}
.stale-badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;line-height:1;padding:5px 9px;border-radius:7px;background:color-mix(in srgb,var(--est) 12%,transparent);color:var(--est);border:1px solid color-mix(in srgb,var(--est) 35%,transparent);white-space:nowrap;flex:none;animation:stalePulse 1.4s ease-in-out infinite}
.stale-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--est);flex:none}
@keyframes stalePulse{0%,100%{opacity:.55}50%{opacity:1}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:12px;color:var(--muted)}
.field input,.field textarea,.field select{background:var(--input-bg);border:1px solid var(--border);border-radius:8px;color:var(--input-text);padding:8px 10px;font-size:14px}
.field input:focus,.field textarea:focus,.field select:focus{outline:none;border-color:var(--btn)}
button{background:var(--btn);color:#fff;border:none;border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer;font-weight:600}
button:hover{background:var(--btn-hover)}
button:disabled{opacity:.6;cursor:wait}
.fund-title{font-size:22px;font-weight:600;color:var(--title);margin-left:auto;padding-left:12px;white-space:nowrap}
.fund-title small{color:var(--muted);font-size:13px;font-weight:400;margin-left:8px}
.statusbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;background:var(--sb-info-bg);border:1px solid var(--sb-info-border);border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px}
.statusbar.warn{border-color:var(--sb-warn-border);background:var(--sb-warn-bg)}
.statusbar.ok{border-color:var(--sb-ok-border);background:var(--sb-ok-bg)}
.statusbar.info{border-color:var(--sb-info-border);background:var(--sb-info-bg)}
.status-item{display:flex;align-items:center;gap:6px}
.status-label{color:var(--muted)}
.statusbar.warn .status-label{color:var(--sb-warn-label)}
.statusbar.ok .status-label{color:var(--sb-ok-label)}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.sitem{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center}
.sitem .l{color:var(--muted);font-size:12px;margin-bottom:4px}
.sitem .v{font-size:18px;font-weight:600;color:var(--title)}
/* 回测精度面板：指标卡在上、说明脚注在下，整体更有序 */
.vmetrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px}
.vnote{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--muted);font-size:12px;line-height:1.7;text-align:left;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:10px}
.vnote b{color:var(--text);font-weight:600}
/* 排行表：名称列左对齐、代码超链接、可点击筛选的统计卡片 */
.name{text-align:left}
.codelink{color:var(--code-text);text-decoration:none;font-weight:600}
.codelink:hover{text-decoration:underline}
.sitem.clickable{cursor:pointer;transition:border-color .15s,box-shadow .15s}
.sitem.clickable:hover{border-color:var(--btn)}
.sitem.clickable.active{border-color:var(--btn);box-shadow:inset 0 0 0 2px var(--btn);background:var(--row-hover)}
.pos{color:var(--pos);font-weight:600}
.neg{color:var(--neg);font-weight:600}
.lock{color:var(--lock);font-weight:600}
.est{color:var(--est);font-style:italic}
/* 集思录式紧密表格：紧凑行高、仅底边线、首行+首列锁定 */
.tablebox{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:8px;overflow:auto;max-height:65vh}
table{border-collapse:collapse;width:100%;font-size:12px;table-layout:auto}
th,td{border:0;border-bottom:1px solid var(--border);padding:3px 5px;text-align:right;vertical-align:middle;white-space:nowrap}
th{background:var(--th-bg);color:var(--th-text);font-weight:600;text-align:center;position:sticky;top:0;z-index:3}
td:first-child{text-align:left;position:sticky;left:0;z-index:1;background:var(--panel)}
th:first-child{left:0;top:0;z-index:5}
tbody tr:hover td:first-child{background:var(--row-hover)}
.op-cell{width:64px;text-align:center;white-space:nowrap}
.sig-cell{white-space:nowrap;min-width:96px;text-align:center;line-height:1.3}
.ver{display:inline-block;margin-left:8px;font-size:12px;font-weight:600;color:var(--th-text);background:var(--th-bg);border-radius:999px;padding:1px 10px;vertical-align:middle}
tbody tr:hover{background:var(--row-hover)}
.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600;white-space:nowrap}
.note{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px;font-size:12px;line-height:1.7;color:var(--muted)}
.note ul{margin:6px 0;padding-left:18px}.note li{margin:3px 0}
#loading{color:var(--muted);padding:20px;text-align:center}
#err{color:var(--pos);padding:14px}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;color:var(--code-text)}
/* 响应式布局：窄屏（手机）自适应 */
@media (max-width:760px){
  body{padding:12px;padding-top:max(82px,env(safe-area-inset-top))}
  /* 手机端顶栏导航拆两行（每行约5个链接），不再横向滚动 */
  .topnav{flex-wrap:wrap;overflow-x:visible;gap:5px;padding:6px 8px}
  .topnav .navlink{padding:4px 8px;font-size:12px}
  .topbar{flex-direction:row;align-items:flex-start;gap:8px}
  .top-actions{align-self:stretch;flex-wrap:wrap;gap:6px;width:100%}
  .top-actions .theme-btn,.top-actions a.theme-btn{flex:0 0 auto}
  .theme-btn{align-self:flex-start}
  body{overflow-x:hidden}
  .panel{flex-direction:column;align-items:stretch;gap:10px}
  .field{width:100%}
  .field input,.field textarea,.field select{width:100%}
  button:not(.arb-exp-btn):not(.theme-mini){width:100%}
  .fund-title{margin-left:0;margin-top:2px;font-size:18px}
  h1{font-size:18px}
  .sub{font-size:12px}
  .summary{grid-template-columns:repeat(2,1fr)}
  .sitem .v{font-size:16px}
  .statusbar{font-size:12px;gap:8px}
  .tablebox{padding:4px}
  th,td{padding:2px 3px;font-size:11px}
  #tbl .grid th, #tbl .grid td{padding:2px 3px;font-size:11px}
}
@media (max-width:420px){
  .summary{grid-template-columns:1fr}
}
/* ===== 近5日入选统计表（口袋支点/TOP/可转债）===== */
.histbox{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;margin:12px 0}
.histbox h3{font-size:12.5px;margin:2px 0 8px;color:var(--title);white-space:nowrap}
.histtbl{font-size:11.5px;table-layout:auto;width:max-content;min-width:100%;border-collapse:collapse;white-space:nowrap}
.histtbl th{background:#1f6feb;color:#fff;font-weight:700;padding:5px 7px;position:sticky;top:0;z-index:3;text-align:center;cursor:pointer;user-select:none}
.histtbl td:first-child{text-align:left}
.histtbl td.l{text-align:left}
.histtbl td{padding:4px 7px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}
.histtbl tbody tr:hover td{background:var(--row-hover)}
.histtbl .pos{color:var(--pos);font-weight:600}
.histtbl .neg{color:var(--neg);font-weight:600}
.histtbl .codelink{color:var(--code-text);text-decoration:none;font-weight:600}
.histtbl .codelink:hover{text-decoration:underline}
.hist-empty{color:var(--muted);font-size:12px;padding:12px;text-align:center}
"""
PAGE_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><script>(function(){try{var h=new Date().getHours(),t=localStorage.getItem("arb_theme")||((h>=18||h<6)?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>LOF/ETF 套利数据看板</title>
<style>""" + COMMON_CSS + r"""</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>LOF / ETF 基金套利数据看板 <span class="ver">V1.3</span></h1>
    <div class="sub">填基金代码 → 拉取净值/价格/标的/汇率/申购状态，自动算溢价率与套利信号。估算固定用 30 个交易日，界面默认显示近 10 个交易日。</div>
  </div>
  <button id="themeBtn" class="theme-mini" onclick="toggleTheme()" title="切换主题"><span id="themeIcon">🌙</span></button>
  <div class="topnav">
    <a class="brand" href="/sector"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="17" r="9" fill="none" stroke="#1f6feb" stroke-width="2.4"/><path d="M7 11 L16 5 L25 11" fill="none" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 23 L16 29 L25 23" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>套利工具平台</a>
    <a class="navlink" href="/sector">行业轮动</a><a class="navlink" href="/yupen">鱼盆模型</a>
    <a class="navlink active" href="/arb">套利看板</a>
    <a class="navlink" href="/ranking">排行表</a>
    <a class="navlink" href="/top">TOP套利</a>
    <a class="navlink" href="/pivot">口袋支点</a>
    <a class="navlink" href="/cb">可转债套利</a><a class="navlink" href="/watch">自选池</a>
    <span id="staleBadge" class="stale-badge" style="display:none"><span class="dot"></span>刷新中</span>
  </div>
</div>

<div class="tzline">本页所有行情/净值/汇率日期均按当前北京时间 <b id="clock">—</b><span id="btinline"></span></div>

<div id="fund-title" class="fund-title"></div>
<div class="tablebox" id="tablebox" style="display:none"><table id="tbl"></table></div>
<div id="baseinfo" class="baseinfo" style="display:none;margin:8px 0;color:#8b949e;font-size:13px"></div>
<div id="statusbar" class="statusbar" style="display:none"></div>
<div id="summary" class="summary"></div>
<div id="validate" class="summary" style="display:none"></div>
<div id="loading">加载中…</div>
<div id="err"></div>

<div class="panel">
  <div class="field"><label>基金代码</label><input id="code" value="162411"></div>
  <div class="field"><label>显示近 N 个交易日</label><input id="days" value="10" type="number" min="3" max="60" title="仅控制表格展示行数；估算/校准固定用 30 个交易日"></div>
  <div class="field"><label>溢价率阈值 %</label><input id="threshold" value="1.5" type="number" step="0.1" min="0.1" max="10"></div>
  <div class="field"><label>估值模式</label><select id="mode">
    <option value="auto">自动择优</option>
    <option value="index">指数代理</option>
    <option value="holdings">持仓估算</option>
  </select></div>
  <button id="btn" onclick="load()">查询</button>
</div>

<div class="note">
<b>说明</b>
<ul>
  <li><b>官方溢价</b> = (价格 - 净值) / 净值；<b>估值溢价</b> = (价格 - 估算净值) / 估算净值；<b>误差</b> = (估算净值 - 官方净值) / 官方净值。红=溢价/涨，绿=折价/跌。</li>
  <li>估算净值 = 锚定净值 × (标的_t / 标的_锚) × (汇率_t / 汇率_锚)，w 为仓位系数（按历史回测校准）。QDII 净值 T+1 公布，受时差/汇率/跟踪误差影响，仅供参考，非投资建议。</li>
  <li>申购状态是套利前提：<b>暂停申购</b> 无法做「申购→卖出」；<b>限大额</b> 受每日上限约束。</li>
</ul>
</div>
</div>
<script>
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentMode="auto";
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
function arbAutoTheme(){ var h=new Date().getHours(); return (h>=18||h<6)?'dark':'light'; }
function initTheme(){
  let t=arbAutoTheme();
  try{ t = localStorage.getItem('arb_theme') || arbAutoTheme(); }catch(e){}
  applyTheme(t);
}
initTheme();
window.addEventListener('DOMContentLoaded',function(){try{applyTheme(document.documentElement.getAttribute('data-theme')||'dark');}catch(e){}});
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

async function load(){
  const code=document.getElementById('code').value.trim();
  const days=document.getElementById('days').value.trim();
  const threshold=document.getElementById('threshold').value.trim();
  currentMode=document.getElementById('mode').value.trim();
  const btn=document.getElementById('btn');
  btn.disabled=true; document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('summary').innerHTML='';
  document.getElementById('statusbar').style.display='none';
  document.getElementById('fund-title').innerHTML='';
  try{
    let url='/api/data?code='+encodeURIComponent(code)+'&days='+encodeURIComponent(days)
          +'&threshold='+encodeURIComponent(threshold)+'&mode='+encodeURIComponent(currentMode);
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
  document.getElementById('staleBadge').style.display=(d&&d.stale)?'inline-flex':'none';
  const code=d.code, name=d.name||('基金'+code);
  // 友好提示：无数据（如代码非上市基金）时不留空白
  document.getElementById('err').textContent = (!d.rows || d.rows.length===0)
    ? '未查询到该基金的行情数据（代码可能非上市基金，或暂无可交易数据）。' : '';
  syncClock(d);
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
    barClass = (st==='开放申购'||st==='限大额申购')?'ok':'warn';
    let hint='';
    if(st==='暂停申购') hint='当前无法做「申购套利」，仅折价赎回套利可行（需看赎回状态）。';
    else if(st==='限大额申购') hint='可做申购套利，但受每日上限约束。';
    else if(st==='开放申购') hint='申购通道正常开放，可做「申购→卖出」溢价套利。';
    else hint='该基金仅场内交易（无个人现金申赎），无法做申赎套利，只能二级市场买卖。';
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
  // 摘要与估值基准块都要用 summary，先在此声明（避免 TDZ：估值基准块早于原声明处引用 s 会抛 ReferenceError）
  const s=d.summary||{};

  // 估值基准透明化（对标 haoetf「估值基准：SP500 7413.18 +0.02%」）：展示标的/模式/最新标的价
  const baseEl=document.getElementById('baseinfo');
  if(baseEl){
    let bhtml='<b>估值基准</b>：'+esc(d.underlying_label||'—');
    if(d.est_mode) bhtml+=' ｜ 模式：'+esc(d.est_mode);
    if(s.latest_xop!=null) bhtml+=' ｜ 最新标的价：'+Number(s.latest_xop).toFixed(4);
    baseEl.innerHTML=bhtml; baseEl.style.display='block';
  }

  // 摘要卡片（原油/油气基金才显示 XOP 收盘）
  const showOil = !!d.is_oil_gas;
  const summ=[
    ['最新场内价', fmtNum(s.latest_price,4)],
    ['最新估值溢价', fmtPct(s.latest_premium), s.latest_premium>0?'pos':(s.latest_premium<0?'neg':'')],
  ];
  if(d.use_fx!==false){
    summ.push(['最新 USD/CNY', fmtNum(s.latest_fx,4)]);
  }
  if(showOil){
    summ.splice(2,0,['最新 XOP 收盘', fmtNum(s.latest_xop,2)]);
  }
  document.getElementById('summary').innerHTML=summ.map(it=>
    '<div class="sitem"><div class="l">'+it[0]+'</div><div class="v '+(it[2]||'')+'">'+it[1]+'</div></div>'
  ).join('');

  // 表格：日期 价格 涨跌% 净值 净值涨跌幅 估算净值 估值溢价 误差 [汇率 汇率涨跌]
  //       （原油/油气基金追加 XOP收盘、XOP溢价） 申购状态 限购金额 套利信号
  const showFx = d.use_fx!==false;
  const head=['日期','价格','涨跌%','净值','净值涨跌幅','估算净值','估值溢价','误差'];
  if(showFx) head.push('汇率','汇率涨跌');
  if(showOil) head.push('XOP收盘','XOP溢价');
  head.push('申购状态','限购金额','套利信号');
  const limitTxt = c.purchase_limit!=null ? esc(c.purchase_limit+'元') : '—';
  const stSub=c.subscribe_status||'', stRed=c.redeem_status||'';
  const openSub=(stSub==='开放申购'||stSub==='限大额申购'), openRed=(stRed==='开放赎回');
  const sigOf=p=>{
    if(p==null) return ['—',''];
    if(p>d.threshold) return openSub?['溢价·可申购套利','pos']:['溢价·仅场内','lock'];
    if(p<-d.threshold) return openRed?['折价·可赎回套利','neg']:['折价·仅场内','lock'];
    return ['平价(观察)',''];
  };
  let rowsHtml=d.rows.map(r=>{
    const navCell = r.real_nav!=null? fmtNum(r.real_nav,4)
        : '<span class="est">'+fmtNum(r.est_nav,4)+'<br><small>净值待公布</small></span>';
    const sigR = r.est_premium!=null? r.est_premium : r.premium;
    const [sigTxt,sigC]=sigOf(sigR);
    let cells='<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+navCell+'</td>'
      +'<td class="'+cls(r.nav_change)+'">'+fmtPct(r.nav_change,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td class="'+cls(r.nav_err)+'">'+(r.nav_err!=null?fmtPct(r.nav_err,true):'—')+'</td>';
    if(showFx){
      cells += '<td>'+fmtNum(r.fx,4)+'</td>'
             + '<td class="'+cls(r.fx_change)+'">'+fmtPct(r.fx_change,true)+'</td>';
    }
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
  loadValidate(code);
}

async function loadValidate(code){
  const box=document.getElementById('validate');
  box.style.display='none'; box.innerHTML='';
  const bt=document.getElementById('btinline'); if(bt) bt.innerHTML='';
  try{
    const r=await fetch('/api/validate?code='+encodeURIComponent(code)+'&days=30&mode='+encodeURIComponent(currentMode));
    const d=await r.json();
    if(d.error) return;
    let comp='';
    if(d.idx_mae!=null && d.hld_mae!=null){
      comp=' · 自动择优→'+(d.mode==='holdings'?'持仓':'指数')
        +' · 指数MAE '+esc(d.idx_mae)+'% · 持仓MAE '+esc(d.hld_mae)+'%'
        +(d.mode==='holdings' && d.coverage!=null?(' · 覆盖 '+Math.round(d.coverage*100)+'%'):'');
    }else if(d.mode==='holdings'){
      comp=' · 模式=持仓估算'+(d.coverage!=null?(' · 覆盖 '+Math.round(d.coverage*100)+'%'):'');
    }else if(d.mode==='index'){
      comp=' · 模式=指数代理';
    }
    box.innerHTML='<div class="vmetrics">'
      +'<div class="sitem"><div class="l">估算精度 MAE</div><div class="v">±'+esc(d.mae)+'%</div></div>'
      +'<div class="sitem"><div class="l">中位数偏差</div><div class="v '+(d.median>0?'pos':(d.median<0?'neg':''))+'">'+fmtPct(d.median,true)+'</div></div>'
      +'<div class="sitem"><div class="l">RMSE</div><div class="v">'+esc(d.rmse)+'%</div></div>'
      +'</div>';
    // 回测参数说明并入顶部「北京时间」同一行，界面更整洁
    if(bt) bt.innerHTML=' ｜ 基于 <b>'+esc(d.count)+'</b> 个交易日回测 · w=<b>'+esc(Number(d.weight).toFixed(4))+'</b> · 滞后窗口 lag=<b>'+esc(d.lag)+'</b> · 标的=<b>'+esc(d.underlying)+'</b>'+comp+' · MAE 越小说明估算越稳。';
    box.style.display='block';
  }catch(e){}
}
document.getElementById('code').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('days').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('threshold').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
// 支持从排行表点击代码跳转：?code=XXXX 预填并自动查询
(function(){
  try{
    const p=new URLSearchParams(location.search);
    const c=(p.get('code')||'').trim();
    if(/^\d{6}$/.test(c)){ document.getElementById('code').value=c; }
  }catch(e){}
})();
// 默认基金：无 ?code 时取「LOF / ETF 基金溢价排行表(网页2)」按当前默认排序的第 1 名。
// 默认排序与网页2完全一致：① 申购状态(限大额>开放>暂停>其他) ② 估算溢价(或官方溢价)由高到低 ③ 成交额由大到小。
// 拉取失败回退 162411。_BASE 兼容独立 HTML(file://) 与线上同源两种场景（make_standalone 会注入 BASE）。
const _BASE = (typeof BASE !== 'undefined') ? BASE : '';
function statusRankTop(st){
  if(st==='限大额申购') return 0;
  if(st==='开放申购') return 1;
  if(st==='暂停申购') return 2;
  return 3;
}
async function loadTopDefault(){
  const input=document.getElementById('code');
  input.value='';
  document.getElementById('loading').style.display='block';
  document.getElementById('fund-title').innerHTML='正在加载今日溢价排行表榜首基金…';
  try{
    const r=await fetch(_BASE+'/api/ranking?threshold=1.5');
    const d=await r.json();
    if(d.rows && d.rows.length){
      const rows=d.rows.slice();
      rows.sort((a,b)=>{
        if(a.error && !b.error) return 1;
        if(!a.error && b.error) return -1;
        const s = statusRankTop(a.subscribe_status) - statusRankTop(b.subscribe_status);
        if(s!==0) return s;
        const ap = (a.est_premium!=null? a.est_premium : (a.premium!=null? a.premium : -Infinity));
        const bp = (b.est_premium!=null? b.est_premium : (b.premium!=null? b.premium : -Infinity));
        if(ap!==bp) return bp-ap;
        const at = (a.turnover!=null? a.turnover : -Infinity);
        const bt = (b.turnover!=null? b.turnover : -Infinity);
        return bt-at;
      });
      if(rows.length) input.value=rows[0].code;
    }
  }catch(e){}
  if(!input.value) input.value='162411';
  load();
}
// 北京时间实时时钟：server_ts 为后端 UTC 秒。用它校准浏览器时钟漂移(_calib)，
// 再用 Asia/Shanghai 显示——只转换一次时区，杜绝「+8h 后再 +8h」的双重偏移。
let _calib = 0; // 真实 UTC 与浏览器本地时钟的偏差(ms)：真实 UTC 时刻 = Date.now() + _calib
function syncClock(d){
  if(d && d.server_ts){ _calib = d.server_ts*1000 - Date.now(); tickClock(); }
}
function tickClock(){
  const el=document.getElementById('clock'); if(!el) return;
  const now = new Date(Date.now() + _calib);
  el.textContent = now.toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'});
}
setInterval(tickClock, 1000); tickClock();
// 打开界面：带 ?code= 直接查该基金；否则默认加载 TOP 套利榜第 1 名
(function(){
  const p=new URLSearchParams(location.search);
  const c=(p.get('code')||'').trim();
  if(/^\d{6}$/.test(c)){ load(); } else { loadTopDefault(); }
})();
// 注册 Service Worker，支持「添加到主屏幕 / 离线看壳」
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{
    navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err));
  });
}
</script>
<script src="watchlist.js"></script></body></html>"""
PAGE2_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><script>(function(){try{var h=new Date().getHours(),t=localStorage.getItem("arb_theme")||((h>=18||h<6)?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>LOF/ETF 基金溢价排行表</title>
<style>""" + COMMON_CSS + r"""
/* 界面二专属样式 */
.watchlist{width:100%;min-height:60px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px}
.add-row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.add-row .field{flex:1;min-width:120px}
.add-row button{padding:9px 14px}
/* 代码清单：挪到查询行右侧，点击展开为下拉编辑菜单（拉菜单） */
.codelist{margin-left:auto;flex:none;min-width:240px;max-width:520px;align-self:flex-end}
.codelist>summary{list-style:none;cursor:pointer;display:flex;flex-direction:column;gap:3px;
  background:var(--input-bg);border:1px solid var(--border);border-radius:8px;padding:8px 12px;
  color:var(--text);font-size:13px;user-select:none}
.codelist>summary::-webkit-details-marker{display:none}
.codelist>summary:hover{border-color:var(--btn)}
.codelist .cl-head{display:flex;align-items:center;gap:8px;font-weight:600;color:var(--title)}
.codelist .cl-head .chev{transition:transform .15s;color:var(--muted)}
.codelist[open] .cl-head .chev{transform:rotate(180deg)}
.codelist .cl-preview{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.codelist .cl-body{margin-top:10px;padding-top:10px;border-top:1px dashed var(--border)}
/* 排行表格：表头锁定 + 横向滚动显示全部列（手机端不再截断中间列） */
.rank-scroll{overflow:auto;max-height:74vh;-webkit-overflow-scrolling:touch}
.rank-scroll table{font-size:11.5px;table-layout:auto;width:max-content;min-width:100%}
.rank-scroll th,.rank-scroll td{padding:3px 5px;white-space:nowrap}
.rank-scroll th{position:sticky;top:0;z-index:3}
.summary2{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.rank-bar{background:var(--sb-info-bg);border:1px solid var(--sb-info-border);border-radius:10px;padding:12px 14px;display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-bottom:16px;font-size:13px}
.rank-bar .k{color:var(--muted)}
.rank-bar .v{font-weight:600;color:var(--title)}
.del-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:2px 8px;font-size:12px;border-radius:4px;cursor:pointer}
.del-btn:hover{background:#ff4d4f22;border-color:#ff4d4f55;color:#ff4d4f}
.pin-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:2px 7px;font-size:12px;border-radius:4px;cursor:pointer;margin-right:4px;opacity:.55;filter:grayscale(1)}
.pin-btn.on{opacity:1;filter:none;border-color:#ffc53d88;background:#ffc53d1a}
.pin-btn:hover{background:#ffc53d22;border-color:#ffc53d}
.op-cell .pin-btn{margin-right:4px}
.sort-hint{color:var(--muted);font-size:12px;margin-left:8px}
.toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:var(--btn);color:#fff;
  padding:8px 18px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:50}
.toast.show{opacity:1}
@media (max-width:760px){
  .summary2{grid-template-columns:repeat(2,1fr)}
  .add-row .field{width:100%}
  .codelist{margin-left:0;max-width:none;width:100%;align-self:stretch}
  .rank-scroll{max-height:66vh}
}
@media (max-width:420px){
  .summary2{grid-template-columns:1fr}
}
</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>LOF / ETF 基金溢价排行表 <span class="ver">V1.3</span></h1>
  </div>
  <button id="themeBtn" class="theme-mini" onclick="toggleTheme()" title="切换主题"><span id="themeIcon">🌙</span></button>
  <div class="topnav">
    <a class="brand" href="/sector"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="17" r="9" fill="none" stroke="#1f6feb" stroke-width="2.4"/><path d="M7 11 L16 5 L25 11" fill="none" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 23 L16 29 L25 23" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>套利工具平台</a>
    <a class="navlink" href="/sector">行业轮动</a><a class="navlink" href="/yupen">鱼盆模型</a>
    <a class="navlink" href="/arb">套利看板</a>
    <a class="navlink active" href="/ranking">排行表</a>
    <a class="navlink" href="/top">TOP套利</a>
    <a class="navlink" href="/pivot">口袋支点</a>
    <a class="navlink" href="/cb">可转债套利</a><a class="navlink" href="/watch">自选池</a>
    <span id="staleBadge" class="stale-badge" style="display:none"><span class="dot"></span>刷新中</span>
  </div>
</div>

<div class="tzline">本页所有行情/净值/汇率日期均按当前北京时间 <b id="clock">—</b></div>

<div class="tablebox rank-scroll" id="tablebox" style="display:none"><table id="tbl"></table></div>
<div class="rank-bar" id="rankbar" style="display:none"></div>
<div id="summary2" class="summary2"></div>
<div id="loading">加载中…</div>
<div id="err"></div>

<div class="panel">
  <div class="field"><label>查询日期</label><input id="rdate" type="date"></div>
  <div class="field"><label>溢价率阈值 %</label><input id="threshold" value="1.5" type="number" step="0.1" min="0.1" max="10"></div>
  <button id="btn" onclick="load()">查询排行</button>
  <details class="codelist" id="codelist">
    <summary>
      <span class="cl-head"><span id="clCount">基金清单</span><span class="chev">▾</span></span>
      <span class="cl-preview" id="clPreview"></span>
    </summary>
    <div class="cl-body">
      <div class="field" style="width:100%"><label>基金代码清单（逗号 / 空格 / 分号 / 换行分隔）</label>
        <textarea id="watchlist" class="watchlist" placeholder="例如：162411, 161130, 164824"></textarea></div>
      <div class="add-row">
        <div class="field"><label>添加基金代码</label><input id="addCode" placeholder="6 位基金代码"></div>
        <button onclick="addCode()">添加</button>
        <button onclick="saveList();toast('已保存设置')" style="background:var(--panel);color:var(--text);border:1px solid var(--border)">保存设置</button>
        <button onclick="resetList()" style="background:var(--panel);color:var(--text);border:1px solid var(--border)">恢复默认</button>
        <span class="sort-hint">默认申购状态优先、溢价高者居前；点击表头可切换排序</span>
      </div>
    </div>
  </details>
</div>

<div class="note">
<b>说明</b>
<ul>
  <li><b>官方溢价</b> = (价格 - 净值) / 净值；<b>估值溢价</b> = (价格 - 估算净值) / 估算净值。红=溢价，绿=折价。</li>
  <li>非交易日自动落到最近 &le; 该日的交易日。估算算法与套利看板一致；QDII（原油/黄金/纳指/标普/印度等）按海外标估算，国内基金取最近净值。</li>
  <li>增删代码后点「查询排行」刷新；「保存设置」可永久记住清单。</li>
</ul>
</div>
</div>
<script>
const DEFAULT_WATCHLIST=["513310","501018","518850","161226","159501","513520","513290","513120","513130","159985","160644","159545","159516","515880","159819","511130","159201","588200","159509","161128","511380","562800","159552","561550","520870","159530","515030","159326","159218","513750","513690","515220","162411","160719","501312","161130","161129","161124","160216","161125","160723","501225","501025","501012","160140"];
const LIST_VERSION="20250727";
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentRows=[], sortKey='premium', sortDesc=true, currentFilter=null, currentThreshold=1.5, currentMeta=null;

function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon'); const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){ applyTheme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light'); }
function arbAutoTheme(){ var h=new Date().getHours(); return (h>=18||h<6)?'dark':'light'; }
function initTheme(){ let t=arbAutoTheme(); try{ t=localStorage.getItem('arb_theme')||arbAutoTheme(); }catch(e){} applyTheme(t); }
initTheme();
window.addEventListener('DOMContentLoaded',function(){try{applyTheme(document.documentElement.getAttribute('data-theme')||'dark');}catch(e){}});
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function parseWatchlist(){
  const raw=document.getElementById('watchlist').value;
  return [...new Set(raw.split(/[,，;；\s]+/).map(x=>x.trim()).filter(x=>/^\d{6}$/.test(x)))];
}
function setWatchlist(arr){ document.getElementById('watchlist').value = arr.join('\n'); }
function refreshCodeListUI(){
  const list=parseWatchlist();
  const cnt=document.getElementById('clCount');
  const prev=document.getElementById('clPreview');
  if(cnt) cnt.textContent='基金 '+list.length+' 只';
  if(prev) prev.textContent = list.length? list.slice(0,14).join(' ') + (list.length>14?' …':'') : '（空）';
}
function loadList(){
  let list;
  try{
    const ver = localStorage.getItem('arb_ranking_list_version');
    if(ver === LIST_VERSION) list = JSON.parse(localStorage.getItem('arb_ranking_list'));
  }catch(e){}
  if(!Array.isArray(list) || list.length===0){ list = DEFAULT_WATCHLIST; saveList(); }
  setWatchlist(list);
  refreshCodeListUI();
}
function saveList(){ localStorage.setItem('arb_ranking_list', JSON.stringify(parseWatchlist())); localStorage.setItem('arb_ranking_list_version', LIST_VERSION); }

// 置顶（钉选）状态：localStorage 持久化，数组顺序即置顶排列顺序
let pins=[];
function loadPins(){ try{ const p=JSON.parse(localStorage.getItem('fundarb_pins')); if(Array.isArray(p)) pins=p.filter(x=>typeof x==='string'); }catch(e){} }
function savePins(){ try{ localStorage.setItem('fundarb_pins', JSON.stringify(pins)); }catch(e){} }
function togglePin(code){
  const i=pins.indexOf(code);
  if(i>=0) pins.splice(i,1); else pins.push(code);
  savePins(); renderBody();
}
function clearPins(){ pins=[]; savePins(); renderBody(); }
function addCode(){
  const inp=document.getElementById('addCode'); const c=inp.value.trim();
  if(!/^\d{6}$/.test(c)){ alert('请输入 6 位基金代码'); return; }
  const list=parseWatchlist();
  if(list.includes(c)){ alert('该代码已在清单中'); inp.value=''; return; }
  list.push(c); setWatchlist(list); saveList(); refreshCodeListUI(); inp.value='';
  load();
}
function removeCode(c){
  const list=parseWatchlist().filter(x=>x!==c); setWatchlist(list); saveList(); refreshCodeListUI(); load();
}
function resetList(){ setWatchlist(DEFAULT_WATCHLIST); saveList(); refreshCodeListUI(); load(); }
function toast(msg){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._tm); t._tm=setTimeout(()=>t.classList.remove('show'), 1600);
}

function today(){ const s=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); return s.replace(/\//g,'-'); }
function initDate(){
  const d=document.getElementById('rdate');
  d.value = today();
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
    currentRows=d.rows||[]; sortKey='__default__'; sortDesc=true; render(d);
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none'; btn.disabled=false;
  }
}

function statusRank(st){
  if(st==='限大额申购') return 0;
  if(st==='开放申购') return 1;
  if(st==='暂停申购') return 2;
  return 3;
}
function defaultSort(){
  sortKey='__default__'; sortDesc=true;
  currentRows.sort((a,b)=>{
    if(a.error && !b.error) return 1;
    if(!a.error && b.error) return -1;
    const s = statusRank(a.subscribe_status) - statusRank(b.subscribe_status);
    if(s!==0) return s;
    const ap = (a.est_premium!=null? a.est_premium : (a.premium!=null? a.premium : -Infinity));
    const bp = (b.est_premium!=null? b.est_premium : (b.premium!=null? b.premium : -Infinity));
    if(ap!==bp) return bp-ap;
    const at = (a.turnover!=null? a.turnover : -Infinity);
    const bt = (b.turnover!=null? b.turnover : -Infinity);
    return bt-at;
  });
  renderBody();
}
function sortRows(key){
  if(sortKey===key) sortDesc=!sortDesc; else { sortKey=key; sortDesc=true; }
  const isStr = ['code','name','date','subscribe_status','signal'].includes(key);
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
  document.getElementById('staleBadge').style.display=(meta&&meta.stale)?'inline-flex':'none';
  currentMeta=meta; currentThreshold=meta.threshold;
  syncClock(meta);
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
    +(minPrem?'<div class="status-item"><span class="k">最高折价</span><span class="v neg">'+fmtPct(minPrem.premium)+' '+esc(minPrem.name)+'</span></div>':'')
    +(pins.length?'<div class="status-item clickable" onclick="clearPins()" title="取消全部置顶"><span class="k">已置顶</span><span class="v" style="color:#ffc53d">'+pins.length+' 只 · 清除</span></div>':'');

  renderSummary();
  defaultSort();
}

// 统计卡片：三项数值可点击筛选；再次点击或「清除筛选」取消
function renderSummary(){
  const meta=currentMeta; if(!meta) return;
  const rows=currentRows;
  const ok=rows.filter(r=>!r.error);
  const up=ok.filter(r=>r.premium>meta.threshold).length;
  const down=ok.filter(r=>r.premium<-meta.threshold).length;
  const sub=ok.filter(r=>['开放申购','限大额申购'].includes(r.subscribe_status)&&r.premium>meta.threshold).length;
  const card=(lbl,val,cls,type)=>'<div class="sitem clickable'+(currentFilter===type?' active':'')+'" onclick="setFilter(\''+type+'\')" title="点击筛选符合条件的基金"><div class="l">'+lbl+'</div><div class="v '+cls+'">'+val+'</div></div>';
  let html=[
    card('溢价 > '+meta.threshold+'%', up, 'pos', 'premium'),
    card('折价 < -'+meta.threshold+'%', down, 'neg', 'discount'),
    card('可申购套利', sub, '', 'subscribe'),
    '<div class="sitem"><div class="l">数据异常</div><div class="v">'+(rows.length-ok.length)+'</div></div>',
  ];
  if(currentFilter){
    html.push('<div class="sitem clickable active" onclick="setFilter(null)" title="清除筛选"><div class="l">清除筛选</div><div class="v">✕</div></div>');
  }
  document.getElementById('summary2').innerHTML=html.join('');
}

function applyFilter(r){
  if(r.error) return false;
  if(currentFilter==='premium')    return r.premium>currentThreshold;
  if(currentFilter==='discount')   return r.premium<-currentThreshold;
  if(currentFilter==='subscribe')  return ['开放申购','限大额申购'].includes(r.subscribe_status) && r.premium>currentThreshold;
  return true;
}

function setFilter(type){
  currentFilter = (currentFilter===type && type!==null) ? null : type;
  renderSummary();   // 刷新卡片高亮
  renderBody();      // 按筛选重绘表格
}

// 跳转套利看板（近10日）：线上 /arb?code=，file:// 独立包 fund_arb.html?code=
function arbHref(code){ code=String(code||'').replace(/^(sh|sz|bj)/i,''); return (location.protocol==='file:' ? 'fund_arb.html' : '/arb') + '?code=' + encodeURIComponent(code); }

function renderBody(){
  const head=[
    {k:'code',l:'代码'},{k:'name',l:'名称'},{k:'date',l:'日期'},
    {k:'price',l:'价格'},{k:'price_change',l:'涨幅%'},{k:'nav',l:'净值'},{k:'nav_date',l:'净值日期'},
    {k:'premium',l:'官方溢价'},{k:'est_nav',l:'估算净值'},{k:'est_premium',l:'估算溢价'},{k:'turnover',l:'成交额(万元)'},
    {k:'subscribe_status',l:'申购状态'},{k:'purchase_limit',l:'限购金额'},{k:'signal',l:'套利信号'},{k:'',l:'操作'}
  ];
  const hHtml=head.map(h=>{ const cls=(h.l==='操作')?' class="op-cell"':''; return h.k? '<th'+cls+' style="cursor:pointer" onclick="sortRows(\''+h.k+'\')" title="点击排序">'+esc(h.l)+'</th>' : '<th'+cls+'>'+esc(h.l)+'</th>'; }).join('');
  let rows = currentFilter ? currentRows.filter(applyFilter) : currentRows;
  // 置顶排序：被钉选的基金浮到表首（按 pins 数组顺序），其余保持当前排序在后
  if(pins.length){
    const pinnedSet=new Set(pins); const pinned=[], unpinned=[];
    for(const r of rows){ if(!r.error && pinnedSet.has(r.code)) pinned.push(r); else unpinned.push(r); }
    pinned.sort((a,b)=> pins.indexOf(a.code)-pins.indexOf(b.code));
    rows = pinned.concat(unpinned);
  }
  const rowsHtml=rows.map(r=>{
    if(r.error) return '<tr><td>'+esc(r.code)+'</td><td colspan="14" style="text-align:left;color:var(--muted)">'+esc(r.name)+' — '+esc(r.error)+'</td></tr>';
    const st=r.subscribe_status||''; const stCol=STATUS_COLORS[st]||'#8c8c8c';
    const limitTxt = r.purchase_limit!=null ? esc(r.purchase_limit+'元') : '—';
    const sigC = r.signal_cls==='premium'?'pos':(r.signal_cls==='discount'?'neg':((r.signal_cls==='premium_lock'||r.signal_cls==='discount_lock')?'lock':''));
    return '<tr>'
      +'<td class="code"><a class="codelink" href="'+arbHref(r.code)+'">'+esc(r.code)+'</a></td>'
      +'<td class="name" title="'+esc(r.name)+'"><a class="codelink" href="'+arbHref(r.code)+'">'+esc(r.short||r.name)+'</a></td>'
      +'<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+fmtNum(r.nav,4)+'</td>'
      +'<td>'+esc(r.nav_date||'—')+'</td>'
      +'<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td>'+(r.turnover!=null? Number(r.turnover).toLocaleString('zh-CN',{maximumFractionDigits:0}) : '—')+'</td>'
      +'<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st||'—')+'</span></td>'
      +'<td>'+limitTxt+'</td>'
      +'<td class="'+sigC+' sig-cell">'+esc(r.signal)+'</td>'
      +'<td class="op-cell"><button class="pin-btn'+(pins.includes(r.code)?' on':'')+'" onclick="togglePin(\''+esc(r.code)+'\')" title="置顶/取消置顶">📌</button><button class="del-btn" onclick="removeCode(\''+esc(r.code)+'\')" title="移除">×</button></td>'
      +'</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML='<tr>'+hHtml+'</tr>'+rowsHtml;
  document.getElementById('tablebox').style.display='block';
}

// 北京时间实时时钟：server_ts 为后端 UTC 秒。用它校准浏览器时钟漂移(_calib)，
// 再用 Asia/Shanghai 显示——只转换一次时区，杜绝「+8h 后再 +8h」的双重偏移。
let _calib = 0; // 真实 UTC 与浏览器本地时钟的偏差(ms)：真实 UTC 时刻 = Date.now() + _calib
function syncClock(d){
  if(d && d.server_ts){ _calib = d.server_ts*1000 - Date.now(); tickClock(); }
}
function tickClock(){
  const el=document.getElementById('clock'); if(!el) return;
  const now = new Date(Date.now() + _calib);
  el.textContent = now.toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'});
}
setInterval(tickClock, 1000); tickClock();
loadList(); loadPins(); initDate(); load();
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{ navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err)); });
}
</script>
<script src="watchlist.js"></script></body></html>"""
PAGE3_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><script>(function(){try{var h=new Date().getHours(),t=localStorage.getItem("arb_theme")||((h>=18||h<6)?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>LOF TOP 套利榜</title>
<style>""" + COMMON_CSS + r"""
.rank-scroll{overflow:auto;max-height:74vh;-webkit-overflow-scrolling:touch}
.rank-scroll table{font-size:11.5px;table-layout:auto;width:max-content;min-width:100%}
.rank-scroll th,.rank-scroll td{padding:3px 5px;white-space:nowrap}
.rank-scroll th{position:sticky;top:0;z-index:3}
.summary2{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.rank-bar{background:var(--sb-info-bg);border:1px solid var(--sb-info-border);border-radius:10px;padding:12px 14px;display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-bottom:16px;font-size:13px}
.rank-bar .k{color:var(--muted)}
.rank-bar .v{font-weight:600;color:var(--title)}
@media (max-width:760px){
  .summary2{grid-template-columns:repeat(2,1fr)}
  .rank-scroll{max-height:66vh}
}
@media (max-width:420px){ .summary2{grid-template-columns:1fr} }
</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>LOF TOP 套利榜 <span class="ver">V1.3</span></h1>
  </div>
  <button id="themeBtn" class="theme-mini" onclick="toggleTheme()" title="切换主题"><span id="themeIcon">🌙</span></button>
  <div class="topnav">
    <a class="brand" href="/sector"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="17" r="9" fill="none" stroke="#1f6feb" stroke-width="2.4"/><path d="M7 11 L16 5 L25 11" fill="none" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 23 L16 29 L25 23" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>套利工具平台</a>
    <a class="navlink" href="/sector">行业轮动</a><a class="navlink" href="/yupen">鱼盆模型</a>
    <a class="navlink" href="/arb">套利看板</a>
    <a class="navlink" href="/ranking">排行表</a>
    <a class="navlink active" href="/top">TOP套利</a>
    <a class="navlink" href="/pivot">口袋支点</a>
    <a class="navlink" href="/cb">可转债套利</a><a class="navlink" href="/watch">自选池</a>
    <span id="staleBadge" class="stale-badge" style="display:none"><span class="dot"></span>刷新中</span>
  </div>
</div>

<div class="tzline">本页所有行情/净值/汇率日期均按当前北京时间 <b id="clock">—</b></div>

<div class="tablebox rank-scroll" id="tablebox" style="display:none"><table id="tbl"></table></div>
<div class="rank-bar" id="rankbar" style="display:none"></div>
<div id="summary2" class="summary2"></div>
<div id="loading">加载中…（全市场扫描较慢，请稍候）</div>
<div id="err"></div>

<div class="panel">
  <div class="field"><label>查询日期</label><input id="rdate" type="date"></div>
  <div class="field"><label>溢价阈值 %</label><input id="threshold" value="1.5" type="number" step="0.1" min="0.1" max="10"></div>
  <div class="field"><label>折价阈值 %</label><input id="dgate" value="-2" type="number" step="0.1" min="-10" max="-0.1"></div>
  <button id="btn" onclick="load()">扫描全市场</button>
  <span class="sort-hint" style="color:var(--muted);font-size:12px">首次扫描约 30~90 秒（全市场取数），10 分钟内重复查询秒回。</span>
</div>

<div class="histbox" id="topHist">
  <h3>近 5 个交易日溢价套利入选</h3>
  <div id="topHistBody"></div>
</div>

<div class="note">
<b>说明</b>
<ul>
  <li>全市场 LOF 自动扫描 → 粗筛（可交易+非债基+规模≥1亿+有净值）→ 精算估算溢价 → 终筛（申赎/限购/阈值）→ 默认排序：① 申购状态（限大额申购 → 开放申购 靠前）② 估算溢价由高到低 ③ 成交额由大到小。估算算法与排行表一致。</li>
  <li><b>粗筛条件（同时满足）</b>：① 当天 A 股场内可交易（有行情且有成交）· ② 非债基（剔除债基/含债/固收类型）· ③ 二级市场可交易规模（东财场内流通市值）≥ 1 亿元 · ④ 有最新净值。终筛再加：⑤ 限购 &gt; 1 元或不限购（暂停申购不入选）· ⑥ 估算溢价 ≥ 溢价阈值 或 估算溢价 &lt; 折价阈值且开放赎回。</li>
  <li><b>成交额</b>：默认排序第③位的成交额列反映流动性（来源腾讯当日行情字段[37]；盘前查看即为上一交易日全量成交）。</li>
  <li><b>估算溢价</b> = (价格 - 估算净值) / 估算净值；QDII 按海外标的+汇率修正，国内基金取最近净值。红=溢价，绿=折价。</li>
  <li>「暂停申购」不属于可申购状态（开放申购 / 限大额申购），不满足条件③，即使深折价也不入榜（条件为同时满足）。</li>
  <li>二级市场可交易规模取东财场内流通市值（场内规模），门槛 ≥ 1 亿元；限购金额取东财场内基金表当日数据。榜单仅供参考，非投资建议。</li>
</ul>
</div>
</div>
<script>
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentRows=[], sortKey='abs_est', sortDesc=true, currentFilter=null, currentMeta=null, currentThreshold=1.5, currentDgate=-2;
// 近5日 TOP 溢价套利入选统计表
let topHistKey='date', topHistDesc=false;
function topHistSort(k){ if(topHistKey===k) topHistDesc=!topHistDesc; else { topHistKey=k; topHistDesc=true; } renderTopHist(); }
function topHistCell(k,l){ return '<th class="'+(k==='code'||k==='name'?'l':'')+'" onclick="topHistSort(\''+k+'\')" title="点击排序">'+l+'</th>'; }
async function loadTopHist(){
  const box=document.getElementById('topHist');
  try{
    const r=await fetch('/api/history?type=top&days=5&t='+Date.now());
    const d=await r.json();
    window._topHistRows=d.rows||[];
    renderTopHist();
  }catch(e){ if(box) box.innerHTML='<div class="hist-empty">统计表加载失败：'+e.message+'</div>'; }
}
function renderTopHist(){
  const box=document.getElementById('topHistBody'); if(!box) return;
  const rows=(window._topHistRows||[]).slice();
  const latest={};
  (currentRows||[]).forEach(function(r){ latest[r.code]={price:r.price, nav:r.nav}; });
  rows.forEach(function(r){
    r._cur=(latest[r.code]&&latest[r.code].price)||null;
    r._nav=(latest[r.code]&&latest[r.code].nav)||null;
    r._pchg=(r._cur!=null&&r.price)?(r._cur-r.price)/r.price*100:null;
    r._nchg=(r._nav!=null&&r.nav)?(r._nav-r.nav)/r.nav*100:null;
  });
  const numKeys=['price','nav','_cur','_nav','_pchg','_nchg'];
  rows.sort(function(a,b){ var av=a[topHistKey],bv=b[topHistKey]; if(av==null&&bv==null)return 0; if(av==null)return 1; if(bv==null)return -1; if(numKeys.indexOf(topHistKey)>=0) return topHistDesc?(bv-av):(av-bv); return topHistDesc?String(bv).localeCompare(String(av),'zh'):String(av).localeCompare(String(bv),'zh'); });
  if(!rows.length){ box.innerHTML='<div class="hist-empty">暂无近 5 日溢价套利入选记录</div>'; return; }
  const head=topHistCell('date','入选日期')+topHistCell('code','代码')+topHistCell('name','名称')+topHistCell('price','入选日价格')+topHistCell('nav','入选日净值')+topHistCell('_cur','最新价')+topHistCell('_nav','最新净值')+topHistCell('_pchg','价格累计涨跌')+topHistCell('_nchg','净值累计涨跌');
  box.innerHTML='<table class="histtbl"><thead><tr>'+head+'</tr></thead><tbody>'+rows.map(function(r){
    const pcls=(r._pchg==null)?'':(r._pchg>=0?'pos':'neg');
    const ncls=(r._nchg==null)?'':(r._nchg>=0?'pos':'neg');
    const plain=String(r.code||'').replace(/^(sh|sz|bj)/i,'');
    return '<tr><td>'+esc(r.date)+'</td><td><a class="codelink" href="'+(location.protocol==='file:'?'fund_arb.html':'/arb')+'?code='+plain+'" target="_blank">'+esc(r.code)+'</a></td><td class="l">'+esc(r.name)+'</td><td>'+fmtNum(r.price)+'</td><td>'+fmtNum(r.nav)+'</td><td>'+fmtNum(r._cur)+'</td><td>'+fmtNum(r._nav)+'</td><td class="'+pcls+'">'+fmtPct(r._pchg)+'</td><td class="'+ncls+'">'+fmtPct(r._nchg)+'</td></tr>';
  }).join('')+'</tbody></table>';
}
function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon'); const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){ applyTheme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light'); }
function arbAutoTheme(){ var h=new Date().getHours(); return (h>=18||h<6)?'dark':'light'; }
function initTheme(){ let t=arbAutoTheme(); try{ t=localStorage.getItem('arb_theme')||arbAutoTheme(); }catch(e){} applyTheme(t); }
initTheme();
window.addEventListener('DOMContentLoaded',function(){try{applyTheme(document.documentElement.getAttribute('data-theme')||'dark');}catch(e){}});
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function today(){ const s=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); return s.replace(/\//g,'-'); }

async function load(){
  const date=document.getElementById('rdate').value;
  const threshold=document.getElementById('threshold').value;
  const dgate=document.getElementById('dgate').value;
  const btn=document.getElementById('btn'); btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('rankbar').style.display='none'; document.getElementById('summary2').innerHTML='';
  try{
    const url='/api/top?date='+encodeURIComponent(date)+'&threshold='+encodeURIComponent(threshold)+'&dgate='+encodeURIComponent(dgate);
    const r=await fetch(url); const d=await r.json();
    if(d.error){ throw new Error(d.error); }
    currentRows=d.rows||[]; sortKey='__default__'; sortDesc=true; render(d); loadTopHist();
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none'; btn.disabled=false;
  }
}

function statusRankTop(st){
  if(st==='限大额申购') return 0;
  if(st==='开放申购') return 1;
  return 2;
}
function defaultSort(){
  sortKey='__default__'; sortDesc=true;
  currentRows.sort((a,b)=>{
    const s = statusRankTop(a.subscribe_status) - statusRankTop(b.subscribe_status);
    if(s!==0) return s;
    const ap = (a.est_premium!=null? a.est_premium : (a.premium!=null? a.premium : -Infinity));
    const bp = (b.est_premium!=null? b.est_premium : (b.premium!=null? b.premium : -Infinity));
    if(ap!==bp) return bp-ap;
    const at = (a.turnover!=null? a.turnover : -Infinity);
    const bt = (b.turnover!=null? b.turnover : -Infinity);
    return bt-at;
  });
  renderBody();
}
// 统计卡片：溢价套利/折价套利可点击筛选（与网页2一致）；再次点击或「清除筛选」取消
function renderSummary(){
  const meta=currentMeta; if(!meta) return;
  const rows=currentRows;
  const est=r=> r.est_premium!=null?r.est_premium:(r.premium!=null?r.premium:null);
  const prem=rows.filter(r=>{const p=est(r); return p!=null && p>=meta.threshold;}).length;
  const disc=rows.filter(r=>{const p=est(r); return p!=null && p<meta.dgate && r.redeem_status==='开放赎回';}).length;
  const card=(lbl,val,cls,type)=>'<div class="sitem clickable'+(currentFilter===type?' active':'')+'" onclick="setFilter(\''+type+'\')" title="点击筛选符合条件的基金"><div class="l">'+lbl+'</div><div class="v '+cls+'">'+val+'</div></div>';
  let html=[
    card('溢价套利（≥'+meta.threshold+'%）', prem, 'pos', 'premium'),
    card('折价套利（<'+meta.dgate+'%且可赎回）', disc, 'neg', 'discount'),
    '<div class="sitem"><div class="l">入榜总数</div><div class="v">'+rows.length+'</div></div>',
  ];
  if(currentFilter){
    html.push('<div class="sitem clickable active" onclick="setFilter(null)" title="清除筛选"><div class="l">清除筛选</div><div class="v">✕</div></div>');
  }
  document.getElementById('summary2').innerHTML=html.join('');
}
function applyFilter(r){
  const est=r.est_premium!=null?r.est_premium:(r.premium!=null?r.premium:null);
  if(est==null) return false;
  if(currentFilter==='premium')  return est>=currentThreshold;
  if(currentFilter==='discount') return est<currentDgate && r.redeem_status==='开放赎回';
  return true;
}
function setFilter(type){
  currentFilter = (currentFilter===type && type!==null) ? null : type;
  renderSummary();
  renderBody();
}
function sortRows(key){
  if(sortKey===key) sortDesc=!sortDesc; else { sortKey=key; sortDesc=true; }
  const isStr = ['code','name','date','nav_date','subscribe_status','redeem_status','signal'].includes(key);
  currentRows.sort((a,b)=>{
    let av=a[sortKey], bv=b[sortKey];
    if(av==null && bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    if(isStr) return sortDesc? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    return sortDesc? (bv-av) : (av-bv);
  });
  renderBody();
}

function render(meta){
  document.getElementById('staleBadge').style.display=(meta&&meta.stale)?'inline-flex':'none';
  currentMeta=meta;
  // 同步查询阈值到全局，供点击筛选卡片时 applyFilter 使用（否则会沿用默认值 1.5/-2，与卡片标签不一致）
  currentThreshold=meta.threshold; currentDgate=meta.dgate;
  syncClock(meta);
  const rows=currentRows;
  const bar=document.getElementById('rankbar');
  bar.style.display='flex';
  bar.innerHTML='<div class="status-item"><span class="k">查询日期</span><span class="v">'+esc(meta.date)+'</span></div>'
    +'<div class="status-item"><span class="k">全市场 LOF</span><span class="v">'+esc(meta.universe)+' 只</span></div>'
    +'<div class="status-item"><span class="k">场内可交易</span><span class="v">'+esc(meta.tradable)+' 只</span></div>'
    +'<div class="status-item"><span class="k">剔除债基</span><span class="v">'+esc((meta.filter_trace&&meta.filter_trace.excluded_bond)||0)+' 只</span></div>'
    +'<div class="status-item"><span class="k">粗筛候选(非债基+规模≥1亿)</span><span class="v">'+esc(meta.candidates)+' 只</span></div>'
    +'<div class="status-item"><span class="k">入榜</span><span class="v">'+esc(meta.count)+' 只</span></div>';
  renderSummary();
  defaultSort();
}

// 跳转套利看板（近10日）：线上 /arb?code=，file:// 独立包 fund_arb.html?code=
function arbHref(code){ code=String(code||'').replace(/^(sh|sz|bj)/i,''); return (location.protocol==='file:' ? 'fund_arb.html' : '/arb') + '?code=' + encodeURIComponent(code); }

function renderBody(){
  const head=[
    {k:'code',l:'代码'},{k:'name',l:'名称'},{k:'date',l:'日期'},
    {k:'price',l:'价格'},{k:'price_change',l:'涨幅%'},{k:'nav',l:'净值'},{k:'nav_date',l:'净值日期'},
    {k:'premium',l:'官方溢价'},{k:'est_nav',l:'估算净值'},{k:'est_premium',l:'估算溢价'},{k:'index_change',l:'指数涨跌'},
    {k:'scale',l:'场内规模(亿)'},{k:'turnover',l:'成交额(万元)'},{k:'subscribe_status',l:'申购状态'},{k:'purchase_limit',l:'限购金额'},
    {k:'redeem_status',l:'赎回状态'},{k:'signal',l:'套利信号'}
  ];
  const hHtml=head.map(h=> h.k? '<th style="cursor:pointer" onclick="sortRows(\''+h.k+'\')" title="点击排序">'+esc(h.l)+'</th>' : '<th>'+esc(h.l)+'</th>').join('');
  const rows = currentFilter ? currentRows.filter(applyFilter) : currentRows;
  const rowsHtml=rows.map((r,i)=>{
    const st=r.subscribe_status||''; const stCol=STATUS_COLORS[st]||'#8c8c8c';
    const sigC = r.signal_cls==='premium'?'pos':(r.signal_cls==='discount'?'neg':((r.signal_cls==='premium_lock'||r.signal_cls==='discount_lock')?'lock':''));
    const rdCol = (r.redeem_status==='开放赎回')?'#52c41a':'#ff4d4f';
    return '<tr>'
      +'<td class="code"><a class="codelink" href="'+arbHref(r.code)+'">'+esc(r.code)+'</a></td>'
      +'<td class="name" title="'+esc(r.name)+'"><a class="codelink" href="'+arbHref(r.code)+'">'+esc(r.short||r.name)+'</a></td>'
      +'<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+fmtNum(r.nav,4)+'</td>'
      +'<td>'+esc(r.nav_date||'—')+'</td>'
      +'<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
    +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
    +'<td class="'+cls(r.index_change)+'">'+fmtPct(r.index_change,true)+'</td>'
    +'<td>'+(r.scale!=null? Number(r.scale).toFixed(2):'—')+'</td>'
      +'<td>'+(r.turnover!=null? Number(r.turnover).toLocaleString('zh-CN',{maximumFractionDigits:0}) : '—')+'</td>'
      +'<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st||'—')+'</span></td>'
      +'<td>'+esc(r.purchase_limit_text||'—')+'</td>'
      +'<td style="color:'+rdCol+'">'+esc(r.redeem_status||'—')+'</td>'
      +'<td class="'+sigC+' sig-cell">'+esc(r.signal||'—')+'</td>'
      +'</tr>';
  }).join('');
  const emptyMsg = currentFilter ? '当前筛选条件下没有符合条件的 LOF 基金' : '当前没有满足全部四个条件的 LOF 基金';
  document.getElementById('tbl').innerHTML='<tr>'+hHtml+'</tr>'+(rows.length? rowsHtml : '<tr><td colspan="17" style="text-align:center;color:var(--muted);padding:18px">'+emptyMsg+'</td></tr>');
  document.getElementById('tablebox').style.display='block';
}

// 北京时间实时时钟（与其余页面一致：server_ts 校准 + Asia/Shanghai 单次转换）
let _calib = 0;
function syncClock(d){ if(d && d.server_ts){ _calib = d.server_ts*1000 - Date.now(); tickClock(); } }
function tickClock(){
  const el=document.getElementById('clock'); if(!el) return;
  const now = new Date(Date.now() + _calib);
  el.textContent = now.toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'});
}
setInterval(tickClock, 1000); tickClock();
(function(){ const d=document.getElementById('rdate'); d.value=today(); })();
load();
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{ navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err)); });
}
</script>
<script src="watchlist.js"></script></body></html>"""
PAGE4_HTML = (
    '<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><script>(function(){try{var h=new Date().getHours(),t=localStorage.getItem("arb_theme")||((h>=18||h<6)?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n<meta name="theme-color" content="#0d1117">\n<link rel="manifest" href="/manifest.json">\n<link rel="apple-touch-icon" href="/icon-192.png">\n<title>口袋支点量化选股 V1.0</title>\n<style>'
    + COMMON_CSS
    + '</style></head><body>\n'
    + '<div class="wrap">\n<div class="topbar">\n  <div class="titles">\n    <h1>口袋支点量化选股 <span class="ver">V1.0</span></h1>\n    <div class="sub">基于欧奈尔 CAN SLIM · 米勒维尼趋势模板/VCP · 斯泰恩超级强势股，全市场扫描口袋支点买点。每交易日 14:50（收盘前 10 分钟）自动更新。</div>\n  </div>\n  <button id="themeBtn" class="theme-mini" onclick="toggleTheme()" title="切换主题"><span id="themeIcon">🌙</span></button>\n  <div class="topnav">\n    <a class="brand" href="/sector"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="17" r="9" fill="none" stroke="#1f6feb" stroke-width="2.4"/><path d="M7 11 L16 5 L25 11" fill="none" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 23 L16 29 L25 23" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>套利工具平台</a>\n    <a class="navlink" href="/sector">行业轮动</a><a class="navlink" href="/yupen">鱼盆模型</a>\n    <a class="navlink" href="/arb">套利看板</a>\n    <a class="navlink" href="/ranking">排行表</a>\n    <a class="navlink" href="/top">TOP套利</a>\n    <a class="navlink active" href="/pivot">口袋支点</a>\n    <a class="navlink" href="/cb">可转债套利</a><a class="navlink" href="/watch">自选池</a>\n    <span id="staleBadge" class="stale-badge" style="display:none"><span class="dot"></span>扫描中</span>\n  </div>\n</div>\n\n<div class="tzline">数据更新时间（北京时间）<b id="updated">—</b><span id="elapsedInfo"></span></div>\n\n<div class="tablebox" id="tablebox" style="display:none"><table id="tbl"></table></div><div id="statusbar" class="statusbar" style="display:none"></div>\n<div id="summary" class="summary"></div>\n<div id="loading">加载中…</div>\n<div id="err"></div>\n\n\n<div class="panel">\n  <div class="field"><label>最低评分</label><input id="minScore" value="0" type="number" min="0" max="100" step="5"></div>\n  <div class="field"><label>最低 RS 评级</label><input id="minRs" value="0" type="number" min="0" max="99" step="5"></div>\n  <div class="field"><label>趋势模板下限</label><select id="minTt">\n    <option value="0">不限</option>\n    <option value="6">≥ 6 条</option>\n    <option value="7">≥ 7 条</option>\n    <option value="8">8 条全过</option>\n  </select></div>\n  <div class="field"><label>信号分级</label><select id="fGrade">\n    <option value="">全部</option>\n    <option value="S">S 级（全优）</option>\n    <option value="A">A 级（模板全过）</option>\n    <option value="B">B 级</option>\n    <option value="C">C 级（观察）</option>\n  </select></div>\n  <button id="btn" onclick="applyFilter()">筛选</button>\n  <button id="rescanBtn" onclick="rescan()" style="background:var(--panel);color:var(--title);border:1px solid var(--border)">立即重扫</button>\n  <div id="pick-count" class="fund-title"></div>\n</div>\n\n<div class="histbox" id="pivotHist">\n  <h3>近 5 个交易日 A 级及以上入选</h3>\n  <div id="pivotHistBody"></div>\n</div>\n<div class="note">\n<b>方法论与用法</b>\n<ul>\n  <li><b>口袋支点</b>（Morales &amp; Kacher）：当日成交量 &gt; 过去 10 日所有<b>下跌日</b>的最大成交量，且收阳、实体阳线、收在振幅上半部、站上 50 日线、贴近 10 日线、未过度延伸、未跳空追高、非涨停 —— 共 13 条硬条件全过才算命中。</li>\n  <li><b>趋势模板 8 条</b>（Minervini 第二阶段）：现价 &gt; 150/200 日线、150 &gt; 200 日线、200 日线上行 1 个月、50 &gt; 150 &gt; 200 多头排列、现价 &gt; 50 日线、高于 52 周低点 30%、距 52 周高点 25% 内、RS ≥ 70。</li>\n  <li><b>评分权重</b>（2024-11~2026-07 全市场 32326 个信号回测标定）：趋势模板 40 + RS 22 + 支点质量 15 + VCP 10 + 距高点 8 + 行业 5。实证：趋势模板 8/8 超额 +2.22%，RS 80-90 超额 +2.05%，<b>大盘空头环境超额 -2.95%（择时优先级最高）</b>。</li>\n  <li><b>离场规则</b>：8% 硬止损（Minervini 铁律）+ 收盘跌破 50 日线离场，<b>不设固定止盈</b> —— 回测证明 25% 止盈会把最优组收益从 6.0% 砍到 4.5%。仓位按单笔 1% 风险预算反推。</li>\n  <li>大盘为<b>空仓/防御</b>时信号天然稀少，属纪律性表现，不是程序故障。本页为量化信号提示，不构成投资建议。</li>\n</ul>\n</div>\n</div>'
    + '<script>'
    + 'let RAW=null, POLL=null;\nconst GRADE_COLORS={"S":"#e6394a","A":"#fa8c16","B":"#1f6feb","C":"#8c8c8c"};\n\nfunction applyTheme(t){\n  document.documentElement.setAttribute(\'data-theme\', t);\n  const icon=document.getElementById(\'themeIcon\'), lbl=document.getElementById(\'themeLbl\');\n  if(icon) icon.textContent=(t===\'light\')?\'☀️\':\'🌙\';\n  if(lbl) lbl.textContent=(t===\'light\')?\'日间\':\'夜间\';\n  try{ localStorage.setItem(\'arb_theme\',t); }catch(e){}\n}\nfunction toggleTheme(){\n  applyTheme(document.documentElement.getAttribute(\'data-theme\')===\'light\'?\'dark\':\'light\');\n}\nfunction arbAutoTheme(){ var h=new Date().getHours(); return (h>=18||h<6)?\'dark\':\'light\'; }\n(function(){ let t=arbAutoTheme(); try{ t=localStorage.getItem(\'arb_theme\')||arbAutoTheme(); }catch(e){} applyTheme(t); })();\n\nfunction esc(s){ return String(s==null?"":s).replace(/[&<>"\']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;"}[c])); }\nfunction fmtPct(v,plus){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+Number(v).toFixed(2)+"%"; }\nfunction cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }\nfunction fmtAmt(w){ if(w==null)return "—"; return w>=10000?(w/10000).toFixed(2)+"亿":Math.round(w)+"万"; }\n\n// 近5日 A级及以上入选统计表\nlet histSortKey=\'date\', histSortDesc=false;\nfunction histSort(k){ if(histSortKey===k) histSortDesc=!histSortDesc; else { histSortKey=k; histSortDesc=true; } renderPivotHist(); }\nfunction histCell(k,l){ return \'<th class="\'+(k===\'code\'||k===\'name\'?\'l\':\'\')+\'" onclick="histSort(\'+k+\')" title="点击排序">\'+l+\'</th>\'; }\nasync function loadPivotHist(){\n  const box=document.getElementById(\'pivotHist\');\n  try{\n    const r=await fetch(\'/api/history?type=pivot&days=5&t=\'+Date.now());\n    const d=await r.json();\n    window._histRows=d.rows||[];\n    renderPivotHist();\n  }catch(e){ if(box) box.innerHTML=\'<div class="hist-empty">统计表加载失败：\'+e.message+\'</div>\'; }\n}\nfunction fmtNum4(v){ if(v==null||isNaN(v)) return \'—\'; return Number(v).toFixed(4); }\nfunction fmtPct2(v){ if(v==null||isNaN(v)) return \'—\'; return (v>0?\'+\':\'\')+Number(v).toFixed(2)+\'%\'; }\nfunction renderPivotHist(){\n  const box=document.getElementById(\'pivotHistBody\'); if(!box) return;\n  const rows=(window._histRows||[]).slice();\n  const pm=(window._latestPivot&&window._latestPivot.pickMap)||{};\n  rows.forEach(function(r){ r._cur=(pm[r.code]&&pm[r.code].close)||null; r._chg=(r._cur!=null&&r.price)?(r._cur-r.price)/r.price*100:null; });\n  const numKeys=[\'price\',\'_cur\',\'_chg\'];\n  rows.sort(function(a,b){ var av=a[histSortKey],bv=b[histSortKey]; if(av==null&&bv==null)return 0; if(av==null)return 1; if(bv==null)return -1; if(numKeys.indexOf(histSortKey)>=0) return histSortDesc?(bv-av):(av-bv); return histSortDesc?String(bv).localeCompare(String(av),\'zh\'):String(av).localeCompare(String(bv),\'zh\'); });\n  if(!rows.length){ box.innerHTML=\'<div class="hist-empty">暂无近 5 日 A 级及以上入选记录</div>\'; return; }\n  const head=histCell(\'date\',\'入选日期\')+histCell(\'code\',\'代码\')+histCell(\'name\',\'名称\')+histCell(\'grade\',\'级别\')+histCell(\'price\',\'入选价\')+histCell(\'_cur\',\'最新价\')+histCell(\'_chg\',\'入选至今涨跌幅\');\n  box.innerHTML=\'<table class="histtbl"><thead><tr>\'+head+\'</tr></thead><tbody>\'+rows.map(function(r){\n    const chgCls=(r._chg==null)?\'\':(r._chg>=0?\'pos\':\'neg\');\n    const plain=String(r.code||\'\').replace(/^(sh|sz|bj)/i,\'\');\n    return \'<tr><td>\'+esc(r.date)+\'</td><td><a class="codelink" href="\'+(location.protocol===\'file:\'?\'fund_arb.html\':\'/arb\')+\'?code=\'+plain+\'" target="_blank">\'+esc(r.code)+\'</a></td><td class="l">\'+esc(r.name)+\'</td><td>\'+esc(r.grade)+\'</td><td>\'+fmtNum4(r.price)+\'</td><td>\'+fmtNum4(r._cur)+\'</td><td class="\'+chgCls+\'">\'+fmtPct2(r._chg)+\'</td></tr>\';\n  }).join(\'\')+\'</tbody></table>\';\n}\n\n\nasync function load(){\n  try{\n    const r=await fetch(\'/api/pivot?t=\'+Date.now());\n    const d=await r.json();\n    if(d.error) throw new Error(d.error);\n    RAW=d;\n    window._latestPivot={pickMap:{}};\n    (d.picks||[]).forEach(function(p){ window._latestPivot.pickMap[p.code]=p; });\n    render(d);\n    loadPivotHist();\n    // 扫描进行中 → 轮询进度\n    if(d.scanning){\n      document.getElementById(\'staleBadge\').style.display=\'inline-flex\';\n      if(!POLL) POLL=setInterval(load,4000);\n    }else{\n      document.getElementById(\'staleBadge\').style.display=\'none\';\n      if(POLL){ clearInterval(POLL); POLL=null; }\n    }\n  }catch(e){\n    document.getElementById(\'loading\').style.display=\'none\';\n    document.getElementById(\'err\').textContent=\'加载失败：\'+e.message;\n  }\n}\n\nfunction render(d){\n  document.getElementById(\'loading\').style.display=\'none\';\n  document.getElementById(\'err\').textContent=\'\';\n  document.getElementById(\'updated\').textContent=d.updated||\'—\';\n  const ei=document.getElementById(\'elapsedInfo\');\n  if(d.scanning){\n    const p=d.progress||{};\n    ei.textContent=\'\u3000｜\u3000正在扫描：\'+(p.phase||\'\')+\' \'+(p.done||0)+\'/\'+(p.total||0);\n  }else if(d.elapsed!=null){\n    ei.textContent=\'\u3000｜\u3000本次扫描耗时 \'+d.elapsed+\' 秒，覆盖 \'+((d.stats&&d.stats.universe)||0)+\' 只个股\';\n  }else{ ei.textContent=\'\'; }\n\n  // ---- 大盘状态条 ----\n  const m=d.market||{};\n  const bar=document.getElementById(\'statusbar\');\n  if(m.state){\n    const good=(m.state===\'进攻\'), bad=(m.state===\'空仓\'||m.state===\'防御\');\n    bar.className=\'statusbar \'+(good?\'ok\':(bad?\'warn\':\'info\'));\n    bar.style.display=\'flex\';\n    const col=good?\'#52c41a\':(bad?\'#ff4d4f\':\'#fa8c16\');\n    bar.innerHTML=\'<div class="status-item"><span class="status-label">大盘状态</span>\'\n      +\'<span class="badge" style="background:\'+col+\'22;color:\'+col+\';border:1px solid \'+col+\'55">\'+esc(m.state)+\'</span></div>\'\n      +\'<div class="status-item"><span class="status-label">市场健康度</span><span>\'+(m.score!=null?m.score:\'—\')+\' / 100</span></div>\'\n      +\'<div class="status-item"><span class="status-label">建议仓位上限</span><span>\'+(m.max_position!=null?m.max_position+\'%\':\'—\')+\'</span></div>\'\n      +\'<div class="status-item"><span class="status-label">25日分销日</span><span>\'+(m.dd_count!=null?m.dd_count+\' 个\':\'—\')+\'</span></div>\'\n      +\'<div class="status-item" style="margin-left:auto;color:var(--muted)">\'+esc(m.detail||\'\')+\'</div>\';\n  }else{ bar.style.display=\'none\'; }\n\n  // ---- 统计卡片（可点击筛选分级）----\n  const st=d.stats||{}, g=st.grade||{};\n  const cur=document.getElementById(\'fGrade\').value;\n  const cards=[[\'\',\'命中总数\',st.picks!=null?st.picks:0],\n               [\'S\',\'S 级（全优）\',g.S||0],[\'A\',\'A 级（模板全过）\',g.A||0],\n               [\'B\',\'B 级\',g.B||0],[\'C\',\'C 级（观察）\',g.C||0]];\n  document.getElementById(\'summary\').innerHTML=cards.map(function(x){\n    const on=(cur===x[0])?\' active\':\'\';\n    const c=GRADE_COLORS[x[0]];\n    return \'<div class="sitem clickable\'+on+\'" onclick="pickGrade(\\\'\'+x[0]+\'\\\')">\'\n      +\'<div class="l">\'+x[1]+\'</div><div class="v"\'+(c?\' style="color:\'+c+\'"\':\'\')+\'>\'+x[2]+\'</div></div>\';\n  }).join(\'\');\n\n  applyFilter();\n}\n\nfunction pickGrade(g){\n  document.getElementById(\'fGrade\').value=g;\n  render(RAW);\n}\n\nlet pivotSortKey=\'score\', pivotSortDesc=true;\n\nfunction pivotSortBy(key){ if(pivotSortKey===key) pivotSortDesc=!pivotSortDesc; else { pivotSortKey=key; pivotSortDesc=true; } applyFilter(); }\nfunction pivotHeadCell(k,l){ var arrow=(pivotSortKey===k)?(pivotSortDesc?\' ▼\':\' ▲\'):\'\'; return \'<th style=\\"cursor:pointer\\" onclick=\\"pivotSortBy(\\\'\'+k+\'\\\')\\" title=\\"点击排序\\">\'+l+arrow+\'</th>\'; }\nfunction pivotSorted(rows){ var numKeys=[\'score\',\'rs\',\'trend_pass\',\'close\',\'chg_pct\',\'vol_x\',\'off_high_pct\',\'plan_stop\',\'plan_pos\']; var numeric=numKeys.indexOf(pivotSortKey)>=0; return rows.slice().sort(function(a,b){ var av=a[pivotSortKey], bv=b[pivotSortKey]; if(av==null&&bv==null)return 0; if(av==null)return 1; if(bv==null)return -1; if(numeric)return pivotSortDesc?(bv-av):(av-bv); return pivotSortDesc?String(bv).localeCompare(String(av),\'zh\'):String(av).localeCompare(String(bv),\'zh\'); }); }\n\nfunction applyFilter(){\n  if(!RAW) return;\n  const minScore=parseFloat(document.getElementById(\'minScore\').value)||0;\n  const minRs=parseFloat(document.getElementById(\'minRs\').value)||0;\n  const minTt=parseInt(document.getElementById(\'minTt\').value)||0;\n  const fg=document.getElementById(\'fGrade\').value;\n  let rows=(RAW.picks||[]).filter(function(p){\n    return p.score>=minScore && p.rs>=minRs && p.trend_pass>=minTt && (!fg||p.grade===fg);\n  });\n  document.getElementById(\'pick-count\').innerHTML=rows.length+\' 只 <small>符合当前条件</small>\';\n\n  if(!rows.length){\n    document.getElementById(\'tablebox\').style.display=\'none\';\n    document.getElementById(\'err\').textContent=(RAW.scanning\n      ? \'首次扫描进行中，请稍候（全市场约需 3-6 分钟）…\'\n      : \'当前条件下无命中。大盘走弱时信号稀少属正常，可放宽筛选条件。\');\n    return;\n  }\n  document.getElementById(\'err\').textContent=\'\';\n\n  rows = pivotSorted(rows);\n  rows.forEach(function(p){ p.plan_stop=(p.plan&&p.plan.stop!=null)?p.plan.stop:null; p.plan_pos=(p.plan&&p.plan.pos_pct!=null)?p.plan.pos_pct:null; });\n  let html=\'<thead><tr>\' + pivotHeadCell(\'name\',\'名称/代码\') + pivotHeadCell(\'grade\',\'级别\') + pivotHeadCell(\'score\',\'评分\')\n    + pivotHeadCell(\'rs\',\'RS\') + pivotHeadCell(\'trend_pass\',\'模板\') + pivotHeadCell(\'close\',\'现价\')\n    + pivotHeadCell(\'chg_pct\',\'涨跌\') + pivotHeadCell(\'vol_x\',\'量能倍数\') + pivotHeadCell(\'off_high_pct\',\'距52周高\')\n    + pivotHeadCell(\'plan_stop\',\'止损\') + pivotHeadCell(\'plan_pos\',\'仓位\') + \'<th>详情</th></tr></thead><tbody>\';\n  rows.forEach(function(p,i){\n    const gc=GRADE_COLORS[p.grade]||\'#8c8c8c\';\n    html+=\'<tr>\'\n      +\'<td class="name"><b>\'+esc(p.name)+\'</b> <a class="codelink" href="https://gu.qq.com/\'+esc(p.symbol)+\'" target="_blank" rel="noopener">\'+esc(p.code)+\'</a></td>\'\n      +\'<td><span class="badge" style="background:\'+gc+\'22;color:\'+gc+\';border:1px solid \'+gc+\'55">\'+esc(p.grade||\'—\')+\'</span></td>\'\n      +\'<td><b>\'+p.score+\'</b></td>\'\n      +\'<td>\'+p.rs+\'</td>\'\n      +\'<td>\'+p.trend_pass+\'/8</td>\'\n      +\'<td>\'+p.close+\'</td>\'\n      +\'<td class="\'+cls(p.chg_pct)+\'">\'+fmtPct(p.chg_pct,true)+\'</td>\'\n      +\'<td>\'+p.vol_x+\'×</td>\'\n      +\'<td class="\'+cls(p.off_high_pct)+\'">\'+fmtPct(p.off_high_pct,false)+\'</td>\'\n      +\'<td>\'+(p.plan_stop==null?\'—\':p.plan_stop)+\'</td>\'\n      +\'<td>\'+(p.plan_pos==null?\'—\':p.plan_pos)+\'%</td>\'\n      +\'<td class="op-cell"><button style="padding:4px 10px;font-size:12px" onclick="toggleDetail(\'+i+\')">展开</button></td>\'\n      +\'</tr>\'\n      +\'<tr id="dt\'+i+\'" style="display:none"><td colspan="12" style="text-align:left;white-space:normal;padding:12px 14px;background:var(--row-hover)">\'\n      +detailHtml(p)+\'</td></tr>\';\n  });\n  document.getElementById(\'tbl\').innerHTML=html+\'</tbody>\';\n  document.getElementById(\'tablebox\').style.display=\'block\';\n  window.__rows=rows;\n}\n\nfunction detailHtml(p){\n  const tt=p.tt||{}, stine=p.stine||{}, pl=p.plan||{};\n  const mark=function(v){ return v?\'<span style="color:var(--neg)">✓</span>\':\'<span style="color:var(--muted)">✗</span>\'; };\n  let s=\'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">\';\n  // 趋势模板\n  s+=\'<div><b>Minervini 趋势模板 \'+p.trend_pass+\'/8</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\';\n  Object.keys(tt).forEach(function(k){ s+=mark(tt[k])+\' \'+esc(k)+\'<br>\'; });\n  s+=mark(p.rs>=70)+\' ⑧RS评级≥70（当前 \'+p.rs+\'）\';\n  s+=\'</div></div>\';\n  // 交易计划\n  s+=\'<div><b>交易计划（1% 风险预算）</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\'\n    +\'买入区间：<b>\'+pl.buy_low+\' ~ \'+pl.buy_high+\'</b><br>\'\n    +\'止损价：<b style="color:var(--pos)">\'+pl.stop+\'</b>（风险 \'+pl.risk_pct+\'%）<br>\'\n    +\'2R 目标：\'+pl.target2+\'\u30003R 目标：\'+pl.target3+\'<br>\'\n    +\'建议仓位：<b>\'+pl.pos_pct+\'%</b><br>\'\n    +\'离场：\'+esc(pl.exit_rule||\'\')\n    +\'</div></div>\';\n  // Stine + 关键指标\n  s+=\'<div><b>超级强势股（Stine）</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\';\n  Object.keys(stine).forEach(function(k){ s+=mark(stine[k])+\' \'+esc(k)+\'<br>\'; });\n  s+=\'</div></div>\';\n  s+=\'<div><b>关键指标</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\'\n    +\'支点质量：\'+p.pocket_quality+\' / 100<br>\'\n    +\'VCP：\'+(p.vcp?\'成立\':\'不成立\')+\'（\'+p.vcp_score+\' 分）<br>\'\n    +\'量能 / 50日均量：\'+p.vol_vs_ma50+\'×<br>\'\n    +\'距 52 周低点：+\'+p.up_from_low_pct+\'%<br>\'\n    +\'成交额：\'+fmtAmt(p.amount_wan)+\'\u3000换手：\'+p.turn_rate+\'%<br>\'\n    +\'流通市值：\'+p.float_mcap+\' 亿\'\n    +\'</div></div>\';\n  s+=\'</div>\';\n  if(p.reasons&&p.reasons.length){\n    s+=\'<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border);font-size:12px">\'\n      +\'<b>入选理由</b>：\'+p.reasons.map(esc).join(\' ｜ \')+\'</div>\';\n  }\n  return s;\n}\n\nfunction toggleDetail(i){\n  const el=document.getElementById(\'dt\'+i);\n  if(el) el.style.display=(el.style.display===\'none\')?\'table-row\':\'none\';\n}\n\nasync function rescan(){\n  const b=document.getElementById(\'rescanBtn\');\n  b.disabled=true; b.textContent=\'已触发…\';\n  try{\n    await fetch(\'/api/pivot?force=1&t=\'+Date.now());\n    document.getElementById(\'staleBadge\').style.display=\'inline-flex\';\n    if(!POLL) POLL=setInterval(load,4000);\n  }catch(e){}\n  setTimeout(function(){ b.disabled=false; b.textContent=\'立即重扫\'; },3000);\n}\n\n[\'minScore\',\'minRs\'].forEach(function(id){\n  document.getElementById(id).addEventListener(\'keydown\',function(e){ if(e.key===\'Enter\') applyFilter(); });\n});\n[\'minTt\',\'fGrade\'].forEach(function(id){\n  document.getElementById(id).addEventListener(\'change\',applyFilter);\n});\n\nload();\nsetInterval(function(){ if(!POLL) load(); }, 60000);\n\nif(\'serviceWorker\' in navigator){\n  window.addEventListener(\'load\',function(){\n    navigator.serviceWorker.register(\'/sw.js\').catch(function(err){ console.log(\'SW 注册失败：\',err); });\n  });\n}'
    + '</script>\n<script src="watchlist.js"></script></body></html>'
)
PAGE5_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><script>(function(){try{var h=new Date().getHours(),t=localStorage.getItem("arb_theme")||((h>=18||h<6)?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>可转债套利</title>
<style>""" + COMMON_CSS + r"""
/* ===== 可转债页专属样式（表格 / 卡片 / 角标）===== */
:root{--bg2:#0d1117;--link:#79c0ff}
:root[data-theme="light"]{--bg2:#f5f7fa;--link:#2563eb}
.grid{width:100%;border-collapse:collapse;font-size:12px;margin-top:0}
.grid th{padding:4px 6px;border-bottom:1px solid var(--border);text-align:center;white-space:nowrap}.grid td{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}
.grid thead th{color:var(--th-text);font-weight:600;background:var(--th-bg);text-align:center;position:sticky;top:0;z-index:3}
.grid thead th:first-child{left:0;top:0;z-index:5;background:var(--th-bg)}
.grid td:first-child{background:var(--panel)}
#tbl .grid tbody tr:hover td:first-child{background:var(--row-hover)}
.grid td.num{text-align:right;font-variant-numeric:tabular-nums}
.grid td.rank{text-align:center;color:var(--muted);width:34px}
.grid .pos{color:var(--pos);font-weight:600}
.grid .neg{color:var(--neg)}
.grid .codelink{color:var(--link);text-decoration:none}
.grid .codelink:hover{text-decoration:underline}
.grid .c-sub{color:var(--muted);font-size:11px;font-weight:400;margin-left:6px;font-variant-numeric:tabular-nums}
.badge.disc{background:rgba(22,163,74,.15);color:#16a34a}
.badge.crit{background:rgba(100,116,139,.18);color:var(--muted)}
.card{display:inline-block;min-width:84px;padding:10px 14px;margin:6px 8px 6px 0;border:1px solid var(--border);border-radius:10px;background:var(--bg2)}
.card-v{font-size:22px;font-weight:700}
.card-t{font-size:12px;color:var(--muted);margin-top:2px}
.card.clickable{cursor:pointer;transition:border-color .15s,box-shadow .15s}
.card.clickable:hover{border-color:var(--btn)}
.card.clickable.active{border-color:var(--btn);box-shadow:inset 0 0 0 2px var(--btn);background:var(--row-hover)}
.empty{padding:30px;text-align:center;color:var(--muted)}
.summary{margin:8px 0}
.ops{display:flex;align-items:center;gap:10px;margin:10px 0}
</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>可转债套利 <span class="ver">V1.0</span></h1>
    <div class="sub">转股溢价率 &lt; 0（折价）即具备"买入转债 + 融券卖空正股 + 转股"的折价套利条件；榜单按套利收益率降序取前 10。</div>
  </div>
  <button id="themeBtn" class="theme-mini" onclick="toggleTheme()" title="切换主题"><span id="themeIcon">🌙</span></button>
  <div class="topnav">
    <a class="brand" href="/sector"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="17" r="9" fill="none" stroke="#1f6feb" stroke-width="2.4"/><path d="M7 11 L16 5 L25 11" fill="none" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 23 L16 29 L25 23" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>套利工具平台</a>
    <a class="navlink" href="/sector">行业轮动</a><a class="navlink" href="/yupen">鱼盆模型</a>
    <a class="navlink" href="/arb">套利看板</a>
    <a class="navlink" href="/ranking">排行表</a>
    <a class="navlink" href="/top">TOP套利</a>
    <a class="navlink" href="/pivot">口袋支点</a>
    <a class="navlink active" href="/cb">可转债套利</a><a class="navlink" href="/watch">自选池</a>
  </div>
</div>
  <div id="tbl" class="tablebox"></div>
  <div id="statusbar" class="statusbar"></div>
  <div id="summary" class="summary"></div>
  <div class="ops">
    <button class="btn" id="rescanBtn" onclick="rescan()">立即重扫</button>
    <span id="scanState" class="tzline"></span>
    <span class="tzline" style="margin-left:auto">每交易日 14:45 自动更新</span>
  </div>
  <div class="histbox" id="cbHist">
    <h3>近 5 个交易日严格折价信号</h3>
    <div id="cbHistBody"></div>
  </div>
  <div class="note">
    <b>套利逻辑</b>：转股溢价率 &lt; 0（折价）即具备"买入转债 + 融券卖空正股 + 转股"的折价套利条件，
    套利收益率(粗略，未扣费) = (转股价值 - 转债现价) / 转债现价。
    榜单按套利收益率降序取前 10；绿标为<b>严格折价</b>标的，灰标为<b>最接近折价的临界</b>标的（溢价率最低的正溢价）。
    <br><b>风险提示</b>：折价套利需正股可融券且承担 T+1 转股锁定期价格波动；转股价值基于实时行情，尾盘数据以 14:45 快照为准。本页仅供研究，非投资建议。
  </div>
</div>
<script>
var cbTimer = null;
function fmt(x, d){ if(x===null||x===undefined||x==="") return "-"; var n=Number(x); if(isNaN(n)) return x; return n.toFixed(d===undefined?2:d); }
// 近5日严格折价统计表
function escCb(s){ return String(s==null?"":s).replace(/[&<>"']/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]);}); }
var cbHistKey='date', cbHistDesc=false;
function cbHistSort(k){ if(cbHistKey===k) cbHistDesc=!cbHistDesc; else { cbHistKey=k; cbHistDesc=true; } renderCbHist(); }
function cbHistCell(k,l){ return '<th class="'+(k==='code'||k==='name'||k==='stock_name'?'l':'')+'" onclick="cbHistSort(\''+k+'\')" title="点击排序">'+l+'</th>'; }
async function loadCbHist(){
  var box=document.getElementById('cbHist');
  try{
    var r=await fetch('/api/history?type=cb&days=5&t='+Date.now());
    var d=await r.json();
    window._cbHistRows=d.rows||[];
    renderCbHist();
  }catch(e){ if(box) box.innerHTML='<div class="hist-empty">统计表加载失败：'+e.message+'</div>'; }
}
function fmtPctCb(v){ if(v==null||isNaN(v)) return '—'; return (v>0?'+':'')+Number(v).toFixed(2)+'%'; }
function renderCbHist(){
  var box=document.getElementById('cbHistBody'); if(!box) return;
  var rows=(window._cbHistRows||[]).slice();
  var latest={};
  if(cbLastData&&cbLastData.picks){ cbLastData.picks.forEach(function(p){ latest[p.code]={price:p.price, stock:p.stock_price}; }); }
  rows.forEach(function(r){
    r._cur=(latest[r.code]&&latest[r.code].price)||null;
    r._scur=(latest[r.code]&&latest[r.code].stock)||null;
    r._schg=(r._scur!=null&&r.stock_price)?(r._scur-r.stock_price)/r.stock_price*100:null;
  });
  var numKeys=['price','stock_price','convert_price','_cur','_scur','_schg'];
  rows.sort(function(a,b){ var av=a[cbHistKey],bv=b[cbHistKey]; if(av==null&&bv==null)return 0; if(av==null)return 1; if(bv==null)return -1; if(numKeys.indexOf(cbHistKey)>=0) return cbHistDesc?(bv-av):(av-bv); return cbHistDesc?String(bv).localeCompare(String(av),'zh'):String(av).localeCompare(String(bv),'zh'); });
  if(!rows.length){ box.innerHTML='<div class="hist-empty">暂无近 5 日严格折价信号</div>'; return; }
  var head=cbHistCell('code','转债代码')+cbHistCell('name','转债名称')+cbHistCell('date','入选日期')+cbHistCell('price','入选日转债价')+cbHistCell('_cur','最新转债价')+cbHistCell('stock_name','正股')+cbHistCell('stock_code','正股代码')+cbHistCell('stock_price','入选日正股价')+cbHistCell('convert_price','入选日转股价')+cbHistCell('_scur','最新正股价')+cbHistCell('_schg','转股累计涨跌');
  box.innerHTML='<table class="histtbl"><thead><tr>'+head+'</tr></thead><tbody>'+rows.map(function(r){
    var cls=(r._schg==null)?'':(r._schg>=0?'pos':'neg');
    var plain=String(r.code||'').replace(/^(sh|sz|bj)/i,'');
    var link=(location.protocol==='file:')?'fund_arb.html':'/arb';
    return '<tr><td><a class="codelink" href="'+link+'?code='+plain+'" target="_blank">'+escCb(r.code)+'</a></td><td class="l">'+escCb(r.name)+'</td><td>'+escCb(r.date)+'</td><td>'+fmt(r.price)+'</td><td>'+fmt(r._cur)+'</td><td class="l">'+escCb(r.stock_name)+'</td><td>'+escCb(r.stock_code)+'</td><td>'+fmt(r.stock_price)+'</td><td>'+fmt(r.convert_price)+'</td><td>'+fmt(r._scur)+'</td><td class="'+cls+'">'+fmtPctCb(r._schg)+'</td></tr>';
  }).join('')+'</tbody></table>';
}
function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  var icon=document.getElementById('themeIcon');
  var lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){
  var cur = (document.documentElement.getAttribute('data-theme')==='light') ? 'dark' : 'light';
  applyTheme(cur);
}
function arbAutoTheme(){ var h=new Date().getHours(); return (h>=18||h<6)?'dark':'light'; }
function initTheme(){
  var t=arbAutoTheme();
  try{ t = localStorage.getItem('arb_theme') || arbAutoTheme(); }catch(e){}
  applyTheme(t);
}
function load(){
  fetch("/api/cb?t=" + Date.now()).then(function(r){return r.json();}).then(render).catch(function(e){
    document.getElementById("tbl").innerHTML = '<div class="empty">加载失败：'+e+'</div>';
  });
}
var cbCurrentFilter = null;
var cbLastData = null;
// 表头排序状态（默认按套利收益率降序）
var cbSortKey = 'arb';
var cbSortDesc = true;
function cbSortBy(key){
  if(cbSortKey===key) cbSortDesc=!cbSortDesc; else { cbSortKey=key; cbSortDesc=true; }
  cbRenderTable();
}
function cbSortRows(arr){
  var numKeys = ['price','convert_value','premium','arb','double_low','convert_start'];
  var numeric = numKeys.indexOf(cbSortKey)>=0;
  return arr.slice().sort(function(a,b){
    var av=a[cbSortKey], bv=b[cbSortKey];
    if(av==null && bv==null) return 0;
    if(av==null) return 1;
    if(bv==null) return -1;
    if(numeric) return cbSortDesc ? (bv-av) : (av-bv);
    return cbSortDesc ? String(bv).localeCompare(String(av),'zh') : String(av).localeCompare(String(bv),'zh');
  });
}
function cbHeadCell(k, l){
  var arrow = (cbSortKey===k) ? (cbSortDesc?' ▼':' ▲') : '';
  return '<th style="cursor:pointer" onclick="cbSortBy(\''+k+'\')" title="点击排序">'+l+arrow+'</th>';
}
function render(d){
  cbLastData = d;
  var scanning = d.scanning;
  var modeTxt = {"strict":"严格折价","mixed":"折价+临界补足","fallback":"无折价(临界参考)"}[d.mode] || d.mode || "-";
  var sb = document.getElementById("statusbar");
  sb.innerHTML = '<span class="sitem">更新：'+(d.updated||"-")+'</span>'
    + '<span class="sitem">模式：'+modeTxt+'</span>'
    + (scanning ? '<span class="sitem stale-badge">扫描中…</span>' : '<span class="sitem">就绪</span>');
  document.getElementById("scanState").textContent = scanning ? ("扫描中 "+((d.progress&&d.progress.done)||0)+"/"+((d.progress&&d.progress.total)||0)) : "";
  document.getElementById("rescanBtn").disabled = scanning;
  cbRenderSummary();
  cbRenderTable();
  loadCbHist();
  if(cbTimer) clearTimeout(cbTimer);
  cbTimer = setTimeout(load, scanning ? 4000 : 60000);
}
// 统计卡片：单击筛选；再次单击或「清除筛选」取消（与其他页面一致）
function cbRenderSummary(){
  var d = cbLastData; if(!d) return;
  var s = d.stats || {};
  var cards = [
    {t:"全市场可转债", v:s.universe||0, type:null},
    {t:"严格折价", v:s.discount||0, type:"discount"},
    {t:"榜单", v:d.total_picks||0, type:null}
  ];
  var html = cards.map(function(c){
    var active = (cbCurrentFilter===c.type && c.type!==null) ? " active" : "";
    return '<div class="card clickable'+active+'" onclick="cbSetFilter('+(c.type===null?'null':"'"+c.type+"'")+')" title="点击筛选 / 再次点击取消"><div class="card-v">'+c.v+'</div><div class="card-t">'+c.t+'</div></div>';
  }).join("");
  if(cbCurrentFilter){
    html += '<div class="card clickable active" onclick="cbSetFilter(null)" title="清除筛选"><div class="card-v">✕</div><div class="card-t">清除筛选</div></div>';
  }
  document.getElementById("summary").innerHTML = html;
}
function cbSetFilter(type){
  cbCurrentFilter = (cbCurrentFilter===type && type!==null) ? null : type;
  cbRenderSummary();
  cbRenderTable();
}
function cbRenderTable(){
  var d = cbLastData; if(!d) return;
  var picks = d.picks||[];
  var view = (cbCurrentFilter==="discount") ? picks.filter(function(p){ return p.is_discount; }) : picks;
  var tbl = document.getElementById("tbl");
  if(!view.length){
    tbl.innerHTML = '<div class="empty">'+(cbCurrentFilter ? "当前筛选条件下无标的" : (d.scanning?"扫描中，请稍候…":"今日无符合条件标的"))+'</div>';
    return;
  }
  var rows = cbSortRows(view).map(function(p){
    var disc = p.is_discount;
    var rateCls = p.arb>=0 ? "pos" : "neg";
    return '<tr class="row-hover">'
      + '<td><a class="codelink" href="https://quote.eastmoney.com/kzz/'+p.market+p.code+'.html" target="_blank">'+p.name+'</a><span class="c-sub">'+p.code+'</span></td>'
      + '<td class="num">'+fmt(p.price)+'</td>'
      + '<td class="num">'+fmt(p.convert_value)+'</td>'
      + '<td class="num '+(p.premium>=0?"pos":"neg")+'">'+fmt(p.premium)+'%</td>'
      + '<td class="num '+rateCls+'"><b>'+fmt(p.arb)+'%</b></td>'
      + '<td><a class="codelink" href="https://quote.eastmoney.com/'+p.market+p.stock_code+'.html" target="_blank">'+p.stock_name+'</a><span class="c-sub">'+p.stock_code+'</span></td>'
      + '<td class="num">'+fmt(p.double_low)+'</td>'
      + '<td>'+fmtConvStart(p.convert_start)+'</td>'
      + '<td><span class="badge '+(disc?"disc":"crit")+'">'+(disc?"折价":"临界")+'</span></td>'
      + '</tr>';
  }).join("");
  tbl.innerHTML =
    '<table class="grid"><thead><tr>'
    + cbHeadCell('name','转债') + cbHeadCell('price','现价') + cbHeadCell('convert_value','转股价值')
    + cbHeadCell('premium','溢价率') + cbHeadCell('arb','套利收益率')
    + cbHeadCell('stock_name','正股') + cbHeadCell('double_low','双低') + cbHeadCell('convert_start','转股起始')
    + '<th>状态</th>'
    + '</tr></thead><tbody>'+rows+'</tbody></table>';
}
function fmtConvStart(s){ if(!s||s.length<8) return "-"; return s.substr(0,4)+"-"+s.substr(4,2)+"-"+s.substr(6,2); }
function rescan(){
  document.getElementById("rescanBtn").disabled = true;
  fetch("/api/cb?force=1&t=" + Date.now()).then(function(r){return r.json();}).then(render).catch(function(){});
  setTimeout(load, 1500);
}
(function(){
  initTheme();
window.addEventListener('DOMContentLoaded',function(){try{applyTheme(document.documentElement.getAttribute('data-theme')||'dark');}catch(e){}});
  load();
})();
</script><script src="watchlist.js"></script></body></html>"""
MANIFEST_JSON = r"""{
  "name": "A股行业轮动与资金流向监控",
  "short_name": "套利工具平台",
  "description": "A股行业轮动、风格轮动、资金流向与基金套利看板",
  "start_url": "/sector",
  "scope": "/",
  "display": "standalone",
  "background_color": "#0d1117",
  "theme_color": "#0d1117",
  "orientation": "portrait",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
  ]
}"""
ICON_PNG_192 = base64.b64decode("""iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAIAAADdvvtQAAADrElEQVR42u3dQW7bMBAFUF5Ai666LNCz5By5Qk7Z03SRK6RAAS+CJJYViiLnP+CvTYLzTNuyOGrbj58ih9MsgQAkAAlAApAIQAKQACQAiQAkAAlAApAIQPfz+vT0RawPQA+jgQmgznQwAqgDHYxCAfWlE86ooYMRQBPpSTPU6GEIoOn05Bhq9DAE0KArhAwB1KfSAEUAOrvGDFUGNKy04YaiAa04FkDV9IQbCgVUZlCAKmw/yZtQs/3YhACa6J5UgGw/NiGALi0eQAABBBBAAAEEUOiZwBxDAAEEEEAAAQQQQAC5DO1itJ/xfsYDBBBAAAHka5AvQAABBJA7EgECCCCG6AHIuTCAJqyok6mhgJyNB+ji0urOAdDBGmsRVB/Qdqin2OAXBKigIT0SAZrCUMLa6hNND0DzGcpZ1SBAv17+jtHzbyCAqtG5ZYCeWwCqpudURh8OBFA1OmcwujsQQAX1dGG0fxSAauo5JunY6wNUWc+YAFRczyRDALSYniWGA2hGPeuOC9DFeopNAKBx9Ss/DYAWLluaoUYPQwBNVyqA6GEIoKsrBBA9DGUDMk+Aln9n196Emu3HbAECCKDq9ahqCCBzBmiRSgCkEgCtD2jdz4KSn2LN9mPyAAEEEEAAqQFAAJk8QCYPEEAAqQFAamDyAJk8QAABpAYA+UvSn6lu5zBtgAACyC2tACkGQI71mC1AAAF0VkkcbQaowttacwWbkO2nIqBNgymAxlRIizuAFquTJpsFAWnzC9ACBdNonCF6APKwFYAGlNDjngDqUEsPnAOoQ1E98hKgPgX20N10QIcN/f7zvDP0FAf0kKH9br4jqeo6lwW0x9B36DzEqPAiVwb0BaNedO4yKr+89QG9M3QGnc8YJaxtBKAbo7P13AzlrGoQoDF6/gcgehgC6Do9OYYaPQwB1FPP4BcEqIieqV4coJUATT4EQGX1MJQOaMWxAKqmJ9xQKKAygwJUqpCBhgACCKCZSphmCCCAANpdv5w5AAQQQAAB5AuQr0EAXVA2gAACCCCAAAIIIIAAYogegAACCCCAAALIxWiXoXNvKLP9AOSORIBqHclIPpjhVIbtByDnwgBa2pCTqaGAnI0HqENpD1dXe5dNg6ljZdYcCKAjJdflLg7QpkciQOsaSlhbfaLpAWg+QzmrGgRomKGoJc0CdDajwMVMBHQGo9hlzAXUi1H4AqYDcoUQIPekAiQACUAiAAlAApAAJAKQACQACUAiAAlAApBUyhsAjiPygPW2MAAAAABJRU5ErkJggg==""")

ICON_PNG_512 = base64.b64decode("""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""")

ICON_SVG = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0d1117"/>
  <circle cx="256" cy="272" r="144" fill="none" stroke="#1f6feb" stroke-width="34"/>
  <path d="M112 176 L256 80 L400 176" fill="none" stroke="#ef4444" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M112 368 L256 464 L400 368" fill="none" stroke="#22c55e" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""
SW_JS = r"""const CACHE='fundarb-v1.4';
const SHELL=['/','/ranking','/top','/manifest.json','/icon-192.png'];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',e=>{
  const url=new URL(e.request.url);
  // 数据接口：网络优先，失败回退缓存
  if(url.pathname.startsWith('/api/')){
    e.respondWith(
      fetch(e.request).then(r=>{const cp=r.clone();caches.open(CACHE).then(c=>c.put(e.request,cp));return r;})
        .catch(()=>caches.match(e.request))
    );
    return;
  }
  // 静态壳：缓存优先，回退网络
  e.respondWith(
    caches.match(e.request).then(c=>c||fetch(e.request).then(r=>{const cp=r.clone();caches.open(CACHE).then(ca=>ca.put(e.request,cp));return r;}))
  );
});
"""
