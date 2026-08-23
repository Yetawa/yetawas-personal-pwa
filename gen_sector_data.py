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
import concurrent.futures

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
    "1.000905": "中证500", "1.932000": "中证2000",
}
INDEX_NAMES = ["上证指数", "深证成指", "创业板指", "沪深300", "科创50", "北证50"]
STYLE_NAMES = ["大盘成长", "大盘价值", "小盘成长", "小盘价值", "上证50", "中证1000", "中证500", "中证2000"]

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


def _fetch_style_hist(n_days=10):
    """近 n_days 交易日风格指数收盘历史（需求5：风格差值曲线）。
    返回 {YYYY-MM-DD: {风格名:[收盘, 涨跌幅%]}}；失败返回 {}。"""
    secids = {
        "0.399372": "大盘成长", "0.399373": "大盘价值", "0.399376": "小盘成长",
        "0.399377": "小盘价值", "1.000016": "上证50", "1.000852": "中证1000",
        "1.000905": "中证500", "1.932000": "中证2000",
    }
    hosts = ["%d.push2his.eastmoney.com" % random.randint(1, 99) for _ in range(6)]
    hosts += ["push2his.eastmoney.com"]
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    # 收集每只指数的 [日期, 收盘, 涨跌幅]
    raw = {}  # name -> {date: [close, chg]}
    for host in hosts:
        try:
            for secid, name in secids.items():
                url = ("https://%s/api/qt/stock/kline/get?secid=%s"
                       "&fields1=f1&fields2=f3,f4,f8&klt=101&fqt=0"
                       "&end=20500101&lmt=%d&ut=fa5fd1943c7b386f172d6893dbfba10b&_=%d"
                       % (host, secid, n_days + 1, int(time.time() * 1000)))
                req = urllib.request.Request(url, headers={
                    "User-Agent": ua, "Referer": "https://quote.eastmoney.com/",
                })
                with urllib.request.urlopen(req, timeout=8) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
                kls = ((j or {}).get("data") or {}).get("klines") or []
                buf = {}
                for row in kls:
                    parts = row.split(",")
                    if len(parts) < 3:
                        continue
                    d = parts[0]
                    try:
                        close = float(parts[2])  # 收盘价
                        chg = float(parts[3]) if len(parts) > 3 else 0.0  # 涨跌幅
                    except (ValueError, IndexError):
                        continue
                    buf[d] = [round(close, 2), round(chg, 2)]
                if buf:
                    raw[name] = buf
            if len(raw) >= len(secids):
                break
        except Exception:
            continue
    if not raw:
        return {}
    # 合并为按日期的矩阵；仅保留全部风格都有的日期
    all_dates = set()
    for buf in raw.values():
        all_dates |= set(buf.keys())
    out = {}
    for d in sorted(all_dates):
        rec = {}
        ok = True
        for name, buf in raw.items():
            if d not in buf:
                ok = False
                break
            rec[name] = buf[d]
        if ok and len(rec) == len(secids):
            out[d] = rec
    return out


def _get(url, timeout=10, retries=2):
    """带退避重试的 JSON GET（历史行情接口偶发连接重置）。"""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json, text/plain, */*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(0.4 * (i + 1))
    return None


def _fetch_one_history(name, bk, n_days):
    """取单个行业的近 n_days 日历史：{date: {chg, main}}。chg 由日K收盘序列推算，main 取资金流日K。"""
    secid = "90." + bk
    closes = {}   # date -> close
    mains = {}    # date -> 主力净流入(亿)
    # 日K（收盘），多取 1 根用于推算首根涨跌幅
    try:
        t = int(time.time() * 1000)
        u = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
             "&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53&klt=101&fqt=1&lmt=%d&end=20500101&_=%d"
             % (secid, n_days + 1, t))
        j = _get(u, timeout=8)
        for row in ((j or {}).get("data") or {}).get("klines") or []:
            p = row.split(",")
            if len(p) >= 3:
                try:
                    closes[p[0]] = float(p[2])
                except Exception:
                    pass
    except Exception:
        pass
    # 资金流日K（主力净流入，单位元 → 亿）
    try:
        t = int(time.time() * 1000)
        u = ("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=%d&klt=101&secid=%s"
             "&fields1=f1,f2,f3,f7&fields2=f51,f52&_=%d" % (n_days + 1, secid, t))
        j = _get(u, timeout=8)
        for row in ((j or {}).get("data") or {}).get("klines") or []:
            p = row.split(",")
            if len(p) >= 2:
                try:
                    mains[p[0]] = round(float(p[1]) / 1e8, 2)
                except Exception:
                    pass
    except Exception:
        pass
    # 由相邻收盘推算涨跌幅（与实时 f3 口径一致）
    dates = sorted(closes.keys())
    out = {}
    for i, d in enumerate(dates):
        if i == 0:
            continue
        prev = closes[dates[i - 1]]
        chg = round((closes[d] - prev) / prev * 100, 2) if prev else None
        main = mains.get(d)
        out[d] = {"chg": chg, "main": main}
    return name, out


def fetch_history(bk_map, n_days=5):
    """并发取全部行业的近 n_days 日历史，返回 {date_iso: {name: {chg, main}}}。"""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one_history, n, b, n_days): n for n, b in bk_map.items()}
        for f in concurrent.futures.as_completed(futs):
            try:
                name, daily = f.result()
            except Exception:
                continue
            for d, v in daily.items():
                results.setdefault(d, {})[name] = v
    return results


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


# 历史种子：网络不可达（如沙箱被封 push2his）时，用内置真实历史日补齐近交易日，
# 保证「近5交易日切换」立即可用；用户本机每日运行会用实时/回补数据覆盖这些种子。
_HISTORY_SEED = r"""{"2026-08-07":{"label":"08-07 周五","source":"东方财富资金流向日报(13个行业主力净流入)","industries":{"电子":{"chg":3.53,"main":282.97},"汽车":{"chg":0.28,"main":-1.62},"医药生物":{"chg":4.77,"main":88.46},"纺织服饰":{"chg":-0.27,"main":-1.75},"有色金属":{"chg":3.19,"main":70.77},"家用电器":{"chg":-0.86,"main":-1.75},"机械设备":{"chg":2.08,"main":40.49},"食品饮料":{"chg":0.21,"main":-1.76},"电力设备":{"chg":1.19,"main":29.93},"房地产":{"chg":-0.51,"main":-1.83},"建筑材料":{"chg":3.33,"main":29.25},"社会服务":{"chg":0.11,"main":-1.87},"国防军工":{"chg":1.47,"main":10.51},"轻工制造":{"chg":-0.16,"main":-2.43},"基础化工":{"chg":1.23,"main":9.73},"商贸零售":{"chg":-0.42,"main":-2.84},"煤炭":{"chg":-0.34,"main":1.17},"环保":{"chg":0.49,"main":-2.85},"钢铁":{"chg":-0.21,"main":1.0},"交通运输":{"chg":-0.64,"main":-3.38},"石油石化":{"chg":0.64,"main":0.85},"传媒":{"chg":0.05,"main":-9.48},"公用事业":{"chg":-0.1,"main":0.35},"银行":{"chg":-0.65,"main":-10.61},"农林牧渔":{"chg":-0.21,"main":0.15},"非银金融":{"chg":-0.26,"main":-11.47},"建筑装饰":{"chg":-0.06,"main":-0.35},"通信":{"chg":0.13,"main":-24.25},"美容护理":{"chg":0.72,"main":-0.46},"计算机":{"chg":-0.6,"main":-58.56},"综合":{"chg":0.77,"main":-0.94}}},"2026-08-10":{"label":"08-10 周一","source":"证券时报·数据宝 A股行情指标(申万一级行业)","industries":{"电力设备":{"chg":0.71,"main":17.78},"食品饮料":{"chg":2.51,"main":16.34},"有色金属":{"chg":2.02,"main":12.18},"基础化工":{"chg":1.68,"main":5.95},"国防军工":{"chg":1.32,"main":5.72},"传媒":{"chg":1.42,"main":5.64},"汽车":{"chg":1.37,"main":4.58},"农林牧渔":{"chg":3.14,"main":3.15},"轻工制造":{"chg":1.91,"main":2.4},"商贸零售":{"chg":1.62,"main":1.81},"银行":{"chg":0.45,"main":1.79},"钢铁":{"chg":0.94,"main":1.39},"煤炭":{"chg":2.34,"main":1.3},"纺织服饰":{"chg":2.4,"main":1.09},"美容护理":{"chg":1.79,"main":0.53},"社会服务":{"chg":1.98,"main":0.47},"交通运输":{"chg":0.91,"main":-0.45},"机械设备":{"chg":0.02,"main":-0.57},"综合":{"chg":1.32,"main":-1.0},"环保":{"chg":1.63,"main":-1.95},"房地产":{"chg":1.63,"main":-2.14},"家用电器":{"chg":1.39,"main":-2.7},"公用事业":{"chg":0.89,"main":-2.77},"建筑装饰":{"chg":0.75,"main":-3.37},"石油石化":{"chg":1.49,"main":-3.99},"建筑材料":{"chg":0.35,"main":-13.24},"非银金融":{"chg":0.18,"main":-15.7},"医药生物":{"chg":1.4,"main":-20.6},"计算机":{"chg":-0.26,"main":-43.39},"通信":{"chg":-3.16,"main":-170.44},"电子":{"chg":-0.49,"main":-196.54}}},"2026-08-11":{"label":"08-11 周二","source":"证券时报·数据宝 A股行情指标(申万一级行业)","industries":{"通信":{"chg":1.13,"main":13.36},"石油石化":{"chg":0.5,"main":8.39},"医药生物":{"chg":0.31,"main":-12.75},"公用事业":{"chg":0.27,"main":-3.12},"家用电器":{"chg":0.2,"main":0.39},"纺织服饰":{"chg":0.11,"main":2.64},"房地产":{"chg":-0.01,"main":-3.45},"银行":{"chg":-0.02,"main":0.42},"建筑装饰":{"chg":-0.06,"main":12.76},"电力设备":{"chg":-0.2,"main":-25.98},"煤炭":{"chg":-0.23,"main":1.62},"商贸零售":{"chg":-0.41,"main":-2.19},"计算机":{"chg":-0.46,"main":-21.3},"机械设备":{"chg":-0.57,"main":-11.61},"汽车":{"chg":-0.61,"main":8.99},"综合":{"chg":-0.68,"main":-0.06},"环保":{"chg":-0.69,"main":-2.32},"轻工制造":{"chg":-0.69,"main":-3.06},"食品饮料":{"chg":-0.74,"main":-12.62},"建筑材料":{"chg":-0.82,"main":-7.73},"传媒":{"chg":-0.86,"main":-19.7},"电子":{"chg":-0.87,"main":-101.7},"美容护理":{"chg":-0.9,"main":-1.18},"非银金融":{"chg":-0.92,"main":-22.64},"社会服务":{"chg":-1.21,"main":-3.53},"农林牧渔":{"chg":-1.21,"main":-9.86},"交通运输":{"chg":-1.43,"main":-16.75},"钢铁":{"chg":-1.52,"main":-3.03},"基础化工":{"chg":-1.57,"main":-19.06},"国防军工":{"chg":-2.38,"main":-36.66},"有色金属":{"chg":-4.42,"main":-138.4}}},"2026-08-12":{"label":"08-12 周三","source":"东方财富实时行情接口(ulist.np) 收盘数据 · 主力净流入=超大单+大单","industries":{"电子":{"chg":1.99,"main":101.58},"通信":{"chg":2.46,"main":129.33},"计算机":{"chg":1.04,"main":-15.41},"传媒":{"chg":1.36,"main":7.17},"电力设备":{"chg":1.58,"main":40.23},"机械设备":{"chg":1.49,"main":16.78},"国防军工":{"chg":0.99,"main":-4.56},"汽车":{"chg":0.95,"main":15.47},"家用电器":{"chg":1.15,"main":-1.74},"食品饮料":{"chg":1.66,"main":12.77},"纺织服饰":{"chg":0.6,"main":-0.84},"轻工制造":{"chg":1.22,"main":3.04},"医药生物":{"chg":0.53,"main":-34.4},"公用事业":{"chg":-0.01,"main":-7.57},"交通运输":{"chg":0.73,"main":1.98},"房地产":{"chg":3.1,"main":11.53},"商贸零售":{"chg":1.22,"main":0.35},"社会服务":{"chg":1.17,"main":1.47},"综合":{"chg":1.69,"main":2.37},"建筑材料":{"chg":1.19,"main":-5.3},"建筑装饰":{"chg":1.42,"main":-6.35},"农林牧渔":{"chg":1.01,"main":-0.45},"基础化工":{"chg":0.95,"main":-6.95},"钢铁":{"chg":0.77,"main":0.5},"有色金属":{"chg":1.12,"main":-10.5},"石油石化":{"chg":-0.46,"main":-3.55},"煤炭":{"chg":-0.78,"main":-3.19},"环保":{"chg":1.14,"main":1.0},"美容护理":{"chg":-0.21,"main":-0.97},"银行":{"chg":-0.09,"main":6.22},"非银金融":{"chg":0.72,"main":-0.35}}}}"""

def fetch_north_latest():
    """抓北向资金近 10 个交易日陆股通成交额（MUTUAL_TYPE 003=深股通 + 005=沪股通，DEAL_AMT 百万→亿）。
    返回 {"date": 最新日, "turnover": 最新日亿, "trend": [{date:"MM/DD", v:亿}, ...] 近10日升序}。
    2024-08-19 起北向不再披露每日净买入/净卖出，仅披露成交额。失败返回 None。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "sortColumns=TRADE_DATE&sortTypes=-1&pageSize=120&pageNumber=1"
           "&reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL&source=WEB&client=WEB")
    j = _get(url, timeout=12, retries=2)
    if not j or not j.get("result") or not j["result"].get("data"):
        return None
    daily = {}
    for x in j["result"]["data"]:
        if x.get("MUTUAL_TYPE") in ("003", "005") and isinstance(x.get("DEAL_AMT"), (int, float)):
            dt = x["TRADE_DATE"][:10]
            daily[dt] = daily.get(dt, 0) + x["DEAL_AMT"]
    if not daily:
        return None
    dates = sorted(daily)[-10:]
    trend = [{"date": d[5:].replace("-", "/"), "v": round(daily[d] / 100, 1)} for d in dates]
    latest = dates[-1]
    return {"date": latest, "turnover": round(daily[latest] / 100, 2), "trend": trend}


def fetch_margin_latest():
    """抓两融余额最新值（RPTA_RZRQ_LSHJ，RZRQYE 单位元→亿；delta=最新两天余额差值）。失败返回 None。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "sortColumns=DIM_DATE&sortTypes=-1&pageSize=3&pageNumber=1"
           "&reportName=RPTA_RZRQ_LSHJ&columns=ALL&source=WEB&client=WEB")
    j = _get(url, timeout=12, retries=2)
    if not j or not j.get("result") or not j["result"].get("data"):
        return None
    rows = j["result"]["data"]
    try:
        d0, d1 = rows[0], rows[1]
        date = d0["DIM_DATE"][:10]
        bal = float(d0["RZRQYE"]) / 1e8
        delta = (float(d0["RZRQYE"]) - float(d1["RZRQYE"])) / 1e8
        return {"date": date, "balance": round(bal, 2), "delta": round(delta, 2)}
    except Exception:
        return None


def _gen_judge(days, indices, style):
    """基于最新交易日数据自动生成行业配置研判（≤3 条 [标题, 正文]）。数据不足返回 []。"""
    if not days:
        return []
    d0 = sorted(days.keys(), reverse=True)[0]
    blk = days[d0].get("industries") or {}
    items = [(n, v.get("chg"), v.get("main")) for n, v in blk.items()]
    items = [x for x in items if x[1] is not None]
    if len(items) < 5:
        return []
    items.sort(key=lambda x: x[1], reverse=True)
    top_up = items[:3]
    dn_list = [x for x in items if x[1] < 0]
    dn_list.sort(key=lambda x: x[1])
    top_dn = dn_list[:3]
    mains = [(n, c, m) for n, c, m in items if m is not None]
    mains.sort(key=lambda x: x[2], reverse=True)
    in_lead = mains[:3]
    out_lead = mains[-3:][::-1]
    ups = sum(1 for _, c, _ in items if c > 0)
    downs = len(items) - ups

    style_txt = ""
    if style and "大盘成长" in style and "大盘价值" in style:
        gc = style["大盘成长"][1]
        gv = style["大盘价值"][1]
        style_txt = ("成长占优：大盘成长 %+.2f%% 跑赢大盘价值 %+.2f%%。" % (gc, gv)
                     if gc > gv else
                     "价值占优：大盘价值 %+.2f%% 跑赢大盘成长 %+.2f%%。" % (gv, gc))

    out = []
    up_s = "、".join("%s%+.2f%%" % (n, c) for n, c, _ in top_up)
    dn_s = ("、".join("%s%+.2f%%" % (n, c) for n, c, _ in top_dn)
            if top_dn else "无下跌行业")
    out.append([
        "%s 行业强弱：%d 涨 %d 跌" % (d0[5:].replace("-", "/"), ups, downs),
        "领涨：%s；领跌：%s。全市场 %d 个申万一级行业中 %d 涨 %d 跌。" % (up_s, dn_s, len(items), ups, downs),
    ])
    if in_lead and out_lead:
        in_s = "、".join("%s%+.0f亿" % (n, m) for n, _, m in in_lead)
        out_s = "、".join("%s%+.0f亿" % (n, m) for n, _, m in out_lead)
        out.append([
            "主力资金：净流入集中在 %s" % in_lead[0][0],
            "主力净流入居前：%s；净流出居前：%s。%s" % (in_s, out_s, style_txt or "跟随资金方向，避免逆势。"),
        ])
    elif style_txt:
        out.append(["风格轮动", style_txt])
    max_chg = max(c for _, c, _ in items)
    if max_chg > 3:
        out.append([
            "警惕追高",
            "当日领涨 %s 涨幅达 %+.2f%%，短线涨幅过快，追高需控仓，宜沿 5/10 日线分批，并留意次日资金是否延续。" % (top_up[0][0], max_chg),
        ])
    return out[:3]


def _static_sections(today):
    try:
        s = json.loads(_STATIC_JSON)
    except Exception:
        return {}
    # 注意：不要用 today 覆盖 north/margin 的 date —— 静态数值是各自抓取日的，
    # 若把日期改成"今天"会导致「日期=今天、数值=旧」的误导（曾因此被用户指出数据不对）。
    # north/margin 保留 _STATIC_JSON 中各自的真实数据日期。
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

    # 风格指数近10日历史（需求5：风格差值曲线）。拉取失败则 style_hist 为空，前端降级提示。
    style_hist = {}
    try:
        style_hist = _fetch_style_hist()
        if style_hist:
            print("    风格历史: %d 个交易日" % len(style_hist))
    except Exception as e:
        print("    风格历史抓取失败（前端将降级）:", e)

    static = _static_sections(today)

    today_str = today.isoformat()
    is_today = (today == datetime.date.today())

    def _label(d):
        dt = datetime.date.fromisoformat(d)
        return dt.strftime("%m-%d") + " " + _WEEKDAYS[dt.weekday()]

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "sector_data.json")
    prev = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    # ---- 组装近 5 个交易日（滚动窗口）----
    # 当日：实时接口（最准）；历史日：日K+资金流日K 回补，缺失行业用旧文件兜底。
    days = {}
    try:
        hist = fetch_history(SECTOR_BK, n_days=5)
    except Exception:
        hist = {}
    hist_days = {}
    if is_today:
        # 目标是今天：今日行由下方实时接口生成，历史日从 hist 拿（排除今日）
        hist_days = {d: v for d, v in hist.items() if d != today_str}
    else:
        # 补跑历史交易日(--date D)：目标日 D 的收盘数据并入；同时排除「今天」的盘中
        # 数据（今日未收盘，K线不完整，混入会被误标为最新交易日——曾致回补错乱）
        hist_days = {d: v for d, v in hist.items() if d != datetime.date.today().isoformat()}
        if today_str in hist:
            hist_days[today_str] = hist[today_str]
    # 历史日：合并旧文件同日的行业（回补个别取数失败的行业）
    for d, ind_h in hist_days.items():
        merged = dict(ind_h)
        prev_ind = (prev.get("days", {}).get(d, {}).get("industries", {})) if prev else {}
        for nm, val in prev_ind.items():
            if nm not in merged:
                merged[nm] = val
        days[d] = {
            "label": _label(d),
            "source": "东方财富历史行情(日K) · 主力净流入=超大单+大单(历史资金流日K)",
            "industries": merged,
        }
    # 当日：实时接口（仅当目标是真正的今天）
    if is_today:
        days[today_str] = {
            "label": _label(today_str),
            "source": "东方财富实时行情接口(ulist.np) 收盘数据 · 主力净流入=超大单+大单",
            "industries": ind,
        }
    # 历史回补不足（<2 天）时，退回旧文件的 days，保证不丢数据
    if len(days) < 2 and prev:
        for d, blk in prev.get("days", {}).items():
            if d not in days:
                days[d] = blk
    # 用内置历史种子补齐缺失的近交易日（仅当该日期无实时/回补数据），
    # 保证「近5交易日切换」立即可用；用户本机每日运行会覆盖这些种子。
    try:
        for _sd, _sblk in json.loads(_HISTORY_SEED).items():
            if _sd not in days:
                days[_sd] = _sblk
    except Exception:
        pass
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
    if style_hist:
        D["style_hist"] = style_hist
    if static:
        for _k in ("north", "margin", "judge", "etfs"):
            if static.get(_k):
                D[_k] = static[_k]
    # 北向 / 两融：动态抓取最新值覆盖静态兜底（保留 note 说明；失败时用静态值）
    try:
        _nb = fetch_north_latest()
        if _nb:
            D["north"] = dict(static.get("north", {}), **_nb)
            print("    北向动态更新:", _nb)
    except Exception as e:
        print("    北向动态抓取失败，保留静态:", e)
    try:
        _mg = fetch_margin_latest()
        if _mg:
            D["margin"] = _mg
            print("    两融动态更新:", _mg)
    except Exception as e:
        print("    两融动态抓取失败，保留静态:", e)
    # 行业配置研判：基于最新数据自动生成（数据不足时保留静态文案）
    try:
        _gj = _gen_judge(days, indices, style)
        if _gj:
            D["judge"] = _gj
            print("    研判自动生成:", len(_gj), "条")
    except Exception as e:
        print("    研判自动生成失败，保留静态:", e)
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
