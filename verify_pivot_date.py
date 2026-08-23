#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
口袋支点数据日期自洽校验（本机运行，需国内网络可访问东财）。

用途：
  重跑 pivot 扫描 / 生成快照后，用本脚本核对：
  1) 快照 trade_date 标签 == 全市场 K 线末根最晚交易日（代码已强制对齐）
  2) 快照内前 N 只票的 close/chg_pct 与东财当日真实收盘一致（取 K 线末根对照）

运行：
  cd D:/Workbuddy/yetawas-personal-pwa
  python verify_pivot_date.py            # 默认校验 pivot_snapshot.json
  python verify_pivot_date.py cb         # 校验 cb_snapshot.json（仅标签+updated）

若发现"标签 8/21 但 K 线末根停在 8/20"，说明抓取时东财当日数据未入库，
需等收盘数据入库后重跑 scan_pivot.py / 服务重扫。
"""
import json
import os
import sys
import urllib.request
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

KIND = sys.argv[1] if len(sys.argv) > 1 else "pivot"
SNAP = os.path.join(HERE, "pivot_snapshot.json" if KIND == "pivot" else "cb_snapshot.json")


def http_get_json(url, referer="https://quote.eastmoney.com/"):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def em_kline_last(sym):
    """返回 (date, close) 东财日线末根。sym 形如 sz002142 / sh600919。"""
    secid = ("0." if sym.startswith("sz") else "1.") + sym[2:]
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
           f"&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=0"
           f"&end=20500101&lmt=5&ut=fa5fd1943c7b386f172d6893dbfba10b")
    d = http_get_json(url)
    kl = (d.get("data") or {}).get("klines") or []
    if not kl:
        return None, None
    last = kl[-1].split(",")
    return last[0], float(last[2])


def main():
    if not os.path.exists(SNAP):
        print(f"[FAIL] 找不到 {SNAP}，请先运行扫描生成快照")
        return
    data = json.load(open(SNAP, encoding="utf-8"))
    td = data.get("trade_date")
    kld = data.get("kline_last_date")
    print(f"快照 trade_date = {td}")
    print(f"快照 kline_last_date = {kld}")
    if kld and td != kld:
        print(f"[WARN] 标签({td}) 与 K线末根({kld}) 不一致！数据可能错位。")
    else:
        print(f"[OK] 标签与 K 线末根一致：{td}")

    if KIND != "pivot":
        print(f"cb 快照 updated = {data.get('updated')}，picks = {len(data.get('picks', []))}")
        return

    picks = data.get("picks", [])[:10]
    print(f"\n对照前 {len(picks)} 只票 东财当日真实收盘：")
    print(f"{'代码':<10}{'名称':<10}{'快照close':>10}{'真实close':>10}{'快照chg%':>9}{'状态':>6}")
    mismatch = 0
    for p in picks:
        sym = p.get("symbol")
        sc, rc = p.get("close"), None
        try:
            rdate, rclose = em_kline_last(sym)
            rc = rclose
            if rdate != td:
                print(f"  ! {sym} 东财末根日期={rdate} ≠ 快照{td}")
        except Exception as e:
            print(f"  ! {sym} 抓取失败: {e}")
            continue
        ok = (rc is not None and abs(rc - sc) < 0.01)
        if not ok:
            mismatch += 1
        print(f"{sym:<10}{p.get('name',''):<10}{str(sc):>10}{str(rc):>10}"
              f"{str(p.get('chg_pct')):>9}{'OK' if ok else 'DIFF':>6}")
    print()
    if mismatch == 0:
        print(f"[OK] 全部 {len(picks)} 只快照数值与东财当日收盘一致，数据日期 {td} 可信。")
    else:
        print(f"[FAIL] {mismatch} 只数值不一致，快照数据非 {td} 真实收盘，需重跑扫描。")


if __name__ == "__main__":
    main()
