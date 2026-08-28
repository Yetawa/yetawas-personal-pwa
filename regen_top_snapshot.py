#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 TOP 套利榜「仓库内置快照」top_snapshot.json，可选自动推送 GitHub。

为什么需要它
------------
onrender（美西节点）访问 push2.eastmoney.com 在 **HTTP 层被断连**，故线上永远
算不出实时 TOP 榜，只能读快照。而 onrender 每次重新部署都会清空本地磁盘，
磁盘缓存 fund_arb_cache_top.json 丢失 —— 必须有一份随源码提交的
top_snapshot.json，线上才能"打开即有数据"。本脚本在**可访问东财的环境（国内）**
生成这份快照并推送，实现线上每日自动更新。

关于「下午 3 点整」
------------------
A 股 15:00 收盘，但东财行情/K 线入库有约 10~15 分钟延迟。若 15:00 整抓取，
K 线末根很可能仍是上一交易日，直接造成「标签 15:00 当天、数值前一天」的错位
（用户三令五申的数据日期铁律）。

因此本脚本默认 15:15，并且**无论设成几点，都会先做「数据就绪校验」**：
轮询上证指数日 K 末根日期，确认等于目标交易日才动工；未就绪则等待重试，
直到数据真实入库（或超过 --deadline 放弃）。所以即使 --at 15:00 也安全。

用法
----
    python regen_top_snapshot.py                    # 跑一次：等数据就绪 → 生成 → 推送
    python regen_top_snapshot.py --at 15:15         # 等到 15:15 再开始（默认即 15:15）
    python regen_top_snapshot.py --at 15:00         # 想 3 点整启动也行，会自动等数据
    python regen_top_snapshot.py --no-push          # 只生成，不推 GitHub
    python regen_top_snapshot.py --daemon           # 常驻：每交易日自动跑（不退出）

定时任务（Windows，每天自动跑一次，推荐）
----------------------------------------
    schtasks /Create /TN "FundArbTopSnapshot" /TR
      "python D:\\Workbuddy\\yetawas-personal-pwa\\regen_top_snapshot.py"
      /SC DAILY /ST 15:15 /F

环境变量
--------
    GH_TOKEN  推送所需（不设则跳过推送，仅本地生成）
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_PATH = os.path.join(HERE, "top_snapshot.json")
REPO = ("Yetawa", "yetawas-personal-pwa", "main")
API = "https://api.github.com"

# 上证指数日 K，用来判断「当日行情是否已入库」
BENCH_SECIDs = [("1.000001", "上证指数"), ("0.399001", "深证成指")]


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


# --------------------------------------------------------------------------
# 交易日历：优先复用 fund_arb 的实现（含法定节假日表），失败时退化为周末判断
# --------------------------------------------------------------------------
try:
    sys.path.insert(0, HERE)
    import fund_arb as F

    def last_trading_day():
        return F._last_trading_day()

    def is_trading_day(d):
        return F._is_trading_day(d)

    def bj_now():
        return F.bj_now()

    HAS_FUND_ARB = True
except Exception as _e:                                   # pragma: no cover
    HAS_FUND_ARB = False
    _IMPORT_ERR = _e

    def bj_now():
        return datetime.utcnow() + timedelta(hours=8)

    def is_trading_day(d):
        return d.weekday() < 5

    def last_trading_day():
        d = bj_now()
        while not is_trading_day(d):
            d -= timedelta(days=1)
        return d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# 数据就绪校验
# --------------------------------------------------------------------------
def kline_last_date(secid, timeout=10):
    """取某标的日 K 末根日期（YYYY-MM-DD）。失败返回 None。"""
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?secid=%s&klt=101&fqt=1&lmt=3&end=20500101"
           "&fields1=f1,f2,f3,f4,f5,f6"
           "&fields2=f51,f52,f53,f56,f57,f58,f59,f60,f61" % secid)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0",
                      "Referer": "https://quote.eastmoney.com/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        ks = ((d.get("data") or {}).get("klines") or [])
        if not ks:
            return None
        return str(ks[-1]).split(",")[0]
    except Exception:
        return None


def data_ready(target, timeout=10):
    """当日行情是否已入库：任一基准指数日 K 末根日期 == target 即认为就绪。"""
    for secid, name in BENCH_SECIDs:
        got = kline_last_date(secid, timeout)
        if got:
            return got == target, name, got
    return False, "基准指数", None


def wait_until_ready(target, deadline_min="16:30", interval=180, verbose=True):
    """轮询等待数据就绪。返回 True/False。

    interval 默认 180 秒（3 分钟）——东财入库通常在收盘后 10~15 分钟内完成，
    3 分钟一次既能及时捕获又不会频繁打扰。
    """
    hh, mm = [int(x) for x in deadline_min.split(":")]
    while True:
        now = bj_now()
        if now.hour > hh or (now.hour == hh and now.minute >= mm):
            log("已过截止时刻 %s，仍未等到 %s 的数据，放弃本次生成" % (deadline_min, target))
            return False
        ok, name, got = data_ready(target)
        if ok:
            log("数据就绪：%s 日K末根日期 = %s（目标 %s）" % (name, got, target))
            return True
        if verbose:
            log("数据未就绪（%s 末根 = %s，目标 %s），%d 秒后重试…"
                % (name, got, target, interval))
        time.sleep(interval)


# --------------------------------------------------------------------------
# 生成 + 推送
# --------------------------------------------------------------------------
def build(target, threshold=1.5, dgate=-2.0, top_n=500):
    """调用 fund_arb 的全市场扫描，返回 (rows, meta)。

    top_n 取 500：快照是「全量候选池」，页面上的阈值/折价筛选由
    _top_finalize 在内存里做，因此快照必须尽量全，否则用户调阈值会漏标的。
    """
    if not HAS_FUND_ARB:
        raise RuntimeError("无法 import fund_arb：%s" % _IMPORT_ERR)
    res = F.compute_top_arbitrage(target, threshold, dgate, top_n=top_n)
    rows = res.get("rows") or []
    meta = {k: res.get(k) for k in
            ("date", "universe", "tradable", "candidates") if k in res}
    return rows, meta


def write_snap(rows, meta, target):
    payload = {
        "ts": time.time(),
        "date": target,
        "generated_at": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe": meta.get("universe", 0),
        "tradable": meta.get("tradable", 0),
        "candidates": meta.get("candidates", 0),
        "rows": rows,
    }
    tmp = SNAP_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, SNAP_PATH)
    log("已写入 %s：date=%s，%d 候选行" % (os.path.basename(SNAP_PATH), target, len(rows)))
    return payload


def gh_push():
    """用 Contents API 单文件推送 top_snapshot.json（需 GH_TOKEN）。"""
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        log("未设置 GH_TOKEN，跳过推送（快照已写入本地）")
        return False

    def api(path, method="GET", data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(API + path, data=body, method=method, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "regen-top-snapshot"})
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return {"_err": e.code, "_msg": e.read().decode()[:300]}

    p = "/repos/%s/%s/contents/top_snapshot.json?ref=%s" % REPO
    cur = api(p)
    sha = cur.get("sha") if isinstance(cur, dict) else None
    raw = open(SNAP_PATH, "rb").read()
    d = api("/repos/%s/%s/contents/top_snapshot.json" % (REPO[0], REPO[1]), "PUT", {
        "message": "data(top): 更新 TOP 套利榜内置快照 %s" % bj_now().strftime("%Y-%m-%d"),
        "content": base64.b64encode(raw).decode(),
        "branch": REPO[2],
        **({"sha": sha} if sha else {}),
    })
    if "_err" in d:
        log("推送失败：%s %s" % (d["_err"], d.get("_msg", "")))
        return False
    log("已推送 GitHub：%s" % str((d.get("commit") or {}).get("sha", ""))[:10])
    return True


# --------------------------------------------------------------------------
def run_once(at=None, do_push=True, deadline="16:30", interval=180, force=False):
    """执行一次完整流程。返回是否成功。"""
    # 先判断今天是否该跑：若非交易日，等到 --at 也没意义，直接跳过，
    # 否则周末启动会白等好几个小时才退出。
    if not is_trading_day(bj_now()) and not force:
        log("今日 %s 非交易日，跳过（最近交易日 = %s）。"
            "如需强制生成请加 --force"
            % (bj_now().strftime("%Y-%m-%d"), last_trading_day()))
        return False

    if at:
        hh, mm = [int(x) for x in at.split(":")]
        now = bj_now()
        tgt_dt = datetime(now.year, now.month, now.day, hh, mm)
        if now < tgt_dt:
            wait_s = (tgt_dt - now).total_seconds()
            log("等待至 %s（还需 %d 秒）…" % (at, int(wait_s)))
            time.sleep(wait_s)

    target = last_trading_day()

    log("目标交易日 = %s（行情源=%s）" % (target, "OK" if HAS_FUND_ARB else "import 失败"))

    if not wait_until_ready(target, deadline_min=deadline, interval=interval):
        return False

    rows, meta = build(target)
    if not rows:
        log("扫描结果为空，不覆盖现有快照（避免把好数据洗成空）")
        return False
    if meta.get("date") and meta["date"] != target:
        log("扫描返回日期 %s ≠ 目标 %s，放弃写入（防止标签与数值错位）"
            % (meta["date"], target))
        return False

    write_snap(rows, meta, target)
    if do_push:
        gh_push()
    return True


def main():
    ap = argparse.ArgumentParser(description="生成并推送 TOP 套利榜内置快照")
    ap.add_argument("--at", default="15:15",
                    help="开始时刻 HH:MM（默认 15:15）。设 15:00 也会自动等数据就绪")
    ap.add_argument("--deadline", default="16:30",
                    help="等不到数据就放弃的时刻（默认 16:30）")
    ap.add_argument("--interval", type=int, default=180,
                    help="数据就绪轮询间隔秒（默认 180）")
    ap.add_argument("--no-push", action="store_true", help="只生成，不推 GitHub")
    ap.add_argument("--force", action="store_true",
                    help="非交易日也生成（一般用于测试）")
    ap.add_argument("--daemon", action="store_true",
                    help="常驻：每交易日跑一次（配合 --at）")
    a = ap.parse_args()

    if not a.daemon:
        ok = run_once(a.at, not a.no_push, a.deadline, a.interval, a.force)
        sys.exit(0 if ok else 1)

    log("常驻模式启动：每交易日 %s 生成快照" % a.at)
    done = set()
    while True:
        try:
            t = last_trading_day()
            if t not in done and is_trading_day(bj_now()):
                if run_once(a.at, not a.no_push, a.deadline, a.interval, a.force):
                    done.add(t)
        except KeyboardInterrupt:
            log("已退出")
            return
        except Exception as e:
            log("异常：%s（60 秒后继续）" % e)
        time.sleep(60)


if __name__ == "__main__":
    main()
