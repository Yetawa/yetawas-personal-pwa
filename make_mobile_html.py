# -*- coding: utf-8 -*-
"""生成 fund_arb_mobile.html —— 全站合并的单文件手机版（本地可保存运行）

设计要点
1) 9 个页面以 srcdoc iframe 内嵌，外壳底部 Tab 统一导航（页内固定导航隐藏，省纵向空间）；
2) 行业轮动为首页（打开即看轮动），Tab 顺序按使用习惯排；
3) 各页版式归一：统一顶部留白 / 左右边距 / 底部留白，消除「标题上方大片空白」；
4) fetch 统一包装（注入到每个页面）：
   - 缓存键归一化：剥离 t=/ts/_/force 等易变参数 → 各页带时间戳的请求也能命中缓存；
   - 同 URL 并发去重：多页面/重复调用只打一次服务端；
   - 超时重试：20s 超时 → 2.5s 后重试一次（45s，兜住 Render 冷启动）；429/5xx 同样重试；
   - 离线/失败：回退最近一次缓存并在顶部标注时间与状态点；
   - 首页加载完空闲后预热小体积接口，切 Tab 直接命中；
5) 页内导航点击 / 基金代码点击 → postMessage 交外壳切 Tab，不做真实跳转；
6) 外壳 iframe LRU（保留 3 个）：切回旧 Tab 不重载、保留滚动位置，瞬时切换；
7) 构建期自检：BASE 不得残留 localhost、占位符必须全部替换、每页必须注入 shim、
   相对 fetch 必须改写、产物不得残留 t=Date.now 类取数、端口占用提醒。

用法：python make_mobile_html.py
"""
import json
import os
import re
import socket

# ------------------------------------------------------------------ 配置
HOME_TAB = "sector"        # 打开即显示的首页（行业轮动）
DEFAULT_CODE = "513310"    # 看板页无历史记录时的默认基金
ONLINE = "https://fund-arb.onrender.com"
ORIGIN = "https://fund-arb.onrender.com"  # 页面里硬编码的线上地址，构建时统一收敛到 FAB_BASE
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_NAME = "fund_arb_mobile.html"

# 需要合并的页面（顺序即底部 Tab 顺序）：tab 键 -> 文件
PAGE_FILES = {
    "sector": "sector_dashboard.html",
    "arb": "fund_arb.html",
    "ranking": "fund_arb_ranking.html",
    "top": "fund_arb_top.html",
    "pivot": "pivot_live.html",
    "cb": "cb.html",
    "fish": "fish_basin.html",
    "watch": "watchlist.html",
}

TAB_TITLES = {
    "sector": "行业轮动", "arb": "套利看板", "ranking": "溢价表", "top": "LOF 溢价榜",
    "pivot": "口袋支点", "cb": "可转债", "fish": "鱼盆模型", "watch": "自选池", "xlj": "寻龙诀",
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

# 首页加载完后空闲预热的小体积接口（切 Tab 直接命中本地缓存）
PREFETCH = [
    "/sector_data.json",
    "/api/sector_live",
    "/api/cb", "/cb_snapshot.json",
    "/api/history?type=cb&days=5",
    "/api/pivot", "/api/history?type=pivot&days=5",
    "/api/history?type=top&days=5",
    "/fish_model.json", "/fish_snapshot.json",
]

# 各页版式归一：统一顶部留白 12px、左右 14px、底部 26px。
# 注意注入的样式在页面自带 <style> 之前，故必须 !important 才能压过页面规则。
LAYOUT = {
    # body 自带 padding 的页面
    "arb": "body{padding:12px 14px 26px!important}",
    "ranking": "body{padding:12px 14px 26px!important}",
    "top": "body{padding:12px 14px 26px!important}",
    "pivot": "body{padding:12px 14px 26px!important}",
    "cb": "body{padding:12px 14px 26px!important}",
    # 容器自带 padding 的页面（鱼盆原本 .page 顶部 64px→手机端 88px，正是标题上方大片空白的来源）
    "sector": "body{padding:0!important}.wrap{padding:12px 14px 26px!important}",
    "fish": "body{padding:0!important}.page{padding:12px 14px 26px!important}",
    "watch": ":root{--nav-h:0px!important}body{padding:0!important}"
             ".wrap{padding:12px 14px 26px!important}",
    "xlj": "",
}

COMMON_CSS = (
    "<style>"
    ".topnav{display:none!important}"           # 外壳已有底部 Tab，页内导航隐藏
    # 页内主题/刷新按钮与外壳功能重复：隐藏，减少顶部控件堆叠
    "#themeBtn,#btnTheme,#refreshBtn{display:none!important}"
    "button[onclick=\"refresh(true)\"]{display:none!important}"
    "img,svg,canvas,video{max-width:100%}"      # 防横向溢出
    # 导出浮动条在手机上缩小，减少对表格的遮挡
    "#arbExportBar{right:8px!important;bottom:8px!important}"
    ".arb-exp-btn{padding:5px 9px!important;font-size:11px!important;border-radius:7px!important}"
    "html{-webkit-text-size-adjust:100%}"
    "</style>"
)


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ 注入片段
SHIM = """<script>
/* ==== fund_arb 手机版注入：BASE 覆写 + fetch 共享缓存 + 导航拦截 ==== */
(function(){
  var BASE='__ONLINE__';
  window.FAB_BASE=BASE;
  window.FAB_PAGE='__TAB__';
  window.__QS__=window.__QS__||'';   /* 保留外壳注入的 ?code=（注入脚本先于 shim 执行） */
  /* 看板页：优先"上次查询的基金"，没有则用默认基金直查。
     目的：跳过"先拉全市场排行榜(冷启动可达数十秒)→再查单只基金"的串行等待。 */
  if(!window.__QS__&&window.FAB_PAGE==='arb'){
    var lc='';
    try{lc=localStorage.getItem('arb_last_code')||'';}catch(e){}
    window.__QS__='?code='+(/^\\d{6}$/.test(lc)?lc:'__DEFAULT_CODE__');
  }
  /* 各接口缓存 TTL（ms）：行情类短、快照/回测类长，兼顾新鲜度与请求量 */
  var TTL=[['/api/data',45000],['/api/validate',600000],['/api/ranking',90000],
           ['/api/top',90000],['/api/pivot',90000],['/api/history',600000],
           ['/api/cb',90000],['/api/sector_live',120000],['/api/kline',900000],
           ['.json',900000]];
  function ttlFor(u){for(var i=0;i<TTL.length;i++){if(u.indexOf(TTL[i][0])>=0)return TTL[i][1];}return 60000;}

  /* 缓存键归一化：剥离 t=/ts/_/force 等易变参数并排序，
     否则各页取数URL上串的 t=Date.now() 会让缓存永不命中（旧版最大的性能漏洞）。 */
  function norm(u){
    var q=u.indexOf('?');
    if(q<0) return u;
    var base=u.slice(0,q), parts=u.slice(q+1).split('&'), keep=[];
    for(var i=0;i<parts.length;i++){
      var p=parts[i]; if(!p) continue;
      var k=p.split('=')[0];
      if(k==='t'||k==='ts'||k==='_'||k==='force') continue;
      keep.push(p);
    }
    keep.sort();
    return base+(keep.length?'?'+keep.join('&'):'');
  }
  function getK(k){try{var r=localStorage.getItem(k);return r?JSON.parse(r):null;}catch(e){return null;}}
  function putK(k,v){
    try{
      localStorage.setItem(k,JSON.stringify(v));
      var keys=[],i;
      for(i=0;i<localStorage.length;i++){var n=localStorage.key(i);if(n&&n.indexOf('fam_')===0)keys.push(n);}
      if(keys.length>80){ /* 简易淘汰：按写入时间删最旧的 20 个，避免撑爆配额 */
        keys.sort(function(a,b){var x=getK(a),y=getK(b);return ((x&&x.t)||0)-((y&&y.t)||0);});
        for(i=0;i<20;i++){try{localStorage.removeItem(keys[i]);}catch(e){}}
      }
    }catch(e){}
  }
  function forced(){try{return (Date.now()-(+localStorage.getItem('fam_force')||0))<4000;}catch(e){return false;}}
  function jsonResp(d){return new Response(JSON.stringify(d),{status:200,headers:{'Content-Type':'application/json'}});}
  function tell(m){try{parent.postMessage(m,'*');}catch(e){}}
  function wait(ms){return new Promise(function(r){setTimeout(r,ms);});}
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
  var inflight={};
  function work(url,init,key){
    function attempt(ms){
      return net(url,init,ms).then(function(r){
        if(r.status===429||r.status>=500) throw new Error('http '+r.status);  /* 限流/冷启动 502-504 一律重试 */
        return r;
      });
    }
    return attempt(20000)
      .catch(function(){return wait(2500).then(function(){return attempt(45000);});})
      .then(function(r){
        var ct=(r.headers&&r.headers.get)?(r.headers.get('content-type')||''):'';
        return r.text().then(function(t){
          var obj=null; try{obj=JSON.parse(t);}catch(e){}
          if(obj!==null&&r.ok) putK(key,{t:Date.now(),d:obj});
          var mc=url.match(/\\/api\\/data\\?(?:[^#]*&)?code=(\\d{6})/);
          if(r.ok&&mc){try{localStorage.setItem('arb_last_code',mc[1]);}catch(e){}}
          return {body:t,ct:ct,json:obj};
        });
      });
  }
  if(of){
    window.fetch=function(input,init){
      try{
        var url=(typeof input==='string')?input:(input&&input.url)||'';
        var method=((init&&init.method)||'GET')+'';
        if(method.toUpperCase()!=='GET'||url.indexOf(BASE)!==0) return of(input,init);
        var key='fam_'+norm(url);
        var bypass=forced()||/[?&]force=1/.test(url);
        var cand=getK(key);
        if(cand&&!bypass&&(Date.now()-cand.t)<ttlFor(url)){
          return Promise.resolve(jsonResp(cand.d));   /* 缓存命中：切页秒开，不打服务端 */
        }
        if(navigator&&navigator.onLine===false){
          if(cand){tell({fa:'stale',t:cand.t});return Promise.resolve(jsonResp(cand.d));}
          return Promise.reject(new Error('offline'));
        }
        var p=inflight[key];
        if(!p||bypass){                            /* 同 URL 并发去重 */
          p=work(url,init,key);
          if(!bypass){
            inflight[key]=p;
            p.then(function(){delete inflight[key];},function(){delete inflight[key];});
          }
        }
        return p.then(function(pack){
          tell({fa:'live'});
          if(pack.json!==null) return jsonResp(pack.json);
          return new Response(pack.body,{status:200,headers:{'Content-Type':pack.ct||'text/plain'}});
        },function(e){
          var c2=getK(key);
          if(c2){tell({fa:'stale',t:c2.t});return jsonResp(c2.d);}
          throw e;
        });
      }catch(e){ return of(input,init); }
    };
  }
  /* 隐藏的 Tab（iframe 已 display:none）暂停定时器，避免后台空转打接口 */
  (function(){
    var si=window.setInterval;
    window.setInterval=function(fn,ms){
      var a=Array.prototype.slice.call(arguments,2);
      return si(function(){
        try{ if(window.frameElement&&window.frameElement.style.display==='none') return; }catch(e){}
        return fn.apply(null,a);
      },ms);
    };
  })();
  /* 首页空闲预热：小体积接口先取好，切 Tab 直接命中缓存 */
  (function(){
    if(window.FAB_PAGE!=='__HOME__') return;
    var LIST=__PREFETCH__;
    function warm(){
      if(navigator.onLine===false) return;
      var c=navigator.connection||{};
      if(c.saveData) return;
      var i=0;
      (function step(){
        if(i>=LIST.length) return;
        var u=BASE+LIST[i++];
        try{ window.fetch(u).then(function(){setTimeout(step,180);},function(){setTimeout(step,180);}); }
        catch(e){ setTimeout(step,180); }
      })();
    }
    /* 不用 window.onload（srcdoc 下不一定触发），改为轮询就绪后延时启动 */
    setTimeout(function(){
      var n=0;
      (function waitReady(){
        if(document.readyState==='complete'||n++>16) return warm();
        setTimeout(waitReady,500);
      })();
    },1500);
  })();
  /* 轮动页：长段"数据说明"默认折叠（手机首屏别被提示文字占满），点按钮展开 */
  if(window.FAB_PAGE==='sector'){
    document.addEventListener('DOMContentLoaded',function(){
      var n=document.getElementById('snapNote');
      if(!n||n.getAttribute('data-fab')) return;
      n.setAttribute('data-fab','1');
      var btn=document.createElement('button');
      function paint(hid){btn.textContent=hid?'ⓘ 数据说明':'▴ 收起说明';}
      btn.style.cssText='margin:0 0 10px;padding:4px 10px;font-size:12px;font-weight:600;border-radius:8px;'
        +'border:1px solid currentColor;background:transparent;color:inherit;opacity:.7;cursor:pointer';
      btn.onclick=function(){
        var hid=n.style.display==='none';
        n.style.display=hid?'':'none';
        paint(!hid);
      };
      n.style.display='none'; paint(true);
      n.parentNode.insertBefore(btn,n);
    });
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


def build_shim(tab):
    return (SHIM.replace("__ONLINE__", ONLINE)
                .replace("__TAB__", tab)          # 先替换页面标记（占位符同名，顺序敏感）
                .replace("__HOME__", HOME_TAB)
                .replace("__DEFAULT_CODE__", DEFAULT_CODE)
                .replace("__PREFETCH__", json.dumps(PREFETCH))
                .replace("__NAVMAP__", json.dumps(NAV_MAP, ensure_ascii=False)))


# ------------------------------------------------------------------ 页面改写
def prep_page(html, tab):
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
    # 4) 取数地址改写为 FAB_BASE 绝对地址（便于统一拦截/缓存）
    html = re.sub(r"fetch\(\s*(?:BASE|window\.FAB_BASE)\s*\+\s*(['\"])/api/", r"fetch(window.FAB_BASE+\1/api/", html)
    html = re.sub(r"fetch\(\s*(['\"])/api/", r"fetch(window.FAB_BASE+\1/api/", html)
    for snap in SNAPSHOTS:
        html = re.sub(r"fetch\(\s*(['\"])/?" + re.escape(snap), r"fetch(window.FAB_BASE+\1/" + snap, html)
        html = html.replace('fetch("' + ONLINE + "/" + snap, 'fetch(window.FAB_BASE+"/' + snap)
        html = html.replace("fetch('" + ONLINE + "/" + snap, "fetch(window.FAB_BASE+'/" + snap)
        # 硬编码线上快照地址同样收敛到 FAB_BASE：只打一个源，避免重复请求
        html = html.replace('fetch("' + ORIGIN + "/" + snap, 'fetch(window.FAB_BASE+"/' + snap)
        html = html.replace("fetch('" + ORIGIN + "/" + snap, "fetch(window.FAB_BASE+'/" + snap)
    # 5) 提示文案里的 localhost 在手机版语境下改为通用说法
    html = html.replace("实时刷新需在本地 localhost:8000 环境使用", "实时刷新需在桌面端本地环境使用")
    # 6) ?code= 读取兼容：srcdoc 无 query，由外壳注入 window.__QS__
    html = html.replace("location.search", "(window.__QS__||location.search)")
    # 7) 头部注入「版式归一 CSS + shim」（必须在页面脚本前执行）
    head = COMMON_CSS + "<style>" + LAYOUT.get(tab, "") + "</style>" + build_shim(tab)
    html = html.replace("<head>", "<head>" + head, 1)
    return html


def check_page(src, html, tab):
    problems = []
    if "localhost:8000" in html:
        problems.append("残留 localhost:8000")
    if "watchlist.js\"" in html:
        problems.append("仍外链 watchlist.js")
    if "fetch 共享缓存" not in html:
        problems.append("未注入 shim")
    if "__TAB__" in html or "__PREFETCH__" in html or "__NAVMAP__" in html:
        problems.append("占位符未替换")
    if LAYOUT.get(tab) and LAYOUT[tab].split("{")[0] not in html:
        problems.append("版式归一 CSS 未注入")
    left = re.findall(r"fetch\(\s*['\"](?!/|https?:)", html)
    if left:
        problems.append("未改写相对 fetch: %s" % left[:3])
    if problems:
        print("  ✗ %s: %s" % (src, "；".join(problems)))
    return not problems


# ------------------------------------------------------------------ 外壳
XLJ_CARD = (
    '<div style="font-family:-apple-system,\'Microsoft YaHei\',sans-serif;padding:40px 22px;text-align:center;'
    'color:%(txt)s;background:%(bg)s;min-height:100vh;box-sizing:border-box">'
    '<div style="font-size:44px;margin-bottom:12px">🐉</div>'
    '<div style="font-size:17px;font-weight:800;margin-bottom:8px">寻龙诀</div>'
    '<div style="font-size:13px;line-height:1.8;color:%(mut)s;margin-bottom:20px">'
    '该页为在线实时图表（数据量大，不适合离线内嵌）。<br>点击下方按钮在浏览器中打开。</div>'
    '<a href="%(base)s/xlj" target="_blank" style="display:inline-block;background:#1f6feb;color:#fff;'
    'text-decoration:none;font-weight:700;font-size:14px;padding:11px 26px;border-radius:10px">打开寻龙诀 ↗</a>'
    '<div style="font-size:11px;color:%(mut)s;margin-top:16px">%(base)s/xlj</div></div>'
)

SHELL_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--btn:#1f6feb;--est:#f2a900;--title:#f0f6fc;--ok:#22c55e}
:root[data-theme="light"]{--bg:#ffffff;--panel:#f5f7fa;--border:#e3e8ef;--text:#1f2933;--muted:#6b7280;--btn:#2563eb;--est:#d97706;--title:#111827;--ok:#16a34a}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei","Segoe UI",sans-serif;background:var(--bg);color:var(--text);overflow:hidden;-webkit-tap-highlight-color:transparent}
#hd{position:fixed;top:0;left:0;right:0;z-index:50;display:flex;align-items:center;gap:8px;height:calc(44px + env(safe-area-inset-top));padding:env(safe-area-inset-top) 12px 0;background:var(--panel);border-bottom:1px solid var(--border)}
#dot{width:7px;height:7px;border-radius:50%;background:var(--ok);flex:none;box-shadow:0 0 6px var(--ok);transition:background .2s}
#dot.stale{background:var(--est);box-shadow:0 0 6px var(--est)}
#hd .t{font-size:14px;font-weight:800;color:var(--title);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.25}
#hd .t small{display:block;font-size:10.5px;font-weight:400;color:var(--muted);margin-top:1px;overflow:hidden;text-overflow:ellipsis}
#hd button{background:var(--panel);color:var(--title);border:1px solid var(--border);border-radius:8px;width:30px;height:26px;padding:0;font-size:13px;line-height:1;cursor:pointer;flex:none}
#hd button:active{border-color:var(--btn);color:var(--btn)}
#banner{position:fixed;top:calc(44px + env(safe-area-inset-top));left:8px;right:8px;z-index:49;display:none;background:rgba(242,169,0,.14);border:1px solid rgba(242,169,0,.45);color:var(--est);border-radius:9px;padding:8px 12px;font-size:12px;line-height:1.5}
#framebox{position:fixed;top:calc(44px + env(safe-area-inset-top));left:0;right:0;bottom:calc(50px + env(safe-area-inset-bottom))}
#framebox iframe{position:absolute;inset:0;width:100%;height:100%;border:0;display:none;background:transparent}
#tabbar{position:fixed;bottom:0;left:0;right:0;z-index:50;display:flex;background:var(--panel);border-top:1px solid var(--border);padding:3px 2px calc(3px + env(safe-area-inset-bottom))}
#tabbar button{flex:1;background:none;border:none;color:var(--muted);font-size:10.5px;font-weight:600;padding:3px 0 2px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:1px;min-width:0;position:relative}
#tabbar button .ic{font-size:15px;line-height:1.1;filter:grayscale(.5);opacity:.7;transition:.15s}
#tabbar button.on{color:var(--btn)}
#tabbar button.on .ic{filter:none;opacity:1}
#load{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;background:var(--bg);color:var(--muted);font-size:13px}
#about{position:fixed;inset:0;z-index:70;display:none;background:rgba(0,0,0,.55);align-items:center;justify-content:center;padding:20px}
#about .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;max-width:420px;width:100%;max-height:76vh;overflow:auto;padding:18px;font-size:13px;line-height:1.85}
#about h3{margin:0 0 10px;color:var(--title);font-size:15px}
#about b{color:var(--title)}
#about .x{margin-top:14px;text-align:center}
#about button{padding:8px 22px;border-radius:8px;border:1px solid var(--border);background:var(--panel);color:var(--title);font-size:13px;cursor:pointer}
"""

SHELL_JS = """
var TABS=[['sector','轮动','🧭'],['arb','看板','📈'],['ranking','溢价表','🏆'],['top','LOF','🔥'],
          ['pivot','口袋','🎯'],['cb','转债','💵'],['fish','鱼盆','🐟'],['watch','自选','⭐'],['xlj','寻龙','🐉']];
var TITLES=__TITLES__;
var PAGES=__PAGES__;
var HOME='__HOME__';
var MAXF=3;                 /* 最多保留 3 个 iframe：切回旧 Tab 不重载、保留滚动位置 */
var cur=null,curKey=null,curQS=null,frames={},order=[];
function $(id){return document.getElementById(id)}
function applyTheme(t){
  try{localStorage.setItem('arb_theme',t);}catch(e){}
  document.documentElement.setAttribute('data-theme',t);
  var b=$('themeBtn'); if(b) b.textContent=(t==='light')?'☀️':'🌙';
}
function autoTheme(){var h=new Date().getHours();return (h>=18||h<6)?'dark':'light';}
function dropFrames(){
  for(var k in frames){try{frames[k].parentNode&&frames[k].parentNode.removeChild(frames[k]);}catch(e){}}
  frames={};order=[];
}
function toggleTheme(){
  applyTheme((document.documentElement.getAttribute('data-theme')==='light')?'dark':'light');
  dropFrames();                 /* 主题变→重建当前页（其余页下次进入重建，均有缓存不慢） */
  if(cur) openTab(cur,curQS);
}
function buildTabbar(){
  $('tabbar').innerHTML=TABS.map(function(t){
    return '<button data-tab="'+t[0]+'" onclick="openTab(\\''+t[0]+'\\')"><span class="ic">'+t[2]+'</span>'+t[1]+'</button>';
  }).join('');
}
function markTab(){
  var bs=$('tabbar').children;
  for(var i=0;i<bs.length;i++) bs[i].className=(bs[i].getAttribute('data-tab')===cur)?'on':'';
  var s=$('sub'); if(s) s.textContent=(TITLES[cur]||'')+' · 断网自动用缓存';
  hideBanner(); setDot(false);
}
function setDot(stale){var d=$('dot'); if(d) d.className=stale?'stale':'';}
function makeFrame(tab,qs){
  var html=PAGES[tab];
  if(qs){
    var inj='<scr'+'ipt>window.__QS__='+JSON.stringify(qs)+';</scr'+'ipt>';
    html=html.replace('<head>','<head>'+inj);
  }
  var ifr=document.createElement('iframe');
  ifr.setAttribute('data-tab',tab);
  ifr.srcdoc=html;
  return ifr;
}
function openTab(tab,qs){
  if(!PAGES[tab]) return;
  var key=tab+(qs?('|'+qs):'');
  cur=tab; curKey=key; curQS=qs||null;
  markTab();
  var box=$('framebox'), f=frames[key], fresh=false;
  if(!f){
    f=makeFrame(tab,qs); frames[key]=f; fresh=true;
    order.push(key);
    f.addEventListener('load',function(){ if(curKey===key) $('load').style.display='none'; });
    box.appendChild(f);
    while(order.length>MAXF){
      var old=order.shift();
      if(old===curKey||!frames[old]) continue;
      var victim=frames[old];
      delete frames[old];
      victim.style.display='none';
      /* 延迟移除：让该页在途请求先结束，避免其回调操作已销毁的文档而报错 */
      setTimeout(function(f){try{f.parentNode&&f.parentNode.removeChild(f);}catch(e){}},3000,victim);
    }
  }
  for(var k in frames) frames[k].style.display=(k===key)?'block':'none';
  if(fresh) $('load').style.display='flex';   /* 首次进入才显示占位，切回旧页瞬开 */
  else $('load').style.display='none';
}
/* 强制刷新：打标记让 shim 跳过新鲜缓存，重建当前页 */
function hardRefresh(){
  try{localStorage.setItem('fam_force',String(Date.now()));}catch(e){}
  dropFrames();
  if(cur) openTab(cur,curQS);
}
function showBanner(msg){var b=$('banner');b.textContent=msg;b.style.display='block';}
function hideBanner(){$('banner').style.display='none';}
function openAbout(){ $('about').style.display='flex'; }
window.addEventListener('message',function(e){
  var m=e.data||{};
  if(m.fa==='tab') openTab(m.tab);
  else if(m.fa==='code') openTab('arb','?code='+m.code);
  else if(m.fa==='xlj') openTab('xlj');
  else if(m.fa==='stale'){
    var d=m.t?new Date(m.t):null;
    setDot(true);
    showBanner('⚠️ 网络暂不可用，显示缓存数据'+(d?('（'+d.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})+' 更新）'):'')+'，点「⟳」重试');
  }
  else if(m.fa==='live'){ setDot(false); hideBanner(); }
});
(function(){
  var t=autoTheme();
  try{t=localStorage.getItem('arb_theme')||t;}catch(e){}
  applyTheme(t); buildTabbar();
  openTab(PAGES[HOME]?HOME:(TABS[0][0]));   /* 首页固定为「轮动」 */
})();
"""

SHELL_ABOUT = """
<h3>📱 使用说明</h3>
<b>首页</b>：打开即是「行业轮动」；底部 9 个标签切换全部功能。<br>
<b>数据来源</b>：fund-arb.onrender.com（需联网）。取数成功的数据会存在手机本地并按接口缓存几十秒到十几分钟，切页几乎秒开；断网时显示最近一次缓存，顶部黄条标注时间，右上小圆点变黄。<br>
<b>刷新</b>：点 ⟳ 强制绕过缓存重新取数；切回看过的页面不会重载（保留滚动位置）。<br>
<b>保存到手机（iPhone）</b>：用微信「文件传输助手」/隔空投送/iCloud 存到「文件」App → 点开 → 分享 → 用 Safari 打开。<br>
<b>保存到手机（Android）</b>：存到下载目录，用 Chrome / Edge 打开即可。<br>
<b>添加到主屏幕</b>：浏览器菜单里选「添加到主屏幕」，之后像 App 一样点开。<br>
<b>提示</b>：Render 免费实例冷启动约 30-60 秒，首次加载慢属正常。
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
    pages, ok = {}, True
    print("改写页面：")
    for tab, fname in PAGE_FILES.items():
        html = prep_page(load(fname), tab)
        ok = check_page(fname, html, tab) and ok
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
    pages["xlj"] = prep_page(xlj_html, "xlj")

    pages_js = "{" + ",".join('"%s":%s' % (k, js_embed(v)) for k, v in pages.items()) + "}"
    js = (SHELL_JS.replace("__TITLES__", json.dumps(TAB_TITLES, ensure_ascii=False))
                  .replace("__PAGES__", pages_js)
                  .replace("__HOME__", HOME_TAB))
    favicon = (
        '<link rel="icon" href="data:image/svg+xml,'
        '<svg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27>'
        '<circle cx=%2716%27 cy=%2717%27 r=%279%27 fill=%27none%27 stroke=%27%231f6feb%27 stroke-width=%273%27/>'
        '<path d=%27M7 11L16 5l9 6%27 fill=%27none%27 stroke=%27%23ef4444%27 stroke-width=%273%27/>'
        '<path d=%27M7 23l9 6 9-6%27 fill=%27none%27 stroke=%27%2322c55e%27 stroke-width=%273%27/></svg>">\n'
    )
    shell = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<meta name=\"theme-color\" content=\"#0d1117\">\n"
        "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">\n"
        + favicon +
        "<title>套利工具平台 · 手机版</title>\n<style>" + SHELL_CSS + "</style>\n</head>\n<body>\n"
        "<div id=\"hd\"><span id=\"dot\"></span>"
        "<div class=\"t\">套利工具平台<small id=\"sub\">行业轮动 · 断网自动用缓存</small></div>"
        "<button id=\"themeBtn\" onclick=\"toggleTheme()\">🌙</button>"
        "<button onclick=\"hardRefresh()\" title=\"强制刷新\">⟳</button>"
        "<button onclick=\"openAbout()\" title=\"使用说明\">ⓘ</button></div>\n"
        "<div id=\"banner\"></div>\n<div id=\"framebox\"></div>\n<div id=\"tabbar\"></div>\n"
        "<div id=\"load\">加载中…</div>\n"
        "<div id=\"about\"><div class=\"card\">" + SHELL_ABOUT + "</div></div>\n"
        "<script>" + js + "</script>\n</body>\n</html>"
    )
    out = os.path.join(HERE, OUT_NAME)
    with open(out, "w", encoding="utf-8") as f:
        f.write(shell)

    print("\n自检：首页=%s(%s) ｜ BASE=%s ｜ 页面数=%d ｜ 输出 %.1f KB"
          % (HOME_TAB, TAB_TITLES[HOME_TAB], ONLINE, len(pages), len(shell.encode("utf-8")) / 1024))
    if "localhost:8000" in shell:
        raise SystemExit("产物中残留 localhost:8000，请检查改写规则")
    for ph in ("__TITLES__", "__PAGES__", "__HOME__", "__TAB__", "__NAVMAP__", "__PREFETCH__"):
        if ph in shell:
            raise SystemExit("产物中残留占位符 %s" % ph)
    if port_in_use(8000):
        print("提示：本机 8000 端口正被占用（本地预览服务在跑，不影响手机版）。"
              "\n      如需重启本地服务：先结束占用进程再 python fund_arb.py")
    print("已生成:", out)


if __name__ == "__main__":
    main()
