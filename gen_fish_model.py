#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_fish_model.py — 生成鱼盆页【全模型】快照 fish_model.json

背景：
  鱼盆趋势模型需要 ~300 日 K 线才能算 PE 百分位 / 盆沿偏离 / 量比 / 趋势 / 变盘预警。
  线上(onrender 美国节点)无法直连东财/腾讯行情，浏览器端拿不到 K 线，导致这些列长期停留在
  内置示例值、无法随公开 ETF 数据自动更新。

  本脚本在【能访问国内行情的环境】（本机/自动化/CloudStudio）收盘后：
    1) 用日 K 线拉取每只 ETF 近 ~320 交易日收盘+成交量（新浪优先，东财 push2his 次之，腾讯 ifzq 兜底）；
    2) 用腾讯 qt.gtimg.cn 取当日实时价/涨跌幅；
    3) 用与前端 fish_basin.html computeModel() 完全一致的算法算出全部模型字段；
    4) 输出 fish_model.json，鱼盆页打开时自动读取（同域 fetch，无代理问题），全字段刷新。

用法：
  python gen_fish_model.py            # 生成本地 fish_model.json
  python gen_fish_model.py --date 2026-08-20
"""
import os, re, json, sys, time, urllib.request, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}


def extract_default_etfs():
    """从 fish_basin.html 解析 DEFAULT_ETFS 数组（保持页面顺序）。"""
    path = os.path.join(HERE, "fish_basin.html")
    with open(path, encoding="utf-8") as f:
        h = f.read()
    m = re.search(r"DEFAULT_ETFS\s*=\s*(\[.*?\]);", h, re.S)
    if not m:
        raise SystemExit("fish_basin.html 中未找到 DEFAULT_ETFS")
    return json.loads(m.group(1))


# ----------------------------------------------------------------------- 行情
def fetch_quotes(codes):
    """腾讯批量行情：{code:{price,change}}（与 gen_fish_snapshot 同源，沙箱可达）。"""
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode("gbk", "replace")
    out = {}
    for line in text.split(";"):
        m = re.match(r'v_([a-z]{2}\d{6})="([^"]*)"', line.strip())
        if not m:
            continue
        code, body = m.group(1).lower(), m.group(2)
        parts = body.split("~")
        if len(parts) < 5:
            continue
        try:
            price = float(parts[3]); prev = float(parts[4])
        except ValueError:
            continue
        if prev <= 0:
            continue
        out[code] = {"price": round(price, 4), "change": round((price - prev) / prev * 100, 2)}
    return out


def _http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_kline_sina(code, days=340):
    """新浪日 K：返回 [(close, vol), ...] 升序（旧->新）。"""
    sym = code  # sh512290 / sz159509
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=5&datalen=%d" % (sym, days))
    arr = _http_json(url)
    bars = []
    for d in arr:
        try:
            bars.append((float(d["close"]), float(d["volume"])))
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def fetch_kline_em(code, days=340):
    """东财日 K 兜底：返回 [(close, vol), ...] 升序。"""
    secid = ("1." if code.startswith("sh") else "0.") + code[2:]
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
           "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1"
           "&end=20500101&lmt=%d" % (secid, days))
    j = _http_json(url)
    kl = (j or {}).get("data", {}) or {}
    kl = kl.get("klines") if isinstance(kl, dict) else None
    if not kl:
        return []
    bars = []
    for s in kl:
        p = s.split(",")
        if len(p) < 6:
            continue
        try:
            bars.append((float(p[2]), float(p[5])))
        except ValueError:
            continue
    return bars


def fetch_kline_tencent(code, days=340):
    """腾讯 ifzq 日 K 兜底：返回 [(close, vol), ...] 升序（web.ifzq.gtimg.cn 沙箱可达）。"""
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,%d,qfq"
           % (code, days))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    d = (j or {}).get("data", {}) or {}
    node = d.get(code) or {}
    kl = node.get("qfqday") or node.get("day") or []
    bars = []
    for s in kl:
        if not isinstance(s, (list, tuple)) or len(s) < 6:
            continue
        try:
            bars.append((float(s[2]), float(s[5])))
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def fetch_kline(code, days=340):
    """多源兜底：新浪优先，东财次之，腾讯 ifzq 兜底（腾讯间歇超时，失败重试一次）。"""
    for fn in (fetch_kline_sina, fetch_kline_em):
        try:
            bars = fn(code, days)
            if len(bars) >= 60:
                return bars
        except Exception as e:
            sys.stderr.write("  kline %s via %s 失败: %s\n" % (code, fn.__name__, e))
    for attempt in (1, 2):
        try:
            bars = fetch_kline_tencent(code, days)
            if len(bars) >= 60:
                return bars
        except Exception as e:
            sys.stderr.write("  kline %s via tencent(attempt %d) 失败: %s\n" % (code, attempt, e))
    return []


# ------------------------------------------------------------------- 模型算法
def compute_model(price, bars):
    """与前端 fish_basin.html computeModel() 完全一致。bars=[(close,vol),...] 升序。"""
    if not bars or len(bars) < 60:
        return None
    closes = [b[0] for b in bars]
    vols = [b[1] for b in bars]
    n = len(closes)
    last_close = closes[-1]
    price = price if (price is not None and price > 0) else last_close

    def ma(arr, w):
        s = arr[-w:]
        return sum(s) / len(s)

    ma5 = ma(closes, 5); ma20 = ma(closes, 20); ma60 = ma(closes, 60)
    baseline = ma20 * 0.6 + ma60 * 0.4
    dev = (price - baseline) / baseline * 100 if baseline else 0
    today_vol = vols[-1]
    prev5 = vols[-6:-1]
    avg_prev5 = sum(prev5) / len(prev5) if prev5 else 0
    vol_ratio = today_vol / avg_prev5 if avg_prev5 else 1
    win = closes[-600:]
    below = sum(1 for x in win if x <= price)
    pe = round(below / len(win) * 100) if win else 50

    if dev > 2:
        status = '跳出盆外'
    elif dev > 0.5:
        status = '盆沿上方'
    elif dev >= -0.5:
        status = '盆沿试探'
    elif dev >= -2:
        status = '盆内游动'
    else:
        status = '盆底深水区'

    slope = (ma20 - ma60) / ma60 if ma60 else 0
    align = 1 if (ma5 > ma20 and ma20 > ma60) else (-1 if (ma5 < ma20 and ma20 < ma60) else 0)
    f1 = align * 0.6 + max(-1, min(1, slope * 20)) * 0.4
    recent20 = closes[-21:-1]
    hh = max(recent20); ll = min(recent20)
    if price > hh:
        f2 = min(1, (price - hh) / (hh or 1) * 50 + 0.5)
    elif price < ll:
        f2 = -min(1, (ll - price) / (ll or 1) * 50 + 0.5)
    else:
        f2 = (price - ll) / ((hh - ll) or 1) * 0.6 - 0.3
    if vol_ratio > 1.2 and price >= ma20:
        f3 = 0.6
    elif vol_ratio > 1:
        f3 = 0.3
    elif vol_ratio < 0.8:
        f3 = -0.3
    else:
        f3 = 0
    import math
    var20 = sum((c - ma20) ** 2 for c in closes[-20:]) / 20
    std = math.sqrt(var20)
    band = std / ma20 if ma20 else 0
    f4 = max(-1, min(1, (0.05 - band) / 0.04))
    score = 0.4 * f1 + 0.3 * f2 + 0.2 * f3 + 0.1 * f4

    trend = '震荡中'
    if score > 0.6 and price > ma20:
        trend = '确立多头'
    elif score < -0.6 and price < ma20:
        trend = '确立空头'

    if score > 0.3:
        if price > hh:
            signal, detail = '趋势趋多', '突破确认'
        else:
            signal, detail = '偏多', '蓄势待跳'
    elif score < -0.3:
        if price < ll:
            signal, detail = '趋势趋空', '破位确认'
        else:
            signal, detail = '偏空', '临界转弱'
    else:
        signal, detail = '震荡', ''

    return {
        "ma5": round(ma5, 3), "ma20": round(ma20, 3), "dev": round(dev, 2), "volRatio": round(vol_ratio, 2),
        "pe": pe, "status": status, "trend": trend, "signal": signal, "signalDetail": detail,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="交易日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--no-quote", action="store_true", help="不取实时价，使用 K 线末值")
    args = ap.parse_args()
    today = args.date or datetime.date.today().isoformat()

    etfs = extract_default_etfs()
    codes = [e["code"] for e in etfs]
    quotes = {} if args.no_quote else fetch_quotes(codes)

    items = {}
    ok = 0
    for e in etfs:
        code = e["code"]
        bars = fetch_kline(code)
        if len(bars) < 60:
            sys.stderr.write("  %s K线不足，跳过\n" % code)
            items[code] = None
            continue
        q = quotes.get(code)
        price = q["price"] if q else None
        m = compute_model(price, bars)
        if not m:
            items[code] = None
            continue
        m["price"] = round(bars[-1][0], 4)
        m["change"] = q["change"] if q else round((bars[-1][0] - bars[-2][0]) / bars[-2][0] * 100, 2) if len(bars) >= 2 else 0
        items[code] = m
        ok += 1
        time.sleep(0.08)  # 新浪限流保护

    snap = {
        "date": today,
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "multi_kline(sina/em/tencent) + tencent_quote",
        "items": items,
    }
    out = os.path.join(HERE, "fish_model.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("OK fish_model.json date=%s 模型 %d/%d 只" % (today, ok, len(etfs)))


if __name__ == "__main__":
    main()
