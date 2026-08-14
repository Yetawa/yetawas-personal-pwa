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

# ---- 指数 / 风格指数 secid（东财 ulist.np，格式 market.code） ----
INDEX_SECIDS = {
    "1.000001": "上证指数", "0.399001": "深证成指", "0.399006": "创业板指",
    "1.000300": "沪深300", "1.000688": "科创50", "0.899050": "北证50",
    "0.399372": "大盘成长", "0.399373": "大盘价值", "0.399376": "小盘成长",
    "0.399377": "小盘价值", "1.000016": "上证50", "1.000852": "中证1000",
}
INDEX_NAMES = ["上证指数", "深证成指", "创业板指", "沪深300", "科创50", "北证50"]
STYLE_NAMES = ["大盘成长", "大盘价值", "小盘成长", "小盘价值", "上证50", "中证1000"]

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


def _fetch_quotes(secids_map):
    """多镜像域名轮询，返回 {name:[price, chg%]} 或 {}。price=f2/100, chg=f3/100。"""
    secids = ",".join(secids_map.keys())
    # 东财返回 f12 为不带市场前缀的代码（如 000001），故按代码末段建映射
    codemap = {s.split(".")[-1]: n for s, n in secids_map.items()}
    fields = "f2,f3,f12,f14"
    hosts = ["%d.push2.eastmoney.com" % random.randint(1, 99) for _ in range(8)]
    hosts += ["push2delay.eastmoney.com", "push2.eastmoney.com"]
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    out = {}
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
            for x in diff:
                code = x.get("f12")
                name = codemap.get(code)
                if not name:
                    continue
                price = x.get("f2")
                chg = x.get("f3")
                if not isinstance(price, (int, float)):
                    continue
                out[name] = [round(price / 100, 2), round((chg or 0) / 100, 2)]
            if out:
                return out
        except Exception:
            continue
    return out


# 静态板块（北向/两融/研判/ETF 文案与参考）—— 北向、两融日期在生成时更新为当日
_STATIC_JSON = """{
 "north": {
  "date": "2026-08-12",
  "turnover": 2822.87,
  "cumTrillion": 251.2,
  "note": "2024-08-19 起北向资金不再披露每日净买入/净卖出，仅披露陆股通成交额；故无法提供每日净买入趋势，以下以成交额衡量活跃度。"
 },
 "margin": {
  "date": "2026-08-11",
  "balance": 26633.29,
  "delta": 11.73
 },
 "judge": [
  [
   "科技制造主线未改，但警惕短期拥挤",
   "通信、电子连续获主力集中加仓——08-07 电子单日净流入 282.97 亿、08-12 通信+129 亿/电子+101 亿，AI算力(CPO/PCB/半导体)仍是资金最密集方向。但 08-10、08-11 电子、通信曾单日大幅净流出(合计超 360 亿)，显示涨幅过快后分歧显著，追高需控仓，宜沿 5/10 日线分批。"
  ],
  [
   "成长风格占优，价值提供防御底座",
   "08-12 小盘成长 +1.05% 显著跑赢大盘价值 -0.50%，全周成长(大盘成长+1.24%/小盘成长+1.05%)持续占优；但银行、煤炭、石油石化等价值/红利板块在波动期展现抗跌属性。建议以成长(通信/电子ETF)为矛、红利(银行/煤炭ETF)为盾的哑铃配置。"
  ],
  [
   "周期躁动持续性弱，消费复苏待验证",
   "煤炭、有色等周期在 08-06/08-07 冲高后于 08-11 大幅回撤(有色金属 -4.42%/-138 亿)，说明周期行情多为事件/情绪驱动、持续性差；大消费(食品饮料/家电/医药)在 08-10 后分化，医药 08-07 大涨后回落。消费与医药宜等待基本面或资金面拐点信号，逢低布局优于追涨。"
  ]
 ],
 "etfs": [
  ["通信 / CPO", "通信ETF", "515880", "光模块、5.5G 主线，与电子联动最强"],
  ["电子 / 半导体", "电子50ETF", "515320", "覆盖半导体、消费电子；或 半导体ETF 512480"],
  ["科创芯片", "科创芯片ETF", "588290", "国产算力、先进制程核心标的"],
  ["电力设备 / 新能源", "新能源ETF", "516160", "光伏、锂电、储能龙头集合"],
  ["汽车", "汽车ETF", "516110", "含智能化、零部件；与机器人链重叠"],
  ["机械设备 / 机器人", "机器人ETF", "562500", "人形机器人、工业自动化主题"],
  ["国防军工", "军工ETF", "512660", "航空装备、军工电子，事件驱动型"],
  ["有色金属", "有色ETF", "512940", "铜、铝、黄金、小金属；周期弹性"],
  ["煤炭", "煤炭ETF", "515220", "高股息红利、低估值防御"],
  ["医药生物", "生物医药ETF", "159508", "CXO、创新药、生物制品"],
  ["食品饮料", "食品饮料ETF", "516900", "白酒+大众消费，复苏预期"],
  ["房地产", "地产ETF", "159707", "政策博弈、估值修复"],
  ["银行", "银行ETF", "512800", "高股息、低估值红利压舱石"],
  ["非银金融 / 券商", "券商ETF", "512000", "行情β与资本市场改革受益"],
  ["计算机 / 软件", "软件ETF", "561010", "AI应用、信创、工业软件"],
  ["建筑材料", "建材ETF", "159745", "地产链后周期、基建催化"],
  ["环保", "环保ETF", "159861", "水务、固废、绿电运营"],
  ["农林牧渔", "养殖ETF", "159865", "生猪养殖周期+饲料"],
  ["钢铁", "钢铁ETF", "515210", "特钢、普钢，并购重组主题"],
  ["基础化工", "化工ETF", "516020", "钛白粉、化肥、新材料"],
  ["交通运输", "交运ETF", "561320", "快递、航运、高股息公路铁路"]
 ]
}"""


def _static_sections(today):
    try:
        s = json.loads(_STATIC_JSON)
    except Exception:
        return {}
    s["north"]["date"] = today.isoformat()
    s["margin"]["date"] = today.isoformat()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="生成后 git add/commit/push 到 main")
    ap.add_argument("--date", default=None, help="指定交易日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--force-preclose", action="store_true",
                    help="强制在15:00收盘前也抓取（仅盘前/昨收快照，慎用）")
    args = ap.parse_args()

    if args.date:
        today = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = datetime.date.today()

    # 周末非交易日：跳过，避免把上周五收盘误写成「今日」
    if today.weekday() >= 5:
        sys.stderr.write("SKIP: %s 为周末，非交易日，不更新快照\n" % today.isoformat())
        sys.exit(0)

    # 收盘前保护：今日真实收盘数据在 15:00 后才产生；在此之前抓取到的
    # 实为盘前/昨收，写入会被误标为「今日收盘」，造成「日期对、数值错」。
    # 目标是今天(或未来)且当前早于 15:00 时，默认拒绝更新（除非显式 --force-preclose）。
    now = datetime.datetime.now()
    if (not args.force_preclose) and today == datetime.date.today() and now.hour < 15:
        sys.stderr.write(
            "REFUSE: 当前 %02d:%02d 早于收盘15:00，今日真实收盘数据尚未产生。\n"
            % (now.hour, now.minute))
        sys.stderr.write(
            "        此刻抓取到的实为盘前/昨收数据，写入会被误标为今日收盘。已拒绝更新。\n")
        sys.stderr.write(
            "        补跑历史交易日请用 --date YYYY-MM-DD；确要抓盘前快照请加 --force-preclose。\n")
        sys.exit(4)

    ind = fetch_today()
    if not ind:
        # 取数失败：保留现有文件，避免覆盖成空数据
        sys.stderr.write("WARN: 东财取数失败，未覆盖现有 sector_data.json\n")
        sys.exit(2)

    # 指数 + 风格指数（失败则缺省，前端会用内置兜底补齐，不影响行业数据）
    idx_style = _fetch_quotes(INDEX_SECIDS)
    indices = {k: idx_style[k] for k in INDEX_NAMES if k in idx_style}
    style = {k: idx_style[k] for k in STYLE_NAMES if k in idx_style}
    static = _static_sections(today)

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
    if indices:
        D["indices"] = indices
    if style:
        D["style"] = style
    if static:
        for _k in ("north", "margin", "judge", "etfs"):
            if static.get(_k):
                D[_k] = static[_k]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=1)
    print("OK sector_data.json today=%s industries=%d indices=%d style=%d (保留%d天)" % (
        today.isoformat(), len(ind), len(indices), len(style), len(days)))

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
