#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_sector_data.py — 生成行业轮动日更快照 sector_data.json

设计目标（方案A：GitHub + onrender 日更路线）：
  onrender 美国节点无法访问东方财富，故「取数」这步不能放在线上。
  本脚本在【能访问东财的国内网络】环境（你本机 / CloudStudio 工作区）运行，
  收盘后拉取申万一级行业实时涨跌+主力净流入，生成 sector_data.json 并提交 GitHub，
  onrender 自动部署后，前端 /sector 直接 fetch 这个同源静态 JSON，每天显示最新交易日。

依赖：仅 Python 标准库（urllib / json / time / datetime / random）。
用法：
  python gen_sector_data.py            # 仅生成本地 sector_data.json
  python gen_sector_data.py --push     # 生成并提交 push 到 main（须在工作区内）
  python gen_sector_data.py --date 2026-08-13  # 指定交易日（默认今天），便于补跑/测试

注意：SECTOR_BK 须与 fund_arb.py 的 SECTOR_BK 保持一致（复制自该处）。
"""
import os
import sys
import json
import time
import random
import datetime
import urllib.request
import argparse

# ---- 申万一级行业 BK 代码映射（与 fund_arb.py 的 SECTOR_BK 一致） ----
SECTOR_BK = {
    "电子": "BK1201", "通信": "BK1215", "计算机": "BK1207", "传媒": "BK0486", "电力设备": "BK1200",
    "机械设备": "BK1205", "国防军工": "BK1204", "汽车": "BK1211", "家用电器": "BK0456", "食品饮料": "BK0438",
    "纺织服饰": "BK0436", "轻工制造": "BK1212", "医药生物": "BK1216", "公用事业": "BK0427", "交通运输": "BK1210",
    "房地产": "BK1202", "商贸零售": "BK1213", "社会服务": "BK1214", "综合": "BK1217", "建筑材料": "BK1208",
    "建筑装饰": "BK1209", "农林牧渔": "BK0433", "基础化工": "BK1206", "钢铁": "BK0479", "有色金属": "BK0478",
    "石油石化": "BK0464", "煤炭": "BK0437", "环保": "BK0728", "美容护理": "BK1035", "银行": "BK1283",
    "非银金融": "BK1203",
}

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def fetch_today():
    """多镜像域名轮询+重试，返回 {name:{chg,main}} 或 None。逻辑同 fund_arb.py._sector_live_payload。"""
    secids = ",".join("90." + b for b in SECTOR_BK.values())
    fields = "f3,f12,f14,f62"
    hosts = ["%d.push2.eastmoney.com" % random.randint(1, 99) for _ in range(8)]
    hosts += ["push2.eastmoney.com", "push2delay.eastmoney.com"]
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    last_err = None
    for host in hosts:
        try:
            url = ("https://%s/api/qt/ulist.np/get?fields=%s&secids=%s"
                   "&ut=fa5fd1943c7b386f172d6893dbfba10b&_=%d" % (
                       host, fields, secids, int(time.time() * 1000)))
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json, text/plain, */*",
            })
            with urllib.request.urlopen(req, timeout=8) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            diff = ((j or {}).get("data") or {}).get("diff") or []
            ind = {}
            for x in diff:
                name = x.get("f14")
                chg = x.get("f3")
                main = x.get("f62")
                if not name:
                    continue
                ind[name] = {
                    "chg": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
                    "main": round((main or 0) / 1e8, 2) if isinstance(main, (int, float)) else None,
                }
            if ind:
                return ind
            last_err = "empty diff from " + host
        except Exception as e:
            last_err = str(e)
            continue
    sys.stderr.write("fetch_today failed: %s\n" % (last_err or "all hosts failed"))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="生成后 git add/commit/push 到 main")
    ap.add_argument("--date", default=None, help="指定交易日 YYYY-MM-DD（默认今天）")
    args = ap.parse_args()

    if args.date:
        today = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = datetime.date.today()

    # 周末非交易日：跳过，避免把上周五收盘误写成「今日」
    if today.weekday() >= 5:
        sys.stderr.write("SKIP: %s 为周末，非交易日，不更新快照\n" % today.isoformat())
        sys.exit(0)

    ind = fetch_today()
    if not ind:
        # 取数失败：保留现有文件，避免覆盖成空数据
        sys.stderr.write("WARN: 东财取数失败，未覆盖现有 sector_data.json\n")
        sys.exit(2)

    label = today.strftime("%m-%d") + " " + _WEEKDAYS[today.weekday()]
    entry = {
        "label": label,
        "source": "东方财富实时行情接口(ulist.np) 收盘数据 · 主力净流入=超大单+大单",
        "industries": ind,
    }

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "sector_data.json")
    prev = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    days = dict(prev.get("days", {}))
    days[today.isoformat()] = entry
    # 仅保留最新 5 个交易日（滚动窗口）
    keys = sorted(days.keys(), reverse=True)[:5]
    days = {k: days[k] for k in keys}

    D = {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": today.isoformat(),
        "bk": SECTOR_BK,
        "days": days,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=1)
    print("OK sector_data.json today=%s industries=%d (保留%d天)" % (
        today.isoformat(), len(ind), len(days)))

    if args.push:
        import subprocess
        # GH_PROXY 环境变量（由 bat 注入）：指定镜像代理地址，避免直连 github.com。
        # 例：https://ghproxy.net  —— 留空则信任本机 git 全局配置。
        proxy = (os.environ.get("GH_PROXY") or "").strip().rstrip("/")
        git_base = ["git"]
        if proxy:
            git_base += ["-c",
                         "url.%s/https://github.com/.insteadOf=https://github.com/" % proxy]
        # 非交互（任务计划）环境下，强制 GCM 静默读取 Windows 凭据管理器缓存的 PAT，
        # 避免 helper-selector 弹窗导致挂起。若报 credential.helper 找不到，改成 manager。
        git_base += ["-c", "credential.helper=manager-core"]
        try:
            subprocess.run(git_base + ["add", "sector_data.json"], check=True, cwd=here)
            msg = "chore: 更新行业轮动快照 %s" % today.isoformat()
            subprocess.run(git_base + ["commit", "-m", msg], check=True, cwd=here)
            subprocess.run(git_base + ["push", "origin", "main"], check=True, cwd=here)
            print("PUSHED -> origin/main")
        except subprocess.CalledProcessError as e:
            sys.stderr.write("git push 失败: %s\n" % e)
            sys.exit(3)


if __name__ == "__main__":
    main()
