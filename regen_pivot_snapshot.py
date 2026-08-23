#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机一键重导口袋支点快照（需国内网络可访问东财）。

修复要点：
  旧逻辑 trade_date 用"运行时刻 bj_now()"，若抓取时东财当日 K 线未入库，
  会出现"标签 8/21、数值 8/20"的错位。
  现 trade_date 改为"全市场 K 线末根最晚交易日"，数值与标签强制对齐。

用法：
  cd D:/Workbuddy/yetawas-personal-pwa
  python regen_pivot_snapshot.py
  （扫描全市场约 3-6 分钟，完成后自动写 pivot_snapshot.json 并自校验）
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fund_arb as fa


def progress(done, total, phase):
    if done % 200 == 0 or done == total:
        print(f"  [{phase}] {done}/{total}")


def main():
    print("▶ 开始全市场口袋支点扫描（约 3-6 分钟，请勿关闭）...")
    res = fa.pivot_scan(progress=progress)
    td = res.get("trade_date")
    kld = res.get("kline_last_date")
    print(f"▶ 扫描完成：trade_date={td}, kline_last_date={kld}, 命中 {res.get('total_picks')} 只")
    if td != kld:
        print(f"  [WARN] 标签与 K 线末根不一致！数据可能仍错位，请检查网络/东财入库情况。")
        return
    fa._pivot_save_disk(res)
    print(f"▶ 已写入 pivot_snapshot.json（trade_date={td}）")
    # 自校验
    print("\n▶ 自校验数据日期自洽性：")
    try:
        import verify_pivot_date as v
        v.main()
    except Exception as e:
        print(f"  校验脚本异常（可手动跑 python verify_pivot_date.py）：{e}")


if __name__ == "__main__":
    main()
