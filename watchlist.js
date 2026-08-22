/* 自选池公共脚本：长按/右键基金代码 → 加入自选池（localStorage 共享） */
(function () {
  var KEY = 'watchlist';
  function loadW() { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; } }
  function saveW(a) { try { localStorage.setItem(KEY, JSON.stringify(a)); } catch (e) {} }
  function norm(code) { return String(code || '').trim().replace(/^(sh|sz|bj)/i, '').toUpperCase(); }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function toast(msg) {
    var t = document.getElementById('wlToast');
    if (!t) {
      t = document.createElement('div'); t.id = 'wlToast';
      t.style.cssText = 'position:fixed;left:50%;bottom:26%;transform:translateX(-50%);background:rgba(15,19,28,.94);color:#e6edf7;padding:9px 18px;border-radius:9px;font-size:13px;z-index:99999;border:1px solid #2f3b52;box-shadow:0 6px 22px rgba(0,0,0,.4);pointer-events:none';
      document.body.appendChild(t);
    }
    t.textContent = msg; t.style.display = 'block';
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.style.display = 'none'; }, 1600);
  }
  // 公开：添加自选（长按/右键/手动共用）
  window.addToWatch = function (code, name) {
    code = norm(code);
    if (!code || !/^\d{6}$/.test(code)) { toast('代码格式不对'); return false; }
    var arr = loadW();
    if (arr.some(function (x) { return norm(x.code) === code; })) { toast('已在自选池'); return false; }
    arr.unshift({ code: code, name: name || '', date: today(), wlprice: null });
    saveW(arr);
    toast('已加入自选池：' + code);
    return true;
  };
  // 事件委托：右键/长按 a.codelink → 添加
  var longTimer = null;
  function tryAdd(a) {
    if (!a) return;
    var code = a.getAttribute('data-code') || a.textContent.trim();
    addToWatch(code, a.getAttribute('data-name') || '');
  }
  document.addEventListener('contextmenu', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a.codelink') : null;
    if (a) { e.preventDefault(); tryAdd(a); }
  });
  document.addEventListener('touchstart', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a.codelink') : null;
    if (!a) return;
    longTimer = setTimeout(function () {
      if (navigator.vibrate) { try { navigator.vibrate(25); } catch (e) {} }
      tryAdd(a);
    }, 700);
  }, { passive: true });
  ['touchend', 'touchmove', 'touchcancel'].forEach(function (ev) {
    document.addEventListener(ev, function () { clearTimeout(longTimer); }, { passive: true });
  });
})();
