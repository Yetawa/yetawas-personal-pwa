# -*- coding: utf-8 -*-
"""生成 fund_arb_mobile.html —— 全站合并的单文件手机版（本地可保存运行）

设计要点
1) 8 个页面（套利看板/溢价表/LOF/口袋支点/可转债/鱼盆/行业轮动/自选池）以 srcdoc iframe 内嵌；
2) 数据统一取线上 https://fund-arb.onrender.com（服务端已开 CORS），页内自带固定导航隐藏，
   由外壳底部 Tab 统一导航（省 ~90px 纵向空间，手机上不再双导航）；
3) fetch 统一包装（注入到每个页面）：
   - 共享缓存：成功 JSON 写入 localStorage，按接口设 TTL，切 Tab 秒开、少打服务端（防限流）；
   - 健壮性：20s 超时→2.5s 后一次重试(45s 覆盖 Render 冷启动)；429 同样重试；
   - 离线/失败：回退最近一次缓存并在顶部标注时间；navigator.onLine=false 时直接用缓存不空等；
4) 页内导航点击 / 基金代码点击 → postMessage 交外壳切 Tab，不做真实跳转；
5) 构建期自检：BASE 不得残留 localhost、每页必须注入 shim、相对 fetch 必须改写、端口占用提醒。

用法：python make_mobile_html.py
"""
import json
import os
import re
import socket

ONLINE = "https://fund-arb.onrender.com"
ORIGIN = "https://fund-arb.onrender.com"  # 页面里硬编码的线上地址，构建时统一收敛到 FAB_BASE
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_NAME = "fund_arb_mobile.html"

# 需要合并的页面：tab 键 -> 文件
PAGE_FILES = {
    "arb": "fund_arb.html",
    "ranking": "fund_arb_ranking.html",
    "top": "fund_arb_top.html",
    "pivot": "pivot_live.html",
    "cb": "cb.html",
    "fish": "fish_basin.html",
    "sector": "sector_dashboard.html",
    "watch": "watchlist.html",
}

# 站内导航映射：页内锚点 href -> tab 键
NAV_MAP = {
    "/sector": "sector", "sector_dashboard.html": "sector",
    "/yupen": "fish", "fish_basin.html": "fish",
    "/arb": "arb", "fund_arb.html": "arb",
    "/ranking": "ranking", "fund_arb_ranking.html": "ranking",
    "/top": "top", "fund_arb_top.html": "top",
    "/pivot": "pivot", "pivot_live.html": "pivot",
    "/cb": "cb", "cb.html": "cb",
    "/watch": "watch", "watchlist.html": "watch",
}

SNAPSHOTS = ("cb_snapshot.json", "fish_model.json", "fish_snapshot.json", "sector_data.json")


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ 注入片段
# 隐藏页内固定导航（外壳已有底部 Tab），并回收其预留的顶部内边距
HEAD_CSS = """<style>
/* ==== 手机版：隐藏页内重复导航，回收顶部空间 ==== */
.topnav{display:none!important}
body{padding-top:10px!important}
.wrap{padding-top:10px!important}
@media (max-width:760px){body{padding-top:10px!important}.wrap{padding-top:10px!important}}
</style>"""

SHIM = """<script>
/* ==== fund_arb 手机版注入：BASE 覆写 + fetch 共享缓存 + 导航拦截 ==== */
(function(){
  var BASE='__ONLINE__';
  window.FAB_BASE=BASE;
  window.__QS__=window.__QS__||'';   /* 保留外壳注入的 ?code=（注入脚本先于 shim 执行） */
  /* 各接口缓存 TTL（ms）：行情类短、快照/回测类长，兼顾新鲜度与请求量 */
  var TTL=[['/api/data',45000],['/api/validate',600000],['/api/ranking',90000],
           ['/api/top',90000],['/api/pivot',90000],['/api/history',600000],
           ['/api/cb',90000],['/api/sector_live',120000],['/api/kline',900000],
           ['.json',900000]];
  function ttlFor(u){for(var i=0;i<TTL.length;i++){if(u.indexOf(TTL[i][0])>=0)return TTL[i][1];}return 60000;}
  function getK(k){try{var r=localStorage.getItem(k);return r?JSON.parse(r):null;}catch(e){return null;}}
  function putK(k,v){
    try{
      localStorage.setItem(k,JSON.stringify(v));
      var keys=[],i;
      for(i=0;i<localStorage.length;i++){var n=localStorage.key(i);if(n&&n.indexOf('fam_')===0)keys.push(n);}
      if(keys.length>80){ /* 简易淘汰：按写入时间删最旧的 20 个，避免撑爆 5MB 配额 */
        keys.sort(function(a,b){var x=getK(a),y=getK(b);return ((x&&x.t)||0)-((y&&y.t)||0);});
        for(i=0;i<20;i++){try{localStorage.removeItem(keys[i]);}catch(e){}}
      }
    }catch(e){}
  }
  function forced(){try{return (Date.now()-(+localStorage.getItem('fam_force')||0))<4000;}catch(e){return false;}}
  function jsonResp(d){return new Response(JSON.stringify(d),{status:200,headers:{'Content-Type':'application/json'}});}
  function tell(m){try{parent.postMessage(m,'*');}catch(e){}}
  var of=window.fetch?window.fetch.bind(window):null;
  function net(url,init,ms){
    return new Promise(function(res,rej){
      var ctl=(typeof AbortController!=='undefined')?new AbortController():null;
      var tid=setTimeout(function(){try{ctl&&ctl.abort();}catch(e){}rej(new Error('timeout'));},ms);
      var o={},k;for(k in (init||{})){o[k]=init[k];}
      if(ctl)o.signal=ctl.signal;
      of(url,o).then(function(r){clearTimeout(tid);res(r);},function(e){clearTimeout(tid);rej(e);});
    });
  }
  if(of){
    window.fetch=function(input,init){
      try{
        var url=(typeof input==='string')?input:(input&&input.url)||'';
        var method=((init&&init.method)||'GET')+'';
        if(method.toUpperCase()!=='GET'||url.indexOf(BASE)!==0) return of(input,init);
        var key='fam_'+url, cand=getK(key), now=Date.now(), ttl=ttlFor(url);
        var bypass=forced()||url.indexOf('force=1')>=0;
        if(cand&&!bypass&&(now-cand.t)<ttl) return Promise.resolve(jsonResp(cand.d));  /* 命中即返，切 Tab 秒开 */
        function onOk(res){
          try{
            var ct=(res.headers&&res.headers.get)?(res.headers.get('content-type')||''):'';
            if(res.ok&&ct.indexOf('json')>=0){
              res.clone().text().then(function(t){try{putK(key,{t:Date.now(),d:JSON.parse(t)});}catch(e){}}).catch(function(){});
            }
          }catch(e){}
          tell({fa:'live'});
          return res;
        }
        function useCache(err){
          if(cand){tell({fa:'stale',t:cand.t});return jsonResp(cand.d);}
          throw err;
        }
        function attempt(ms){
          return net(url,init,ms).then(function(r){if(r.status===429)throw new Error('429 限流');return r;});
        }
        if(navigator&&navigator.onLine===false){ return Promise.resolve().then(function(){return useCache(new Error('offline'));}); }
        return attempt(20000)
          .catch(function(){return new Promise(function(r){setTimeout(r,2500);}).then(function(){return attempt(45000);});})
          .then(onOk,function(e){return useCache(e);});
      }catch(e){ return of(input,init); }
    };
  }
  /* 点击拦截：站内导航 / 代码跳转交外壳处理 */
  var TMAP=__NAVMAP__;
  document.addEventListener('click',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a'):null;
    if(!a) return;
    var href=a.getAttribute('href')||'';
    if(!href||href.charAt(0)==='#') return;
    var mc=href.match(/[?&]code=(\\d{6})/);
    if(mc){e.preventDefault();tell({fa:'code',code:mc[1]});return;}
    var t=TMAP[href];
    if(t){e.preventDefault();tell({fa:'tab',tab:t});return;}
    if(href==='/xlj'){e.preventDefault();tell({fa:'xlj'});return;}
  },true);
})();
</script>"""


def build_shim():
    return SHIM.replace("__ONLINE__", ONLINE).replace(
        "__NAVMAP__", json.dumps(NAV_MAP, ensure_ascii=False))


# ------------------------------------------------------------------ 页面改写
def prep_page(html, shim):
    # 1) 去掉站点静态资源引用与 SW 注册（srcdoc/file 下无意义或 404）
    html = re.sub(r'<link rel="(?:manifest|apple-touch-icon|icon)"[^>]*>', "", html)
    html = re.sub(r"if\('serviceWorker' in navigator\)\{[\s\S]*?\}\s*\}\s*", "", html, count=1)
    # 2) 内联 watchlist.js（srcdoc 下相对脚本取不到）
    if '<script src="watchlist.js"></script>' in html:
        html = html.replace('<script src="watchlist.js"></script>',
                            "<script>\n" + load("watchlist.js") + "\n</script>", 1)
    # 3) BASE：file:// 指向 localhost 的写法在手机上必然失败，统一改线上
    html = re.sub(r"\(location\.protocol===['\"]file:['\"]\)\s*\?\s*['\"]http://localhost:8000['\"]\s*:\s*['\"]['\"]",
                  "'" + ONLINE + "'", html)
    # 4) 取数地址改写为线上绝对地址（走 FAB_BASE，便于统一拦截/缓存）
    html = re.sub(r"fetch\(\s*(?:BASE|window\.FAB_BASE)\s*\+\s*(['\"])/api/", r"fetch(window.FAB_BASE+\1/api/", html)
    html = re.sub(r"fetch\(\s*(['\"])/api/", r"fetch(window.FAB_BASE+\1/api/", html)
    for snap in SNAPSHOTS:
        html = re.sub(r"fetch\(\s*(['\"])/?" + re.escape(snap), r"fetch(window.FAB_BASE+\1/" + snap, html)
        html = html.replace('fetch("' + ONLINE + "/" + snap, 'fetch(window.FAB_BASE+"/' + snap)
        html = html.replace("fetch('" + ONLINE + "/" + snap, "fetch(window.FAB_BASE+'/" + snap)
        # 硬编码的线上快照地址同样收敛到 FAB_BASE：只打一个源，
        # 避免"先打线上超时→再走兜底"的重复请求（本地/线上构建都受益）
        html = html.replace('fetch("' + ORIGIN + "/" + snap, 'fetch(window.FAB_BASE+"/' + snap)
        html = html.replace("fetch('" + ORIGIN + "/" + snap, "fetch(window.FAB_BASE+'/" + snap)
    # 5) 提示文案里的 localhost 在手机版语境下改为通用说法
    html = html.replace("实时刷新需在本地 localhost:8000 环境使用", "实时刷新需在桌面端本地环境使用")
    # 6) ?code= 读取兼容：srcdoc 无 query，由外壳注入 window.__QS__
    html = html.replace("location.search", "(window.__QS__||location.search)")
    # 7) 头部注入 CSS + shim（必须在页面脚本前执行）
    html = html.replace("<head>", "<head>" + HEAD_CSS + shim, 1)
    return html


def check_page(src, html):
    problems = []
    if "localhost:8000" in html:
        problems.append("残留 localhost:8000")
    if "watchlist.js\"" in html:
        problems.append("仍外链 watchlist.js")
    if "fetch 共享缓存" not in html:
        problems.append("未注入 shim")
    left = re.findall(r"fetch\(\s*['\"](?!/|https?:|'\+window\.FAB_BASE)", html)
    if left:
        problems.append("未改写相对 fetch: %s" % left[:3])
    if problems:
        print("  ✗ %s: %s" % (src, "；".join(problems)))
    return not problems


# ------------------------------------------------------------------ 外壳
XLJ_CARD = (
    '<div style="font-family:-apple-system,\'Microsoft YaHei\',sans-serif;padding:48px 22px;text-align:center;'
    'color:%(txt)s;background:%(bg)s;min-height:100vh;box-sizing:border-box">'
    '<div style="font-size:44px;margin-bottom:14px">🐉</div>'
    '<div style="font-size:17px;font-weight:800;margin-bottom:8px">寻龙诀</div>'
    '<div style="font-size:13px;line-height:1.8;color:%(mut)s;margin-bottom:20px">'
    '该页为在线实时图表（数据量大，不适合离线内嵌）。<br>点击下方按钮在浏览器中打开。</div>'
    '<a href="%(base)s/xlj" target="_blank" style="display:inline-block;background:#1f6feb;color:#fff;'
    'text-decoration:none;font-weight:700;font-size:14px;padding:11px 26px;border-radius:10px">打开寻龙诀 ↗</a>'
    '<div style="font-size:11px;color:%(mut)s;margin-top:18px">%(base)s/xlj</div></div>'
)

SHELL_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--btn:#1f6feb;--est:#f2a900;--title:#f0f6fc}
:root[data-theme="light"]{--bg:#ffffff;--panel:#f5f7fa;--border:#e3e8ef;--text:#1f2933;--muted:#6b7280;--btn:#2563eb;--est:#d97706;--title:#111827}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei","Segoe UI",sans-serif;background:var(--bg);color:var(--text);overflow:hidden}
#hd{position:fixed;top:0;left:0;right:0;z-index:50;display:flex;align-items:center;gap:6px;padding:calc(6px + env(safe-area-inset-top)) 12px 6px;background:var(--panel);border-bottom:1px solid var(--border)}
#hd .t{font-size:14px;font-weight:800;color:var(--title);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#hd .t small{display:block;font-size:10px;font-weight:400;color:var(--muted);margin-top:1px;overflow:hidden;text-overflow:ellipsis}
#hd button{background:var(--panel);color:var(--title);border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:12.5px;font-weight:600;cursor:pointer;flex:none}
#hd button:active{border-color:var(--btn);color:var(--btn)}
#banner{position:fixed;top:calc(48px + env(safe-area-inset-top));left:8px;right:8px;z-index:49;display:none;background:rgba(242,169,0,.14);border:1px solid rgba(242,169,0,.45);color:var(--est);border-radius:9px;padding:8px 12px;font-size:12px;line-height:1.5}
#framebox{position:fixed;top:calc(48px + env(safe-area-inset-top));left:0;right:0;bottom:calc(52px + env(safe-area-inset-bottom))}
#framebox iframe{width:100%;height:100%;border:0;display:block}
#tabbar{position:fixed;bottom:0;left:0;right:0;z-index:50;display:flex;background:var(--panel);border-top:1px solid var(--border);padding:4px 2px calc(4px + env(safe-area-inset-bottom))}
#tabbar button{flex:1;background:none;border:none;color:var(--muted);font-size:10.5px;font-weight:600;padding:4px 0 2px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:2px;min-width:0}
#tabbar button .ic{font-size:16px;line-height:1}
#tabbar button.on{color:var(--btn)}
#load{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;background:var(--bg);color:var(--muted);font-size:14px}
#about{position:fixed;inset:0;z-index:70;display:none;background:rgba(0,0,0,.55);align-items:center;justify-content:center;padding:20px}
#about .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;max-width:420px;width:100%;max-height:76vh;overflow:auto;padding:18px;font-size:13px;line-height:1.85}
#about h3{margin:0 0 10px;color:var(--title);font-size:15px}
#about b{color:var(--title)}
#about .x{margin-top:14px;text-align:center}
#about button{padding:9px 22px}
"""

SHELL_JS = """
var TABS=[['arb','看板','📈'],['ranking','溢价表','🏆'],['top','LOF','🔥'],['pivot','口袋','🎯'],
          ['cb','转债','💵'],['fish','鱼盆','🐟'],['sector','轮动','🧭'],['watch','自选','⭐'],['xlj','寻龙','🐉']];
var PAGES=__PAGES__;
var cur=null;
function $(id){return document.getElementById(id)}
function applyTheme(t){
  try{localStorage.setItem('arb_theme',t);}catch(e){}
  document.documentElement.setAttribute('data-theme',t);
  var b=$('themeBtn'); if(b) b.textContent=(t==='light')?'☀️':'🌙';
}
function autoTheme(){var h=new Date().getHours();return (h>=18||h<6)?'dark':'light';}
function toggleTheme(){
  var cur2=(document.documentElement.getAttribute('data-theme')==='light')?'dark':'light';
  applyTheme(cur2);
  if(cur) openTab(cur);   /* 重载当前页以应用新主题（有缓存，秒开） */
}
function buildTabbar(){
  $('tabbar').innerHTML=TABS.map(function(t){
    return '<button data-tab="'+t[0]+'" onclick="openTab(\\''+t[0]+'\\')"><span class="ic">'+t[2]+'</span>'+t[1]+'</button>';
  }).join('');
}
function markTab(){
  var bs=$('tabbar').children;
  for(var i=0;i<bs.length;i++) bs[i].className=(bs[i].getAttribute('data-tab')===cur)?'on':'';
}
function openTab(tab,qs){
  if(!PAGES[tab]) return;
  cur=tab;
  try{localStorage.setItem('fa_mobile_tab',tab);}catch(e){}
  markTab(); hideBanner();
  var box=$('framebox'); box.innerHTML='';
  $('load').style.display='flex';
  var html=PAGES[tab];
  if(qs){
    var inj='<scr'+'ipt>window.__QS__='+JSON.stringify(qs)+';</scr'+'ipt>';
    html=html.replace('<head>','<head>'+inj);
  }
  var ifr=document.createElement('iframe');
  ifr.addEventListener('load',function(){$('load').style.display='none';});
  ifr.srcdoc=html;
  box.appendChild(ifr);
}
/* 强制刷新：打标记让 shim 跳过新鲜缓存，然后重载当前页 */
function hardRefresh(){
  try{localStorage.setItem('fam_force',String(Date.now()));}catch(e){}
  if(cur) openTab(cur);
}
function showBanner(msg){var b=$('banner');b.textContent=msg;b.style.display='block';}
function hideBanner(){$('banner').style.display='none';}
window.addEventListener('message',function(e){
  var m=e.data||{};
  if(m.fa==='tab') openTab(m.tab);
  else if(m.fa==='code') openTab('arb','?code='+m.code);
  else if(m.fa==='xlj') openTab('xlj');
  else if(m.fa==='stale'){
    var d=m.t?new Date(m.t):null;
    showBanner('⚠️ 网络暂不可用，显示缓存数据'+(d?('（'+d.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})+' 更新）'):'')+'，点「刷新」重试');
  }
  else if(m.fa==='live') hideBanner();
});
(function(){
  var t=autoTheme();
  try{t=localStorage.getItem('arb_theme')||t;}catch(e){}
  applyTheme(t); buildTabbar();
  var last='arb';
  try{last=localStorage.getItem('fa_mobile_tab')||'arb';}catch(e){}
  openTab(PAGES[last]?last:'arb');
})();
"""

SHELL_ABOUT = """
<h3>📱 使用说明</h3>
<b>数据来源</b>：fund-arb.onrender.com（需联网）。取数成功的数据会存在手机本地并按接口缓存几十秒到十几分钟，切页几乎秒开；断网时显示最近一次缓存并在顶部黄条标注时间。<br>
<b>页面切换</b>：底部 9 个标签；表格里的基金代码可点，自动跳看板查询；长按代码加入自选池。<br>
<b>保存到手机（iPhone）</b>：把本 HTML 用微信「文件传输助手」/隔空投送/iCloud 存到「文件」App → 点开 → 分享 → 用 Safari 打开。<br>
<b>保存到手机（Android）</b>：存到下载目录，用 Chrome / Edge / 系统浏览器打开即可。<br>
<b>添加到主屏幕</b>：浏览器菜单里选「添加到主屏幕」，之后像 App 一样点开。<br>
<b>提示</b>：Render 免费实例冷启动约 30-60 秒，首次加载慢属正常；页面内黄色提示条表示当前用的是缓存。
<div class="x"><button onclick="document.getElementById('about').style.display='none'">我知道了</button></div>
"""


def js_embed(s):
    """转成安全 JS 字符串字面量（转义 </ 防止提前闭合 script）"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def port_in_use(port=8000):
    s = socket.socket()
    s.settimeout(0.35)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def main():
    shim = build_shim()
    pages, ok = {}, True
    print("改写页面：")
    for tab, fname in PAGE_FILES.items():
        html = prep_page(load(fname), shim)
        ok = check_page(fname, html) and ok
        pages[tab] = html
        print("  ✓ %-24s %6.1f KB" % (fname, len(html.encode("utf-8")) / 1024))
    if not ok:
        raise SystemExit("页面改写自检未通过，已中止生成")

    # 寻龙诀：内嵌轻量入口卡（在线图表页体积大，不做离线内嵌）
    xlj_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>@media(prefers-color-scheme:light){body{background:#fff!important;color:#1f2933!important}}</style>"
        "</head><body style='margin:0'>"
        + XLJ_CARD % {"base": ONLINE, "txt": "#c9d1d9", "bg": "#0d1117", "mut": "#8b949e"}
        + "</body></html>"
    )
    pages["xlj"] = prep_page(xlj_html, shim)

    pages_js = "{" + ",".join('"%s":%s' % (k, js_embed(v)) for k, v in pages.items()) + "}"
    shell = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<meta name=\"theme-color\" content=\"#0d1117\">\n"
        "<title>套利工具平台 · 手机版</title>\n<style>" + SHELL_CSS + "</style>\n</head>\n<body>\n"
        "<div id=\"hd\"><div class=\"t\">套利工具平台<small>数据源 fund-arb.onrender.com ｜ 断网自动用缓存</small></div>"
        "<button id=\"themeBtn\" onclick=\"toggleTheme()\">🌙</button>"
        "<button onclick=\"hardRefresh()\">刷新</button>"
        "<button onclick=\"document.getElementById('about').style.display='flex'\">说明</button></div>\n"
        "<div id=\"banner\"></div>\n<div id=\"framebox\"></div>\n<div id=\"tabbar\"></div>\n"
        "<div id=\"load\">加载中…</div>\n"
        "<div id=\"about\"><div class=\"card\">" + SHELL_ABOUT + "</div></div>\n"
        "<script>" + SHELL_JS.replace("__PAGES__", pages_js) + "</script>\n</body>\n</html>"
    )
    out = os.path.join(HERE, OUT_NAME)
    with open(out, "w", encoding="utf-8") as f:
        f.write(shell)

    print("\n自检：BASE=%s ｜ 页面数=%d ｜ 输出 %.1f KB" % (ONLINE, len(pages), len(shell.encode("utf-8")) / 1024))
    if "localhost:8000" in shell:
        raise SystemExit("产物中残留 localhost:8000，请检查改写规则")
    if port_in_use(8000):
        print("提示：本机 8000 端口正被占用（本地预览服务在跑，不影响手机版）。"
              "\n      如需重启本地服务：先结束占用进程再 python fund_arb.py")
    print("已生成:", out)


if __name__ == "__main__":
    main()
