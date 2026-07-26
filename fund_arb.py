# -*- coding: utf-8 -*-
"""
LOF / ETF 基金套利数据看板（网页交互版）

运行：python fund_arb.py
  -> 自动在本机启动本地服务（默认 http://localhost:8000）
  -> 浏览器打开后，填入基金代码，自动拉取并展示数据

网页功能：
  - 填写基金代码（如 162411）→ 实时刷新
  - 可选填「标的 ETF 代码」（如 XOP / QQQ / SPY）用于估算净值；留空则按内置基金表自动匹配
  - 默认近 10 个交易日，日期倒序（最新在顶端）
  - 表格含：汇率、价格、净值、标的收盘、溢价、估算净值、估值溢价、申购状态、限购金额、套利信号

数据源优先级（自动兜底，本机通常全部可用）：
  - 单位净值：东方财富 api.fund.eastmoney.com
  - 场内收盘价：东方财富 push2his -> 腾讯财经
  - 标的收盘：东方财富全球行情 -> 腾讯财经 -> stockanalysis.com
  - USD/CNY 汇率：frankfurter.app -> 新浪实时汇率
  - 申购状态/限购：东方财富 fundf10 jjfl 页面

仅使用 Python 标准库，无需 pip 安装。

核心公式：
  估算净值(t) = 锚定净值 × (标的_t / 标的_锚) × (汇率_t / 汇率_锚)
  估值溢价(t) = (价格_t − 估算净值(t)) / 估算净值(t)
  其中锚定日取「最近一个已公布真实净值的交易日」；
  标的_锚 取严格早于锚定日的美股收盘（时差处理），汇率_锚取锚定日汇率。
"""
import json
import csv
import re
import urllib.request
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date as _date_cls
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import os
import threading
import statistics

# 界面版本（用于页面展示与 PWA 缓存区分）
VERSION = "V1.2"

# ---------------------------------------------------------------------------
# 安全：输入校验（杜绝注入 / 非法参数进入下游请求与响应反射）
# ---------------------------------------------------------------------------
_RE_CODE = re.compile(r"^\d{6}$")                       # 6 位基金代码
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")         # 日期 YYYY-MM-DD
_RE_UND  = re.compile(r"^[A-Za-z0-9.]{1,16}$")       # 标的 ETF 代码（仅字母数字点）
_RE_SEP  = re.compile(r"[\s,，;；]+")                 # 代码清单分隔符：空格/逗号/分号（全半角）

def _valid_code(v):
    return bool(_RE_CODE.match(v or ""))
def _valid_date(v):
    if not _RE_DATE.match(v or ""):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False
def _valid_und(v):
    return bool(_RE_UND.match(v or ""))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

THRESHOLD = 1.5            # 套利信号阈值 ±%
ANCHOR_DATE = None         # 手动固定锚定日（如 "2026-07-17"），None=自动取最近披露净值

# 常见 LOF / ETF 登记表：代码 -> 名称 + 标的（用于估算净值）
# 标的字段：em=东财全球 secid, tx=腾讯美股前缀, sa=stockanalysis 代码
FUND_REGISTRY = {
    "162411": {"name": "华宝油气",            "underlying": {"em": "107.XOP",  "tx": "usXOP",  "sa": "XOP"}},
    "161130": {"name": "易方达标普500LOF",     "underlying": {"em": "107.QQQ",  "tx": "usQQQ",  "sa": "QQQ"}},
    "161125": {"name": "易方达标普500(LOF)",   "underlying": {"em": "107.SPY",  "tx": "usSPY",  "sa": "SPY"}},
    "513500": {"name": "博时标普500ETF",       "underlying": {"em": "107.SPY",  "tx": "usSPY",  "sa": "SPY"}},
    "513100": {"name": "国泰纳斯达克100ETF",   "underlying": {"em": "107.QQQ",  "tx": "usQQQ",  "sa": "QQQ"}},
    "164824": {"name": "工银印度基金(LOF)",    "underlying": {"em": "107.INDA", "tx": "usINDA", "sa": "INDA"}},
    "162719": {"name": "广发道琼斯石油(LOF)",  "underlying": {"em": "107.IEO",  "tx": "usIEO",  "sa": "IEO"}},
}

# 界面二默认观察清单（来自截图 2026-07-24 的 LOF 基金列表，可增删）
RANKING_WATCHLIST = [
    "160140", "164705", "164824", "501312", "164906", "160717",
    "501300", "160719", "167301", "161126", "160632", "161116", "161831",
    "160924", "161124", "164701", "160639", "163208", "160216", "164812",
    "160143", "161032", "160225", "160416", "160922", "161130",
    "161127", "161226", "161725", "160415", "160644", "501025", "162719",
    "501012", "161040", "161812", "161125", "161128", "501018", "160723",
    "161129", "501225",
]
RANKING_MAX_WORKERS = 8  # 提高并行度：44 只基金冷计算/预热更快（东财等上游对并发容忍度高）

# 排行默认清单：剔除 5 只联网查询始终无价格数据的异常基金
# （164801 / 161113 / 167725 / 162804 / 160244，查询时恒报 "无价格数据"）

# 基金精简名（≤8 个汉字），用于排行表名称列，避免列过宽需横向滚动
SHORT_NAME = {
    # 注册表基金
    "162411": "华宝油气", "161130": "易方达纳指", "161125": "易方达标普500",
    "513500": "博时标普500", "513100": "国泰纳指100", "164824": "工银印度", "162719": "广发石油",
    # 排行默认清单
    "160140": "南方道琼斯", "164705": "汇添富恒生", "501312": "华宝海外科技", "164906": "交银中概互联",
    "160717": "嘉实H股", "501300": "海富通全球债", "160719": "嘉实黄金", "167301": "方正富邦保险",
    "161126": "易方达医疗", "160632": "鹏华酒", "161116": "易方达黄金", "161831": "银华恒生国企",
    "160924": "大成恒生", "161124": "易方达港小盘", "164701": "汇添富黄金", "160639": "鹏华高铁",
    "163208": "诺安油气", "160216": "国泰大宗商品", "164812": "国投白银", "160143": "南方创业板",
    "161032": "富国煤炭", "160225": "国泰新能源", "160416": "华安全球石油", "161127": "易方达生科",
    "161226": "国投白银", "161725": "招商白酒", "160644": "鹏华港美互联", "501025": "鹏华香港银行",
    "501012": "汇添富中药", "161040": "富国创业板", "161812": "银华深证100", "161128": "易方达信息科技",
    "501018": "南方原油", "160723": "嘉实原油", "161129": "易方达原油", "501225": "景顺半导体",
}

# 排行清单中 QDII / 海外基金的标的映射
# 与界面一算法一致：估算净值 = 锚定净值 × (标的_t / 标的_锚) × (汇率_t / 汇率_锚)
def _u(sa):
    return {"em": "107." + sa, "tx": "us" + sa, "sa": sa}

UNDERLYING_MAP = {
    "160140": _u("SPY"), "164705": _u("EWH"), "501312": _u("QQQ"), "164906": _u("KWEB"),
    "160717": _u("FXI"), "501300": _u("AGG"), "160719": _u("GLD"), "161126": _u("XLV"),
    "161116": _u("GLD"), "161831": _u("FXI"), "160924": _u("EWH"), "161124": _u("EWH"),
    "164701": _u("GLD"), "163208": _u("XOP"), "160216": _u("DBC"), "160416": _u("XOP"),
    "161130": _u("QQQ"), "161127": _u("XBI"),
    # 161226 国投瑞银白银期货：投资上海期货交易所白银期货，用国内白银连续合约 AG0，无需 USD/CNY 换汇。
    "161226": {"sina_futures": "AG0", "sa": "AG0", "use_fx": False},
    "160644": _u("KWEB"),
    "501025": _u("FXI"), "162719": _u("IEO"), "161125": _u("SPY"), "161128": _u("XLK"),
    "501018": _u("USO"), "160723": _u("USO"), "161129": _u("USO"), "501225": _u("SOXX"),
    "164824": _u("INDA"),
}

# 仓位系数 w：标的/汇率涨跌对基金净值的实际传导比例
# 1.0 = 满仓跟踪；0.95 ≈ 95%资产跟踪标的、5%现金拖累（参考华宝油气LOF验证思路）
# 图片验证使用 w=0.95；股票型 QDII 通常 0.97~0.99，债券/商品略低。
DEFAULT_WEIGHT = 0.95
UNDERLYING_WEIGHT = {
    "XOP": 0.95, "IEO": 0.95, "USO": 0.95, "DBC": 0.95,   # 油气/大宗商品
    "GLD": 0.96, "SLV": 0.96, "AG0": 0.55,                  # 贵金属 / 国内白银期货
    "SPY": 0.98, "QQQ": 0.98, "INDA": 0.97, "KWEB": 0.97,
    "XLV": 0.98, "XBI": 0.98, "XLK": 0.98, "SOXX": 0.98,  # 行业/宽基股票
    "EWH": 0.98, "FXI": 0.98,                               # 港股
    "AGG": 0.90,                                             # 债券
}

# 复合标的：部分基金同时持有【港股 + 美股】同主题资产（如 160644 港美互联），
# 单一代理（KWEB 仅美股）无法覆盖港股那一腿，导致背离交易日误差爆表（±7%）。
# 这里把多个成分代理按权重合成为一条「合成标的序列」，仅用收益率合成（绝对价位无关），
# 与下游 w/lag 公式完全兼容。权重之和应为 1.0；成分 und 格式同 UNDERLYING_MAP。
COMPOSITE_UNDERLYING = {
    # 160644 鹏华港美互联：基准=中证海外中国互联网指数（即 KWEB 跟踪的指数）。
    # 美股腿用 KWEB（中概 ADR）；港股腿用【仅港股通-only 纯互联网篮子】——
    # 只放没有美股 ADR 的标的（腾讯/美团/小米/快手），避免与 KWEB 里已有的
    # 阿里/京东/百度/网易 ADR 重复计算。篮子按近似市值加权。
    # 注：160644 实际为偏主动管理，净值与基准相关性仅~0.27，代理精度有物理下限，
    #     港股腿权重经回测选 0.3（kwb_w=0.7 时 MAE 最优）。
    "160644": [
        {"em": "107.KWEB", "tx": "usKWEB", "sa": "KWEB", "w": 0.7},
        {"sa": "HKNET", "w": 0.3, "basket": [
            ("hk00700", 0.68),   # 腾讯
            ("hk01810", 0.15),   # 小米
            ("hk03690", 0.14),   # 美团
            ("hk01024", 0.03),   # 快手
        ]},
    ],
}

# ---------------------------------------------------------------------------
# w 逐标的回测校准：用各标的历史数据网格搜索最优仓位系数 w（最小化估算净值误差 MAE）
# 校准结果持久化到 weights_cache.json，服务启动时后台刷新；校准完成前回退到上方默认 w。
# ---------------------------------------------------------------------------
WEIGHT_CACHE = {}          # code(或 sa) -> 校准后的 w（4 位小数），按基金代码优先
WEIGHT_CACHE_TS = {}       # code(或 sa) -> 校准时间戳（秒）
LAG_CACHE = {}             # code(或 sa) -> 校准后的对齐滞后窗口 lag（整数，默认 1）
LAG_CACHE_TS = {}          # code(或 sa) -> lag 校准时间戳（秒）
DEFAULT_LAG = 1            # 默认对齐窗口：T 之前最近 1 个美股交易日
WEIGHT_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights_cache.json")
WEIGHT_STALE_DAYS = 14
# 校准参数：窗口放大到 220 天以保证回测样本充足；样本不足则不接受校准、回退默认。
# 注意：校准按【基金代码】独立进行，避免同一标的下不同基金（如 162411 与 164701 同属 XOP）
#       因波动率差异互相拖累，导致某只基金 w 被低估。
CALIB_DAYS = 120
MIN_CALIB_SAMPLES = 40

def load_weight_cache():
    global WEIGHT_CACHE, WEIGHT_CACHE_TS, LAG_CACHE, LAG_CACHE_TS
    try:
        if os.path.exists(WEIGHT_CACHE_FILE):
            blob = json.load(open(WEIGHT_CACHE_FILE, encoding="utf-8"))
            WEIGHT_CACHE = blob.get("weights", {}) or {}
            WEIGHT_CACHE_TS = blob.get("ts", {}) or {}
            LAG_CACHE = blob.get("lags", {}) or {}
            LAG_CACHE_TS = blob.get("lags_ts", {}) or {}
    except Exception:
        WEIGHT_CACHE, WEIGHT_CACHE_TS, LAG_CACHE, LAG_CACHE_TS = {}, {}, {}, {}

def save_weight_cache():
    try:
        json.dump({"weights": WEIGHT_CACHE, "ts": WEIGHT_CACHE_TS,
                   "lags": LAG_CACHE, "lags_ts": LAG_CACHE_TS},
                  open(WEIGHT_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def _weight_is_fresh(sa):
    ts = WEIGHT_CACHE_TS.get(sa)
    if ts is None:
        return False
    return (time.time() - ts) < WEIGHT_STALE_DAYS * 86400

def codes_for_sa(sa):
    codes = set()
    for c, reg in FUND_REGISTRY.items():
        u = reg.get("underlying")
        if u and u.get("sa") == sa:
            codes.add(c)
    for c, u in UNDERLYING_MAP.items():
        if u.get("sa") == sa:
            codes.add(c)
    return codes

def collect_backtest_points(codes, und, days, fx_map=None, lag=1):
    """收集 (NAV(T-1), NAV(T), P_T) 样本，用于 w 网格搜索。
    P_T 以 T 之前最近的美股交易日 xt 为分子日，分母日为 xt 往前第 lag 个交易日，
    即对标的价格取 T 之前第 lag 个交易日的累计变化（吸收 QDII 估值滞后）。
    标的与汇率严格共用同一对日期 (xt, xt1)，避免跨时区锚点错位。
    对国内期货标的（use_fx=False）跳过汇率因子。"""
    code0 = next(iter(codes)) if codes else None
    use_fx = (und or {}).get("use_fx", True)
    if fx_map is None:
        fx_map = fetch_fx()
    try:
        xop_map, _ = resolve_xop(code0, und, days)
        merge_seed_xop(xop_map)
    except Exception:
        return []
    if not xop_map:
        return []
    xop_dates = sorted(xop_map.keys())
    fx_dates = sorted(fx_map.keys()) if use_fx else []
    pts = []
    for code in codes:
        nav_rows = None
        for _ in range(5):
            try:
                nav_rows = fetch_nav(code, days)
                if nav_rows:
                    break
            except Exception:
                pass
            time.sleep(1)
        if not nav_rows:
            continue
        nav_map = dict(nav_rows)
        nav_dates = sorted(nav_map.keys())
        if len(nav_dates) < 3:
            continue
        for i, T in enumerate(nav_dates[1:], start=1):
            T_prev = nav_dates[i - 1]
            nav_t1 = nav_map[T_prev]
            nav_t = nav_map[T]
            xop_t_date = prev_trade_day(xop_map, T)
            if not xop_t_date:
                continue
            idx = xop_dates.index(xop_t_date)
            if idx - lag < 0:
                continue
            xop_t1_date = xop_dates[idx - lag]
            xop_t = xop_map.get(xop_t_date)
            xop_t1 = xop_map.get(xop_t1_date)
            if not (nav_t1 and xop_t1 and xop_t):
                continue
            if use_fx:
                fx_t = fx_map.get(xop_t_date)
                fx_t1 = fx_map.get(xop_t1_date)
                if not (fx_t1 and fx_t):
                    continue
                P = (xop_t / xop_t1) * (fx_t / fx_t1)
            else:
                P = xop_t / xop_t1
            pts.append((nav_t1, nav_t, P))
    return pts

def _sa_for_code(code):
    """返回该基金代码对应的标的 sa（来自 UNDERLYING_MAP 或 FUND_REGISTRY）。"""
    u = UNDERLYING_MAP.get(code)
    if u:
        return u["sa"]
    reg = FUND_REGISTRY.get(code)
    u = reg.get("underlying") if reg else None
    return u["sa"] if u else None

def calibrate_fund(code, und, days=CALIB_DAYS):
    """对【单只基金】做回测校准，独立搜索最优 w 与对齐滞后 lag。
    按基金独立校准可避免同一标的下不同基金（如 162411 与 164701 同属 XOP）互相拖累。
    国内期货标的（use_fx=False）因现金/保证金比例与展期损耗，有效 w 通常更低，下界放宽。"""
    fx_map = fetch_fx()
    use_fx = (und or {}).get("use_fx", True)
    # 股票型 QDII 用 [0.75, 1.00]；国内期货标的用 [0.45, 1.00]（白银期货有效 w 约 0.55）。
    # 同时遍历对齐滞后 lag∈{1,2,3}：股票型 QDII 用 lag=1，白银期货 LOF 用 lag=2 更准。
    LO, HI = (0.45, 1.00) if not use_fx else (0.75, 1.00)
    best = None  # (mae, w, lag, n)
    for lag in (1, 2, 3):
        pts = collect_backtest_points([code], und, days, fx_map=fx_map, lag=lag)
        if len(pts) < MIN_CALIB_SAMPLES:
            continue
        best_w, best_mae = LO, float("inf")
        w = LO
        while w <= HI + 1e-9:
            mae = sum(abs((nt1 * (1 + w * (P - 1)) - nt) / nt * 100) for (nt1, nt, P) in pts) / len(pts)
            if mae < best_mae:
                best_mae, best_w = mae, w
            w = round(w + 0.0005, 4)
        if best is None or best_mae < best[0]:
            best = (best_mae, best_w, lag, len(pts))
    if best is None:
        return None
    mae, w, lag, n = best
    sa = (und or {}).get("sa")
    return {"code": code, "sa": sa, "w": round(w, 4), "lag": lag, "mae": round(mae, 4), "n": n}

def calibrate_all_weights(days=CALIB_DAYS):
    codes = set(UNDERLYING_MAP.keys())
    for c, reg in FUND_REGISTRY.items():
        if reg.get("underlying"):
            codes.add(c)
    for code in sorted(codes):
        if code in WEIGHT_CACHE and _weight_is_fresh(code):
            continue
        # 获取基金实际标的字典（含 sina_futures/use_fx 等扩展字段）
        name = fetch_fund_name(code) or ""
        reg = FUND_REGISTRY.get(code)
        und = underlying_for(code, name, reg)
        if not und:
            continue
        try:
            r = calibrate_fund(code, und, days)
            if r:
                with UND_LOCK:
                    WEIGHT_CACHE[code] = r["w"]
                    WEIGHT_CACHE_TS[code] = time.time()
                    LAG_CACHE[code] = r["lag"]
                    LAG_CACHE_TS[code] = time.time()
                save_weight_cache()
                print(f"[校准] {code}/{sa} -> w={r['w']} lag={r['lag']} MAE={r['mae']}% n={r['n']}")
        except Exception as e:
            print(f"[校准] {code} 失败: {e}")

# 启动时加载已持久化的校准值（后台刷新在 main() 中启动）
load_weight_cache()

# 优先使用【基金代码】校准值，其次同标的(sa)校准值，最后回退默认 w/lag。
def weight_for(underlying, code=None):
    sa = (underlying or {}).get("sa")
    if code and code in WEIGHT_CACHE and _weight_is_fresh(code):
        return WEIGHT_CACHE[code]
    if sa and sa in WEIGHT_CACHE and _weight_is_fresh(sa):
        return WEIGHT_CACHE[sa]
    return UNDERLYING_WEIGHT.get(sa, DEFAULT_WEIGHT)

def _lag_is_fresh(key):
    ts = LAG_CACHE_TS.get(key)
    if ts is None:
        return False
    return (time.time() - ts) < WEIGHT_STALE_DAYS * 86400

def lag_for(underlying, code=None):
    """返回校准后的对齐滞后窗口 lag（默认 1）。
    lag 表示估算时标的价格取 T 之前最近的第 lag 个美股交易日，
    用于吸收 QDII 不同品种的估值滞后（如白银期货 LOF 为 2）。"""
    sa = (underlying or {}).get("sa")
    if code and code in LAG_CACHE and _lag_is_fresh(code):
        return LAG_CACHE[code]
    if sa and sa in LAG_CACHE and _lag_is_fresh(sa):
        return LAG_CACHE[sa]
    return DEFAULT_LAG

# 关键字推断标的（兜底：用户手动添加、不在上面的清单中的基金）
INFER_TABLE = [
    ("原油", "USO"), ("油气", "XOP"), ("石油", "XOP"), ("道琼斯石油", "IEO"),
    ("黄金", "GLD"), ("贵金属", "GLD"), ("白银", "SLV"),
    ("纳斯达克", "QQQ"), ("纳指", "QQQ"), ("标普医疗", "XLV"), ("标普生物", "XBI"),
    ("标普信息", "XLK"), ("标普", "SPY"), ("印度", "INDA"),
    ("中国互联网", "KWEB"), ("中概", "KWEB"), ("海外互联", "KWEB"), ("港美互联", "KWEB"),
    ("恒生国企", "FXI"), ("H股", "FXI"), ("香港银行", "FXI"),
    ("恒生", "EWH"), ("香港", "EWH"), ("港股", "EWH"),
    ("大宗商品", "DBC"), ("全球石油", "XOP"), ("全球债", "AGG"), ("全球收益债", "AGG"),
    ("美国", "SPY"), ("半导体", "SOXX"),
]

import threading as _threading
UND_LOCK = _threading.Lock()

def infer_underlying(name):
    n = name or ""
    for kw, sa in INFER_TABLE:
        if kw in n:
            return _u(sa)
    return None

def underlying_for(code, name, reg):
    if reg and reg.get("underlying"):
        return reg["underlying"]
    if code in UNDERLYING_MAP:
        return UNDERLYING_MAP[code]
    return infer_underlying(name)

def short_name(code, fullname):
    s = SHORT_NAME.get(code)
    if s:
        return s
    if fullname:
        import re as _re
        t = _re.sub(r"[\(（].*?[\)）]", "", fullname).strip()
        if len(t) > 8:
            t = t[:8]
        return t or code
    return code

def get_underlying_cached(und, n=15):
    key = und.get("sa")
    with UND_LOCK:
        if key in UND_CACHE:
            return UND_CACHE[key]
    try:
        rows, src = fetch_xop(und, n)
        res = (dict(rows), src)
    except Exception as e:
        print(f"    [标的缓存] {key} 获取失败：{e}")
        res = ({}, "无数据")
    with UND_LOCK:
        UND_CACHE[key] = res
    return res

UND_CACHE = {}

# 仅在全部在线接口失败时启用的兜底（已用真实历史校准，本机通常被实时数据覆盖）
SEED_XOP = {
    "2026-07-15": 164.86, "2026-07-16": 166.44, "2026-07-17": 170.18,
    "2026-07-20": 170.04, "2026-07-21": 173.83, "2026-07-22": 176.59,
    "2026-07-23": 175.66, "2026-07-24": 174.05,
}
SEED_FX = {
    "2026-07-15": 6.7743, "2026-07-16": 6.7669, "2026-07-17": 6.7775,
    "2026-07-20": 6.7669, "2026-07-21": 6.7661, "2026-07-22": 6.7730,
    "2026-07-23": 6.7703, "2026-07-24": 6.7729,
}


# ---------------------------------------------------------------------------
# 复合标的：把多个成分代理按权重合成一条「合成标的序列」（仅收益率合成）
# ---------------------------------------------------------------------------
# 港股互联网篮子成分缓存（key=symbol），1 小时内复用，避免每次请求都拉 7 只个股。
BASKET_COMP_CACHE = {}
BASKET_COMP_TTL = 3600

def _fetch_basket_component(symbol, n):
    with UND_LOCK:
        cached = BASKET_COMP_CACHE.get(symbol)
        if cached and (time.time() - cached[1]) < BASKET_COMP_TTL:
            return cached[0]
    try:
        m = dict(fetch_kline_tencent(symbol, n))
    except Exception as e:
        print(f"    [篮子成分] {symbol} 获取失败：{e}")
        m = {}
    with UND_LOCK:
        BASKET_COMP_CACHE[symbol] = (m, time.time())
    return m

def build_basket_xop(symbols_weights, n):
    """把多个个股按权重合成为一条「合成标的序列」（仅收益率合成，绝对价位无关）。
    symbols_weights: [(symbol, weight), ...]，权重无需预先归一。返回 (date->价, 标签) 或 None。"""
    comps, labels = [], []
    for sym, w in symbols_weights:
        m = _fetch_basket_component(sym, n)
        if m:
            comps.append((float(w), m))
            labels.append(sym)
    if not comps:
        return None
    total_w = sum(w for w, _ in comps)
    if total_w <= 0:
        return None
    all_dates = sorted(set().union(*[set(m.keys()) for _, m in comps]))
    if not all_dates:
        return None
    blend, last = {}, None
    for d in all_dates:
        rets = []
        for w, m in comps:
            mk = sorted(m.keys())
            pd = None
            for x in mk:            # 取 d 之前最近的可交易日期（严格 < d）
                if x < d:
                    pd = x
                else:
                    break
            if pd is None:
                continue
            cur, p = m.get(d), m.get(pd)
            if cur and p:
                rets.append(w * (cur / p - 1))
        if not rets:
            blend[d] = blend[last] if last else 1.0
            last = d
            continue
        r = sum(rets) / total_w
        blend[d] = 1.0 if not blend else blend[last] * (1 + r)
        last = d
    return blend, "篮子(" + "+".join(labels) + ")"


def _build_composite_xop(code, n):
    """对港美双市场基金，将多个成分代理按权重合成一条序列。
    返回 (date->合成价, 来源标签) 或 None。绝对价位无关，下游 w/lag 公式兼容。"""
    comps = COMPOSITE_UNDERLYING.get(code)
    if not comps:
        return None
    comp_series = []
    for c in comps:
        try:
            if "basket" in c:
                # 港股互联网篮子：用收益率合成，禁止套用 SEED_XOP（那是 KWEB 量级价格，会污染）
                m_src = build_basket_xop(c["basket"], n)
                m = m_src[0] if m_src else {}
            else:
                m, _ = get_underlying_cached(c, n)
                merge_seed_xop(m)
        except Exception:
            m = {}
        if m:
            comp_series.append((float(c.get("w", 1.0)), m))
    if not comp_series:
        return None
    total_w = sum(w for w, _ in comp_series)
    if total_w <= 0:
        return None
    all_dates = sorted(set().union(*[set(m.keys()) for _, m in comp_series]))
    if not all_dates:
        return None
    blend = {}
    last = None
    for d in all_dates:
        rets = []
        for w, m in comp_series:
            mk = sorted(m.keys())
            pd = None
            for x in mk:            # 取 d 之前最近的可交易日期（严格 < d）
                if x < d:
                    pd = x
                else:
                    break
            if pd is None:
                continue
            cur = m.get(d)
            p = m.get(pd)
            if cur and p:
                rets.append(w * (cur / p - 1))
        if not rets:
            blend[d] = blend[last] if last else 1.0
            last = d
            continue
        r = sum(rets) / total_w
        if not blend:
            blend[d] = 1.0
        else:
            blend[d] = blend[last] * (1 + r)
        last = d
    label = "复合(" + "+".join(c.get("sa", "?") for c in comps) + ")"
    return blend, label


def resolve_xop(code, und, n):
    """取标的序列：若 code 配置为复合标的则返回合成序列，否则走原单标的逻辑。"""
    if code and code in COMPOSITE_UNDERLYING:
        res = _build_composite_xop(code, n)
        if res:
            return res
    return get_underlying_cached(und, n)


def composite_label(code):
    comps = COMPOSITE_UNDERLYING.get(code)
    return "+".join(c.get("sa", "?") for c in comps) if comps else None


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------
# ---- 上游 HTTP 响应内存缓存（TTL）----
# 美西实例跨洋抓东财/腾讯，单次 RTT 高且易抖动；把上游响应缓存 90s，
# 可让重复请求（同基金反复看、排行内多基金共享标的）秒回，且精度无损
# （日内净值/价格/汇率在 90s 内几乎不变）。
_HTTP_CACHE = {}
_HTTP_CACHE_LOCK = threading.Lock()
_HTTP_CACHE_TTL = 90  # 秒


def http_get_json(url, referer=None, timeout=10, retries=2, sleep_base=0.5):
    key = (url, referer)
    now = time.time()
    with _HTTP_CACHE_LOCK:
        hit = _HTTP_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            req.add_header("Accept", "*/*")
            req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
            if referer:
                req.add_header("Referer", referer)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                val = json.loads(resp.read().decode("utf-8", "ignore"))
                with _HTTP_CACHE_LOCK:
                    _HTTP_CACHE[key] = (now + _HTTP_CACHE_TTL, val)
                return val
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(sleep_base + i * 0.5)
    raise last_err


def http_get_text(url, referer=None, timeout=10, retries=2, encoding="utf-8"):
    key = (url, referer)
    now = time.time()
    with _HTTP_CACHE_LOCK:
        hit = _HTTP_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            req.add_header("Accept", "*/*")
            if referer:
                req.add_header("Referer", referer)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                val = resp.read().decode(encoding, "ignore")
                with _HTTP_CACHE_LOCK:
                    _HTTP_CACHE[key] = (now + _HTTP_CACHE_TTL, val)
                return val
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(0.5 + i * 0.5)
    raise last_err


# ---------------------------------------------------------------------------
# 行情数据：净值 / 价格 / 标的 / 汇率 / 申购状态
# ---------------------------------------------------------------------------
def fetch_nav(code, n=120):
    """获取基金单位净值历史。东财 lsjz 单页最多返回约 20 条且对大 pageSize 会报错，
    故按每页 20 条翻页累加到 n 条，保证回测有足够样本（否则仅 ~20 条会导致 w 校准过拟合）。"""
    out = []
    seen = set()
    page = 1
    while len(out) < n and page <= 30:
        url = (f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}"
               f"&pageIndex={page}&pageSize=20&startDate=&endDate=")
        try:
            data = http_get_json(url, referer="http://fundf10.eastmoney.com/")
        except Exception:
            break
        rows = (data or {}).get("Data", {}) or {}
        ls = rows.get("LSJZList") or []
        if not ls:
            break
        added = 0
        for r in ls:
            d, v = r.get("FSRQ"), r.get("DWJZ")
            if d and v not in (None, "--", "") and d not in seen:
                try:
                    out.append((d, float(v)))
                    seen.add(d)
                    added += 1
                except ValueError:
                    pass
        if added == 0 or len(ls) < 20:
            break
        page += 1
    out.sort()                      # 升序：最旧在前、最新在后
    # 东财 lsjz 接口按「最新在前」返回，翻页累加后 out 含多页；
    # 必须取末尾 n 条（最近 n 个交易日）才能与价格日期对齐，
    # 取头部 out[:n] 会留下最旧的一批，导致近期净值全部缺失。
    return out[-n:]


def fetch_kline_eastmoney(secid, n=20):
    fields2 = "f51,f52,f53,f54,f55,f56,f57,f58"
    hosts = ["https://push2his.eastmoney.com", "https://push2delay.eastmoney.com"]
    last_err = None
    for host in hosts:
        try:
            url = (f"{host}/api/qt/stock/kline/get?secid={secid}"
                   f"&fields1=f1,f2,f3,f4,f5,f6&fields2={fields2}"
                   f"&klt=101&fqt=0&end=20500101&lmt={n}"
                   f"&ut=fa5fd1943c7b386f172d6893dbfba10b")
            data = http_get_json(url, referer="https://quote.eastmoney.com/", timeout=15, retries=2)
            klines = data.get("data", {}).get("klines", [])
            if not klines:
                continue
            out = []
            for k in klines:
                p = k.split(",")
                try:
                    out.append((p[0], float(p[2])))
                except (IndexError, ValueError):
                    pass
            out.sort()
            return out, f"东财({host.split('.')[0]})"
        except Exception as e:
            last_err = e
    raise last_err or Exception("东财 K 线无数据")


def fetch_kline_tencent(symbol, n=20):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={symbol},day,,,{n},qfq")
    data = http_get_json(url)
    node = data.get("data", {}).get(symbol)
    if not node:
        return []
    arr = node.get("qfqday") or node.get("day") or []
    out = []
    for row in arr:
        try:
            out.append((row[0], float(row[2])))
        except (IndexError, ValueError):
            pass
    out.sort()
    return out


def fetch_kline_sina(symbol, n=25):
    """新浪财经 K 线（LOF/ETF 场内价格备用源）。symbol 形如 sz164705 / shXXXXXX。"""
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={n}")
    try:
        data = http_get_json(url, referer="https://finance.sina.com.cn/", timeout=15, retries=3)
    except Exception:
        return []
    if not isinstance(data, list) or not data:
        return []
    out = []
    for r in data:
        d = r.get("day")
        c = r.get("close")
        if d and c:
            try:
                out.append((d, float(c)))
            except (ValueError, TypeError):
                pass
    out.sort()
    return out


def fetch_kline_sina_futures(symbol, n=120):
    """新浪财经期货连续合约 K 线（日线）。symbol 如 AG0、AU0、RB0、SC0 等。
    返回 [(date, close), ...] 按日期升序。"""
    url = (f"https://stock.finance.sina.com.cn/futures/api/jsonp.php"
           f"/var=/InnerFuturesNewService.getDailyKLine?symbol={symbol}&_=1")
    try:
        txt = http_get_text(url, timeout=15, retries=3)
    except Exception:
        return []
    m = re.search(r'var=\((.*)\);', txt, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(1))
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for r in arr[-n:]:
        d, c = r.get("d"), r.get("c")
        if d and c:
            try:
                out.append((d, float(c)))
            except (ValueError, TypeError):
                pass
    out.sort()
    return out


def _str_to_date(s):
    try:
        return _date_cls(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, TypeError, IndexError):
        return _date_cls(2000, 1, 1)


def _series_is_fresh(rows, max_gap_days=60):
    """新鲜度校验：最新日期须接近今天，且最近两个点间隔不能离谱（避免腾讯返回
    2020→2026 这种断层旧数据被当成有效序列）。"""
    if not rows:
        return False
    rows = sorted(rows)
    newest = rows[-1][0]
    # 最新点不能超过今天太多（容忍 7 天）；允许未来 1 天（时区）
    if (_date_cls.today() - _str_to_date(newest)).days > 7:
        return False
    if len(rows) >= 2:
        gap = (_str_to_date(rows[-1][0]) - _str_to_date(rows[-2][0])).days
        if gap > max_gap_days:
            return False
    return True


def fetch_price(em_sec, tx_sym, n=25):
    """LOF/ETF 场内价格。多源优先：东财 → 新浪 → 腾讯，取第一个『新鲜』的序列。
    单源若返回陈旧/断层数据（如腾讯对部分基金给出 2020→2026 的坏 kline），
    自动向下一个源回退，避免看板出现数据断层。"""
    sources = [
        ("东财", lambda: fetch_kline_eastmoney(em_sec, n)),
        ("新浪财经", lambda: (fetch_kline_sina(tx_sym, n), "新浪财经")),
        ("腾讯财经", lambda: (fetch_kline_tencent(tx_sym, n), "腾讯财经")),
    ]
    last_err = None
    for name, fn in sources:
        try:
            res = fn()
            rows = res[0] if isinstance(res, tuple) else res
            if rows and _series_is_fresh(rows):
                src = res[1] if isinstance(res, tuple) else name
                return rows, src
            if rows:
                print(f"    [新鲜度] {name} 价格序列存在断层/陈旧，跳过（最新={rows[-1][0]}）")
        except Exception as e:
            last_err = e
            print(f"    [兜底] {name}价格失败：{e}")
    # 全部失败/陈旧：退回腾讯（至少给最新点），保证不空
    try:
        rows = fetch_kline_tencent(tx_sym, n)
        if rows:
            return rows, "腾讯财经(陈旧)"
    except Exception:
        pass
    if last_err:
        raise last_err
    return [], "无数据"


def fetch_price_tencent(tx_sym, n=15):
    """仅使用腾讯价格，用于批量排行场景，避免东财并发限流。"""
    return fetch_kline_tencent(tx_sym, n), "腾讯财经"


def fetch_underlying_stockanalysis(code="XOP", n=25):
    url = f"https://stockanalysis.com/api/symbol/e/{code}/history?range=6M&period=Daily"
    data = http_get_json(url, timeout=15, retries=3)
    h = data.get("data") or []
    out = []
    for r in h:
        try:
            out.append((r["t"], float(r["c"])))
        except (KeyError, ValueError, TypeError):
            pass
    out.sort()
    return out[-n:], "stockanalysis.com"


def fetch_xop(und, n=25):
    """und: {'em':..,'tx':..,'sa':..} 或 None"""
    results = []
    if und:
        em, tx, sa = und.get("em"), und.get("tx"), und.get("sa")
        if em:
            try:
                r, s = fetch_kline_eastmoney(em, n)
                if r:
                    results.append((r, s))
            except Exception as e:
                print(f"    [兜底] 东财标的失败：{e}")
        if tx:
            try:
                r = fetch_kline_tencent(tx, n)
                if r:
                    results.append((r, "腾讯财经"))
            except Exception as e:
                print(f"    [兜底] 腾讯标的失败：{e}")
        if sa:
            try:
                r, s = fetch_underlying_stockanalysis(sa, n)
                if r:
                    results.append((r, s))
            except Exception as e:
                print(f"    [兜底] stockanalysis标的失败：{e}")
    sf = (und or {}).get("sina_futures")
    if sf:
        try:
            r = fetch_kline_sina_futures(sf, n)
            if r:
                results.append((r, "新浪财经期货"))
        except Exception as e:
            print(f"    [兜底] 新浪期货标的失败：{e}")
    if not results:
        return [], "无数据"
    best = max(results, key=lambda x: len(x[0]))
    print(f"    标的候选 {[(len(r), s) for r, s in results]} -> 采用 {best[1]}")
    return best


FX_CACHE = {}              # 汇率缓存（USD/CNY），1 小时刷新
FX_CACHE_TS = 0.0

def fetch_fx_frankfurter(start, end):
    url = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=CNY"
    data = http_get_json(url, timeout=15, retries=2)
    rates = data.get("rates", {})
    out = []
    for d, v in rates.items():
        if "CNY" in v:
            out.append((d, float(v["CNY"])))
    out.sort()
    return out


def fetch_fx_sina_latest():
    url = "https://hq.sinajs.cn/list=fx_susdcny"
    txt = http_get_text(url, referer="https://finance.sina.com.cn/", encoding="gbk")
    if "=" in txt:
        body = txt.split("=", 1)[1].strip().strip('";')
        parts = body.split(",")
        if len(parts) >= 3:
            bid, ask = float(parts[1]), float(parts[2])
            return (bid + ask) / 2.0
    return None


def fetch_fx(days=400):
    """获取 USD/CNY 汇率历史。days 控制回溯窗口（校准需较长窗口以保证回测样本量）。
    结果缓存 1 小时，避免每次请求重复拉取；fx 窗口过小会导致回测样本不足、w 被噪声带偏。"""
    global FX_CACHE, FX_CACHE_TS
    if FX_CACHE and (time.time() - FX_CACHE_TS) < 3600:
        return FX_CACHE
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    try:
        rows = fetch_fx_frankfurter(start, today)
        out.update(dict(rows))
        if rows:
            print(f"    [汇率] frankfurter 取到 {len(rows)} 天")
    except Exception as e:
        print(f"    [兜底] frankfurter 汇率失败：{e}")
    try:
        latest = fetch_fx_sina_latest()
        if latest is not None:
            out[today] = latest
            print(f"    [汇率] 新浪财经最新 USD/CNY = {latest:.4f}")
    except Exception as e:
        print(f"    [兜底] 新浪财经汇率失败：{e}")
    if not out:
        out.update(SEED_FX)
        print("    [汇率] 使用内置 seed 数据兜底")
    FX_CACHE = out
    FX_CACHE_TS = time.time()
    return out


# ---------------------------------------------------------------------------
# 主动管理基金「按持仓估算」模式
# 适用：不跟踪单一指数、净值与指数代理相关性低的主动管理基金（如 160644 鹏华港美互联）。
# 思路：抓基金前十大重仓 → 逐只取行情（美股 stockanalysis / 港股腾讯 hkXXXX / A股腾讯 sz|sh）
#       → 按占净值比例合成 RMB 收益组合（含 USD/CNY、HKD/CNY 换汇）→ 作为「合成标的」
#       复用现有 w/lag 公式（w=1、FX 已折入组合、lag=1）估算净值。
# 模式 HOLDINGS_MODE[code] = "auto"(择优) | "holdings"(强制持仓) | "index"(强制指数代理)
# ---------------------------------------------------------------------------
HOLDINGS_MODE = {
    # 160644 鹏华港美互联：偏主动管理，净值与 KWEB 相关性仅 ~0.27。
    # 实测持仓估算 MAE≈0.86% < 指数代理(KWEB+HKNET) 1.73%，默认自动择优。
    "160644": "auto",
}
HOLDINGS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings_mode_cache.json")
HOLDINGS_CHOICE_TTL = 24 * 3600
HOLDINGS_CHOICE_CACHE = {}   # code -> {mode, idx_mae, hld_mae, ts}
HOLDINGS_INDEX_CACHE = {}    # code -> (index_map, meta, ts)
HOLDINGS_INDEX_TTL = 600
HOLDINGS_RAW_TTL = 24 * 3600
HOLDINGS_RAW_CACHE = {}      # code -> (holdings_list, ts)

def load_holdings_choice_cache():
    global HOLDINGS_CHOICE_CACHE
    try:
        if os.path.exists(HOLDINGS_CACHE_FILE):
            HOLDINGS_CHOICE_CACHE = json.load(open(HOLDINGS_CACHE_FILE, encoding="utf-8")) or {}
    except Exception:
        HOLDINGS_CHOICE_CACHE = {}

def save_holdings_choice_cache():
    try:
        json.dump(HOLDINGS_CHOICE_CACHE, open(HOLDINGS_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def fetch_holdings(code):
    """抓基金前十大重仓，返回 [(name, weight_frac, market, symbol), ...]。
    market ∈ {US, HK, A}；symbol：US= ticker(如 MU)，HK= hk+5位(如 hk00700)，A= 6位代码。"""
    cached = HOLDINGS_RAW_CACHE.get(code)
    if cached and (time.time() - cached[1]) < HOLDINGS_RAW_TTL:
        return cached[0]
    url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10&year=&month="
    txt = None
    for enc in ("utf-8", "gbk"):
        try:
            txt = http_get_text(url, referer="https://fundf10.eastmoney.com/", timeout=15, retries=3, encoding=enc)
            if txt and "占净值" in txt:
                break
        except Exception:
            txt = None
    if not txt:
        print(f"    [持仓] {code} f10 抓取失败")
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S)
    out = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 4:
            continue
        am = re.search(r">([A-Za-z0-9.]{1,8})</a>", cells[1])
        if not am:
            continue
        raw = am.group(1).strip()
        # 占净值比例：行内寻找含 % 的单元格（不同基金列序可能不同，故全行搜索）
        w = None
        for c in cells:
            pm = re.search(r"([\d.]+)\s*%", c)
            if pm:
                try:
                    w = float(pm.group(1)) / 100.0
                except ValueError:
                    w = None
                break
        if w is None:
            continue
        name = re.sub("<.*?>", "", cells[2]).strip()
        up = raw.upper()
        if up.startswith("HK"):
            market, sym = "HK", "hk" + re.sub(r"\D", "", up).zfill(5)
        elif raw.isdigit() and len(raw) == 5:
            market, sym = "HK", "hk" + raw.zfill(5)
        elif raw.isdigit() and len(raw) == 6:
            market, sym = "A", raw
        elif raw.isalpha() or re.match(r"^[A-Z.]+$", up):
            market, sym = "US", up.replace(".", "")
        else:
            continue
        out.append((name, w, market, sym))
    seen, dedup = set(), []
    for h in out:
        if h[3] in seen:
            continue
        seen.add(h[3])
        dedup.append(h)
    out = dedup[:10]
    HOLDINGS_RAW_CACHE[code] = (out, time.time())
    print(f"    [持仓] {code} 抓到 {len(out)} 只重仓："
          + "、".join(f"{n}({round(w*100,1)}%)" for n, w, _, _ in out))
    return out

def fetch_holding_kline(market, sym, n):
    """取单个重仓股的日线收盘（本地货币）。US→stockanalysis；HK→腾讯 hk；A→腾讯 sz/sh。"""
    try:
        if market == "US":
            r, _ = fetch_underlying_stockanalysis(sym, n)
            return dict(r)
        elif market == "HK":
            return dict(fetch_kline_tencent(sym, n))
        elif market == "A":
            prefix = "sh" if sym[0] == "6" else "sz"
            return dict(fetch_kline_tencent(prefix + sym, n))
    except Exception as e:
        print(f"    [持仓] {sym} 行情获取失败：{e}")
    return {}

def _fx_at(fx_map, d):
    if d in fx_map:
        return fx_map[d]
    sd = sorted(x for x in fx_map if x <= d)
    return fx_map[sd[-1]] if sd else None

def build_holdings_index(code, n=60):
    """合成持仓收益指数（date->价，已折入 USD/HKD→CNY 换汇）。返回 (index_map, meta) 或 (None, {error})。"""
    cached = HOLDINGS_INDEX_CACHE.get(code)
    if cached and (time.time() - cached[2]) < HOLDINGS_INDEX_TTL:
        return cached[0], cached[1]
    holdings = fetch_holdings(code)
    if not holdings:
        return None, {"error": "无持仓数据（f10 未披露或非主动管理基金）"}
    fx = fetch_fx()
    klines = {}
    for (name, w, market, sym) in holdings:
        kl = fetch_holding_kline(market, sym, n)
        if kl:
            klines[sym] = kl
    if not klines:
        return None, {"error": "持仓个股行情全部获取失败（可能网络/限流）"}
    all_dates = sorted(set().union(*[set(m) for m in klines.values()]))
    index, last = {}, None
    for d in all_dates:
        port = 0.0
        for (name, w, market, sym) in holdings:
            kl = klines.get(sym)
            if not kl or d not in kl:
                continue
            prevs = [x for x in kl if x < d]
            if not prevs:
                continue
            pd = prevs[-1]
            local_ret = kl[d] / kl[pd] - 1
            if market in ("US", "HK"):
                fx_t, fx_p = _fx_at(fx, d), _fx_at(fx, pd)
                fx_ret = (fx_t / fx_p - 1) if (fx_t and fx_p) else 0.0
            else:
                fx_ret = 0.0
            port += w * ((1 + local_ret) * (1 + fx_ret) - 1)
        index[d] = 1.0 if last is None else index[last] * (1 + port)
        last = d
    coverage = sum(w for (_, w, _, _) in holdings)
    shown = holdings[:6]
    label = "持仓(" + "+".join((h[3].upper() if h[2] == "US" else h[3]) for h in shown) \
            + (")" if len(holdings) <= 6 else f"等{len(holdings)}只)")
    meta = {"label": label, "coverage": round(coverage, 4),
            "holdings": [{"name": n, "w": round(w, 4), "market": m, "sym": s}
                         for (n, w, m, s) in holdings]}
    HOLDINGS_INDEX_CACHE[code] = (index, meta, time.time())
    print(f"    [持仓] {code} 合成指数完成，覆盖 {round(coverage*100,1)}%（{len(holdings)} 只）")
    return index, meta

def holdings_backtest(code, days=60, fx_map=None):
    """用持仓合成指数回测估算净值误差，返回与 backtest_nav_estimate 同构的字典。"""
    n = max(days, 20) + 5
    try:
        nav_rows = fetch_nav(code, n)
        nav_map = dict(nav_rows)
    except Exception as e:
        return {"error": f"净值获取失败: {e}", "code": code}
    try:
        index, meta = build_holdings_index(code, n)
    except Exception as e:
        return {"error": f"持仓指数构建失败: {e}", "code": code}
    if index is None:
        return {"error": meta.get("error", "持仓指数构建失败"), "code": code}
    nav_dates = sorted(nav_map.keys())
    idx_dates = sorted(index.keys())
    if len(nav_dates) < 3:
        return {"error": "官方净值样本不足", "code": code}
    records = []
    for i, T in enumerate(nav_dates[1:], start=1):
        nav_t1 = nav_map[nav_dates[i - 1]]
        nav_t = nav_map[T]
        xop_t_date = prev_trade_day(idx_dates, T)
        if not xop_t_date:
            continue
        idx = idx_dates.index(xop_t_date)
        xop_t1_date = idx_dates[max(0, idx - 1)]   # 持仓 lag=1
        xop_t, xop_t1 = index.get(xop_t_date), index.get(xop_t1_date)
        if not (nav_t1 and xop_t1 and xop_t):
            continue
        fv = nav_t1 * (1 + 1.0 * (xop_t / xop_t1 - 1))
        bias = (fv - nav_t) / nav_t * 100
        records.append({"date": T, "nav_t1": round(nav_t1, 4), "nav_t": round(nav_t, 4),
                        "fv": round(fv, 4), "bias": round(bias, 4)})
    if not records:
        return {"error": "可对比历史样本不足", "code": code}
    biases = [r["bias"] for r in records]
    mae = sum(abs(b) for b in biases) / len(biases)
    return {"code": code, "underlying": meta.get("label", "持仓"), "weight": 1.0, "lag": 1,
            "count": len(records), "mae": round(mae, 4),
            "median": round(statistics.median(biases), 4),
            "rmse": round((sum(b * b for b in biases) / len(biases)) ** 0.5, 4),
            "coverage": meta.get("coverage"), "records": records[-days:]}

def choose_mode(code, days=60):
    """自动择优：比较指数代理 MAE 与持仓估算 MAE，选更小者。结果持久化 24h。"""
    cached = HOLDINGS_CHOICE_CACHE.get(code)
    if cached and (time.time() - cached.get("ts", 0)) < HOLDINGS_CHOICE_TTL:
        return cached
    mode_cfg = HOLDINGS_MODE.get(code, "index")
    if mode_cfg == "index":
        res = {"mode": "index", "ts": time.time()}
        HOLDINGS_CHOICE_CACHE[code] = res
        save_holdings_choice_cache()
        return res
    idx_bt = _backtest_index(code, days, None)
    hld_bt = holdings_backtest(code, days)
    idx_mae = idx_bt.get("mae") if isinstance(idx_bt, dict) and "mae" in idx_bt else None
    hld_mae = hld_bt.get("mae") if isinstance(hld_bt, dict) and "mae" in hld_bt else None
    if mode_cfg == "holdings":
        mode = "holdings" if hld_mae is not None else "index"
    else:  # auto
        if hld_mae is None:
            mode = "index"
        elif idx_mae is None:
            mode = "holdings"
        else:
            mode = "holdings" if hld_mae <= idx_mae else "index"
    res = {"mode": mode, "idx_mae": idx_mae, "hld_mae": hld_mae, "ts": time.time()}
    # 仅当持仓 MAE 可计算时才持久化择优结果；否则本次回退指数代理但不缓存，
    # 避免启动期校准线程抢占 stockanalysis 导致持仓抓取偶发失败、被误锁 24h。
    if hld_mae is not None:
        HOLDINGS_CHOICE_CACHE[code] = res
        save_holdings_choice_cache()
    return res


def fetch_fund_name(code, retries=2):
    """尝试从东财页面或接口获取基金真实名称，失败返回 None。"""
    try:
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        txt = http_get_text(url, referer="https://fundf10.eastmoney.com/",
                            timeout=10, retries=retries, encoding="utf-8")
        m = re.search(r"<title>(.*?)\(\d{6}\)", txt, re.S)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    try:
        url = (f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
               f"?page=1&pagesize=10&plat=Android&appType=ttjj&product=EFund"
               f"&Version=1&KeyWord={code}")
        data = http_get_json(url, timeout=10, retries=retries)
        for d in data.get("Datas") or []:
            name = d.get("FUNDNAME") or d.get("NAME")
            if name:
                return name.strip()
    except Exception:
        pass
    return None


def fetch_fund_names_batch(codes, chunk=30):
    """批量获取基金名称，返回 {code: name}。"""
    names = {}
    for i in range(0, len(codes), chunk):
        chunk_codes = codes[i:i+chunk]
        try:
            fcodes = ",".join(chunk_codes)
            url = (f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
                   f"?page=1&pagesize={len(chunk_codes)+5}&plat=Android&appType=ttjj&product=EFund"
                   f"&Version=1&FCODES={fcodes}")
            data = http_get_json(url, timeout=15, retries=2)
            for d in data.get("Datas") or []:
                code = d.get("FCODE")
                name = d.get("FUNDNAME") or d.get("NAME") or d.get("SHORTNAME")
                if code and name:
                    names[code.strip()] = name.strip()
        except Exception as e:
            print(f"    [批量名称] 失败：{e}")
    return names


def fetch_fund_control(code, retries=3):
    """从东财 fundf10 jjfl 页面解析申购状态 / 限购金额 / 赎回状态 / 申购起点
    注意：页面返回的是当前最新交易状态，并非每日历史，因此只适合做顶部摘要。
    """
    res = {"subscribe_status": "", "redeem_status": "", "purchase_limit": None,
           "purchase_limit_text": "", "purchase_min": None, "ok": False}
    try:
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        txt = http_get_text(url, referer="https://fundf10.eastmoney.com/",
                            timeout=15, retries=retries, encoding="utf-8")
        m = re.search(r"交易状态：<span>(.*?)</span>", txt)
        if m:
            raw = m.group(1).strip()
            # 归一化：东财页面可能是 "暂停申购" / "限大额" / "开放申购" 等
            if "暂停申购" in raw:
                res["subscribe_status"] = "暂停申购"
            elif "限大额" in raw or "限购" in raw:
                res["subscribe_status"] = "限大额申购"
            elif "开放申购" in raw:
                res["subscribe_status"] = "开放申购"
            else:
                res["subscribe_status"] = raw
        for kw in ["单日累计购买上限", "单笔购买上限", "单日购买上限", "单账户购买上限"]:
            m2 = re.search(kw + r"([\d.]+)元", txt)
            if m2:
                res["purchase_limit"] = float(m2.group(1))
                res["purchase_limit_text"] = kw + m2.group(1) + "元"
                break
        m3 = re.search(r"<span>(开放赎回|暂停赎回)</span>", txt)
        if m3:
            res["redeem_status"] = m3.group(1)
        m4 = re.search(r"申购起点</td><td[^>]*>([\d.]+)元", txt)
        if m4:
            res["purchase_min"] = float(m4.group(1))
        res["ok"] = True
    except Exception as e:
        print(f"    [警告] 申购状态获取失败：{e}")
    return res


def fetch_fund_info(code, retries=2):
    """一次性抓取 fundf10 jjfl 页面，同时解析基金名称与申购状态，减少重复请求。"""
    res = {"name": None, "control": {"subscribe_status": "", "redeem_status": "",
           "purchase_limit": None, "purchase_limit_text": "", "purchase_min": None, "ok": False}}
    try:
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        txt = http_get_text(url, referer="https://fundf10.eastmoney.com/",
                            timeout=15, retries=retries, encoding="utf-8")
        m = re.search(r"<title>(.*?)\(\d{6}\)", txt, re.S)
        if m:
            res["name"] = m.group(1).strip()
        m = re.search(r"交易状态：<span>(.*?)</span>", txt)
        if m:
            raw = m.group(1).strip()
            # 归一化：东财页面可能是 "暂停申购" / "限大额" / "开放申购" 等
            if "暂停申购" in raw:
                res["control"]["subscribe_status"] = "暂停申购"
            elif "限大额" in raw or "限购" in raw:
                res["control"]["subscribe_status"] = "限大额申购"
            elif "开放申购" in raw:
                res["control"]["subscribe_status"] = "开放申购"
            else:
                res["control"]["subscribe_status"] = raw
        for kw in ["单日累计购买上限", "单笔购买上限", "单日购买上限", "单账户购买上限"]:
            m2 = re.search(kw + r"([\d.]+)元", txt)
            if m2:
                res["control"]["purchase_limit"] = float(m2.group(1))
                res["control"]["purchase_limit_text"] = kw + m2.group(1) + "元"
                break
        m3 = re.search(r"<span>(开放赎回|暂停赎回)</span>", txt)
        if m3:
            res["control"]["redeem_status"] = m3.group(1)
        m4 = re.search(r"申购起点</td><td[^>]*>([\d.]+)元", txt)
        if m4:
            res["control"]["purchase_min"] = float(m4.group(1))
        res["control"]["ok"] = True
    except Exception as e:
        print(f"    [警告] 基金信息页获取失败：{e}")
    return res


def is_oil_gas(name, underlying_label=""):
    """判断是否为原油/油气相关基金，用于控制 XOP 专属列/卡片显示。"""
    s = (name or "").upper() + " " + (underlying_label or "").upper()
    return any(k in s for k in ["油", "气", "原油", "油气", "石油", "天然气",
                                "XOP", "OIL", "GAS", "能源"])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def deduce_exchange(code):
    """根据 6 位代码判断交易所，返回 (东财secid, 腾讯前缀)
    深交所：15/16/18/0/2/3 开头；上交所：50/51/60/68 等开头
    """
    c = code.strip()
    two = c[:2]
    if two in ("15", "16", "18") or c[0] in ("0", "2", "3"):
        return "0." + c, "sz" + c          # 深交所
    return "1." + c, "sh" + c              # 上交所


def prev_trade_day(dates_map, d):
    candidates = [k for k in dates_map if k <= d]
    return max(candidates) if candidates else None


def prev_date_lt(sorted_dates, d):
    """返回 sorted_dates 中严格小于 d 的最大日期（用于 T-1 对齐）。"""
    candidates = [k for k in sorted_dates if k < d]
    return max(candidates) if candidates else None


def strict_prev_day(s):
    return (datetime.strptime(s, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def prev_index_date(dates, d):
    try:
        idx = dates.index(d)
        return dates[idx - 1] if idx > 0 else None
    except ValueError:
        return None


def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100


def fmt_pct(v, plus=True):
    if v is None:
        return "—"
    sign = "+" if plus and v > 0 else ""
    return f"{sign}{v:.2f}%"


def fmt_num(v, decimals=4):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def signal_for_premium(premium, threshold=THRESHOLD):
    if premium is None:
        return "—", ""
    if premium > threshold:
        return "溢价·可申购套利", "premium"
    if premium < -threshold:
        return "折价·可买入赎回", "discount"
    return "平价(观察)", "flat"


def merge_seed_xop(xop_map):
    used = False
    for d, v in SEED_XOP.items():
        if d not in xop_map:
            xop_map[d] = v
            used = True
    return used


def merge_seed_fx(fx_map):
    used = False
    for d, v in SEED_FX.items():
        if d not in fx_map:
            fx_map[d] = v
            used = True
    return used


def build_rows(price_map, nav_map, xop_map, fx_map, days=10, start="", end="",
               anchor_date=None, und=None, code=None,
               w_override=None, lag_override=None, use_fx=True):
    all_dates = sorted(price_map.keys())
    if start or end:
        sd = start or all_dates[0]
        ed = end or all_dates[-1]
        sel = [d for d in all_dates if sd <= d <= ed]
        dates = sel if sel else all_dates
        print(f"    固定窗口 [{sd} ~ {ed}] -> 命中 {len(dates)} 个交易日")
    else:
        dates = all_dates[-days:]
        print(f"    最近 {days} 个交易日 -> 命中 {len(dates)} 个")

    nav_dates = sorted(nav_map.keys())
    xop_dates = sorted(xop_map.keys())
    fx_dates = sorted(fx_map.keys())
    # w/lag：优先使用调用方显式覆盖（持仓模式 w=1、lag=1），否则按标的校准值
    w = w_override if w_override is not None else (weight_for(und, code=code) if und else None)
    lag = lag_override if lag_override is not None else (lag_for(und, code=code) if und else 1)
    has_und = und is not None
    rows = []
    for d in dates:
        price = price_map[d]
        prev_d = prev_index_date(all_dates, d)

        real_nav = nav_map.get(d)
        est_nav = None
        xop_t = None
        fx_t = None
        if has_und and w is not None:
            # 严格 T-1 对齐：以 d 为 T，取 T-1 官方净值作锚
            # FV(T) = NAV(T-1) × [1 + w × (P - 1)]，P = 标的(T)/标的(T-lag) × 汇率(T)/汇率(T-lag)
            # lag 为各标的校准出的对齐滞后窗口（股票型=1，白银期货=2）
            nav_t1_date = prev_date_lt(nav_dates, d)
            xop_t_date = prev_trade_day(xop_map, d)
            if xop_t_date:
                idx = xop_dates.index(xop_t_date)
                k = max(0, idx - (lag if lag is not None else 1))
                xop_t1_date = xop_dates[k]
            else:
                xop_t1_date = None
            fx_t_date = xop_t_date
            fx_t1_date = xop_t1_date
            nav_t1 = nav_map.get(nav_t1_date) if nav_t1_date else None
            xop_t = xop_map.get(xop_t_date) if xop_t_date else None
            xop_t1 = xop_map.get(xop_t1_date) if xop_t1_date else None
            fx_t = fx_map.get(fx_t_date) if fx_t_date else None
            fx_t1 = fx_map.get(fx_t1_date) if fx_t1_date else None
            # 持仓模式：FX 已折入组合，use_fx=False 时 FX 因子取 1
            if nav_t1 and xop_t1 and xop_t and (True if not use_fx else (fx_t1 and fx_t)):
                P = (xop_t / xop_t1) * ((fx_t / fx_t1) if use_fx else 1.0)
                est_nav = nav_t1 * (1 + w * (P - 1))
        # 国内 / 无标的基金：估算净值回退为最近官方净值（填满列，避免空白）
        if est_nav is None and real_nav is not None:
            est_nav = real_nav

        is_est_nav = real_nav is None and est_nav is not None
        used_nav = real_nav if real_nav is not None else est_nav
        # 误差：估算净值 vs 实际官方净值（仅官方净值已公布时才有意义）
        nav_err = None
        if has_und and real_nav is not None and est_nav is not None:
            nav_err = (est_nav - real_nav) / real_nav * 100

        premium = pct(price, used_nav) if used_nav else None
        est_premium = pct(price, est_nav) if est_nav is not None else None

        rows.append({
            "date": d,
            "price": price,
            "price_change": pct(price, price_map.get(prev_d)),
            "fx": fx_t,
            "fx_change": pct(fx_t, fx_map.get(prev_d)),
            "real_nav": real_nav,
            "nav_change": pct(real_nav, nav_map.get(prev_d)),
            "est_nav": est_nav,
            "is_est_nav": is_est_nav,
            "nav_err": nav_err,
            "xop": xop_t,
            "premium": premium,
            "est_premium": est_premium,
        })
    return rows


def compute(code, days=10, start="", end="", underlying=None, threshold=THRESHOLD, mode=None):
    """核心计算：返回可直接序列化为 JSON 的字典。
    mode: 估值模式覆盖（"auto"/"holdings"/"index"）；None 时取 HOLDINGS_MODE 配置。"""
    code = (code or "").strip()
    reg = FUND_REGISTRY.get(code)
    name = fetch_fund_name(code) or (reg["name"] if reg else f"基金{code}")
    em_sec, tx_sym = deduce_exchange(code)

    if underlying:
        u = underlying.strip().upper()
        und = {"em": "107." + u, "tx": "us" + u, "sa": u}
    else:
        und = underlying_for(code, name, reg)
    underlying_label = composite_label(code) or (und["sa"] if und else "")

    # 估值模式：用户显式覆盖 > 基金配置；未配置基金强制指数代理
    mode_cfg = mode if mode in ("auto", "holdings", "index") else HOLDINGS_MODE.get(code, "index")
    effective = mode_cfg
    mode_info = {"cfg": mode_cfg}
    holdings_meta = None
    holdings_error = None

    print(f">>> [{code}] {name} · 近{days}日 ｜ 标的={underlying_label or '无'} ｜ 模式={mode_cfg}")
    nav = fetch_nav(code, max(days, 25) + 5)
    print(f"    净值 {len(nav)} 条，最新: {nav[-1] if nav else None}")
    price, psrc = fetch_price(em_sec, tx_sym, max(days, 25) + 5)
    print(f"    价格 [{psrc}] {len(price)} 条，最新: {price[-1] if price else None}")
    fx = fetch_fx()
    print(f"    汇率 {len(fx)} 天，最新: {sorted(fx.items())[-1]}")

    # 默认按指数代理准备估算源
    xop, xsrc = resolve_xop(code, und, max(days, 25) + 5)
    print(f"    标的 [{xsrc}] {len(xop)} 条，最新: {sorted(xop.items())[-1] if xop else None}")
    xop_map = dict(xop)
    fx_map = fx
    w_use = weight_for(und, code=code) if und else None
    lag_use = lag_for(und, code=code) if und else 1
    use_fx_flag = und.get("use_fx", True) if und else True
    seed_xop = merge_seed_xop(xop_map)
    seed_fx = merge_seed_fx(fx_map)
    if seed_xop or seed_fx:
        print("    [注意] 部分标的/汇率使用 seed 兜底（本机通常被实时数据覆盖）")

    # 持仓估算分支：auto 先择优，holdings 强制；失败回退指数代理
    if effective in ("holdings", "auto"):
        try:
            if effective == "auto":
                choice = choose_mode(code, max(days, 30))
                effective = choice["mode"]
                mode_info.update(choice)
            if effective == "holdings":
                hindex, hmeta = build_holdings_index(code, max(days, 25) + 5)
                if hindex:
                    xop_map = hindex
                    fx_map = fx                      # 真实汇率仅用于展示，估算已折入组合
                    w_use, lag_use, use_fx_flag = 1.0, 1, False
                    underlying_label = hmeta.get("label", "持仓")
                    xsrc = hmeta.get("label", "持仓")
                    holdings_meta = hmeta
                    seed_xop = 0
                else:
                    effective = "index"
                    holdings_error = hmeta.get("error")
        except Exception as e:
            effective = "index"
            holdings_error = f"持仓估算失败: {e}"

    nav_map, price_map = dict(nav), dict(price)
    rows = build_rows(price_map, nav_map, xop_map, fx_map,
                      days=days, start=start, end=end, anchor_date=ANCHOR_DATE, und=und, code=code,
                      w_override=w_use, lag_override=lag_use, use_fx=use_fx_flag)
    rows.reverse()   # 倒序：日期最新在顶端

    control = fetch_fund_control(code)

    if rows:
        latest = rows[0]
        sig_premium = latest["est_premium"] if latest["est_premium"] is not None else latest["premium"]
        sig_text, sig_cls = signal_for_premium(sig_premium, threshold)
    else:
        sig_text, sig_cls, sig_premium = "—", "", None

    oil_gas = is_oil_gas(name, underlying_label)

    return {
        "code": code, "name": name, "underlying_label": underlying_label,
        "is_oil_gas": oil_gas, "threshold": threshold, "use_fx": use_fx_flag,
        "est_mode": effective, "mode_cfg": mode_cfg,
        "holdings_info": (mode_info if (mode_cfg == "auto" or effective == "holdings") else None),
        "holdings_meta": holdings_meta,
        "holdings_error": holdings_error,
        "sources": {"price": psrc, "underlying": xsrc},
        "control": control, "rows": rows,
        "summary": {
            "latest_price": rows[0]["price"] if rows else None,
            "latest_premium": sig_premium,
            "latest_xop": (rows[0]["xop"] if rows and use_fx_flag else None),
            "latest_fx": rows[0]["fx"] if rows else None,
        },
        "signal": {"text": sig_text, "cls": sig_cls},
        "seed_used": seed_xop or seed_fx,
    }


def compute_one_rank(code, target_date, fx_map, threshold=THRESHOLD):
    """为排行表计算某基金在 target_date 这一天的快照。"""
    code = code.strip()
    reg = FUND_REGISTRY.get(code)
    info = fetch_fund_info(code, retries=1)
    name = info["name"] or (reg["name"] if reg else f"基金{code}")
    if not name or name.startswith("基金"):
        alt = fetch_fund_name(code)
        if alt:
            name = alt
    control = info["control"]
    em_sec, tx_sym = deduce_exchange(code)
    n = 15
    try:
        nav_rows = fetch_nav(code, n)
        nav_map = dict(nav_rows)
    except Exception as e:
        return {"code": code, "name": name, "error": f"净值获取失败: {e}"}
    try:
        price_rows, psrc = fetch_price_tencent(tx_sym, n)
        price_map = dict(price_rows)
    except Exception as e:
        return {"code": code, "name": name, "error": f"价格获取失败: {e}"}

    all_dates = sorted(price_map.keys())
    if not all_dates:
        return {"code": code, "name": name, "error": "无价格数据"}
    if target_date in price_map:
        d = target_date
    else:
        candidates = [x for x in all_dates if x <= target_date]
        d = candidates[-1] if candidates else all_dates[-1]

    price = price_map.get(d)
    prev_d = prev_index_date(all_dates, d)
    price_change = pct(price, price_map.get(prev_d)) if prev_d else None

    nav_dates = sorted(nav_map.keys())
    nav_candidates = [x for x in nav_dates if x <= d]
    nav_d = nav_candidates[-1] if nav_candidates else None
    nav = nav_map.get(nav_d) if nav_d else None
    nav_prev = prev_index_date(nav_dates, nav_d)
    nav_change = pct(nav, nav_map.get(nav_prev)) if nav_d and nav_prev else None

    premium = None
    est_nav = None
    est_premium = None
    if price and nav and nav != 0:
        premium = (price - nav) / nav * 100

    und = underlying_for(code, name, reg)
    if und:
        try:
            xop_map, xsrc = resolve_xop(code, und, n)
            merge_seed_xop(xop_map)
            use_fx = und.get("use_fx", True)
            # 严格 T-1 对齐：以目标日 d 为 T，取 T-1 日官方净值作锚
            # FV(T) = NAV(T-1) × [1 + w × (P - 1)]
            # P = XOP(T)/XOP(T-1) × (FX(T)/FX(T-1) if use_fx else 1)
            xop_dates = sorted(xop_map.keys())
            nav_t1_date = prev_date_lt(nav_dates, d)
            xop_t_date = prev_trade_day(xop_dates, d)
            if xop_t_date:
                idx = xop_dates.index(xop_t_date)
                k = max(0, idx - lag_for(und, code=code))
                xop_t1_date = xop_dates[k]
            else:
                xop_t1_date = None

            nav_t1 = nav_map.get(nav_t1_date) if nav_t1_date else None
            xop_t = xop_map.get(xop_t_date) if xop_t_date else None
            xop_t1 = xop_map.get(xop_t1_date) if xop_t1_date else None

            if nav_t1 and xop_t1 and xop_t and price:
                if use_fx:
                    fx_t = fx_map.get(xop_t_date) if xop_t_date else None
                    fx_t1 = fx_map.get(xop_t1_date) if xop_t1_date else None
                    if fx_t1 and fx_t:
                        P = (xop_t / xop_t1) * (fx_t / fx_t1)
                    else:
                        P = None
                else:
                    P = xop_t / xop_t1
                if P is not None:
                    w = weight_for(und, code=code)
                    est_nav = nav_t1 * (1 + w * (P - 1))
                    est_premium = (price - est_nav) / est_nav * 100
        except Exception as e:
            print(f"    [{code}] 估算净值失败: {e}")
    # 国内基金 / 无标的基金：估算净值、估算溢价回退为最近净值（填满两列，避免空白）
    if est_nav is None and nav is not None and price is not None:
        est_nav = nav
        est_premium = premium

    sig_premium = est_premium if est_premium is not None else premium
    sig_text, sig_cls = signal_for_premium(sig_premium, threshold)

    return {
        "code": code, "name": name, "short": short_name(code, name),
        "date": d, "time": "15:00",
        "price": price, "price_change": price_change,
        "nav": nav, "nav_date": nav_d, "nav_change": nav_change,
        "premium": premium,
        "est_nav": est_nav, "est_premium": est_premium,
        "subscribe_status": control.get("subscribe_status", ""),
        "purchase_limit": control.get("purchase_limit"),
        "purchase_limit_text": control.get("purchase_limit_text", ""),
        "redeem_status": control.get("redeem_status", ""),
        "signal": sig_text, "signal_cls": sig_cls,
        "error": None,
    }


def _backtest_index(code, days=60, fx_map=None):
    """指数代理回测（原 backtest_nav_estimate 主体），返回 MAE 等字典。"""
    n = max(days, 20) + 5
    try:
        nav_rows = fetch_nav(code, n)
        nav_map = dict(nav_rows)
    except Exception as e:
        return {"error": f"净值获取失败: {e}"}
    reg = FUND_REGISTRY.get(code)
    info = fetch_fund_info(code, retries=1)
    name = info["name"] or (reg["name"] if reg else f"基金{code}")
    if not name or name.startswith("基金"):
        alt = fetch_fund_name(code)
        if alt:
            name = alt
    und = underlying_for(code, name, reg)
    if not und:
        return {"error": "非 QDII/无标的基金，无法估算", "code": code, "name": name}
    use_fx = und.get("use_fx", True)
    if fx_map is None:
        fx_map = fetch_fx()
    try:
        xop_map, xsrc = resolve_xop(code, und, n)
        merge_seed_xop(xop_map)
    except Exception as e:
        return {"error": f"标的获取失败: {e}"}
    xop_dates = sorted(xop_map.keys())
    nav_dates = sorted(nav_map.keys())
    w = weight_for(und, code=code)
    records = []
    for i, T in enumerate(nav_dates[1:], start=1):
        nav_t1 = nav_map[nav_dates[i - 1]]
        nav_t = nav_map[T]
        xop_t_date = prev_trade_day(xop_dates, T)
        if xop_t_date:
            idx = xop_dates.index(xop_t_date)
            xop_t1_date = xop_dates[max(0, idx - lag_for(und, code=code))]
        else:
            xop_t1_date = None
        xop_t = xop_map.get(xop_t_date) if xop_t_date else None
        xop_t1 = xop_map.get(xop_t1_date) if xop_t1_date else None
        if not (nav_t1 and xop_t1 and xop_t):
            continue
        if use_fx:
            fx_t = fx_map.get(xop_t_date) if xop_t_date else None
            fx_t1 = fx_map.get(xop_t1_date) if xop_t1_date else None
            if not (fx_t1 and fx_t):
                continue
            P = (xop_t / xop_t1) * (fx_t / fx_t1)
        else:
            fx_t = fx_t1 = None
            P = xop_t / xop_t1
        fv = nav_t1 * (1 + w * (P - 1))
        bias = (fv - nav_t) / nav_t * 100
        rec = {"date": T, "nav_t1": round(nav_t1, 4), "nav_t": round(nav_t, 4),
               "fv": round(fv, 4), "bias": round(bias, 4),
               "xop_t": round(xop_t, 4)}
        if use_fx:
            rec["fx_t"] = round(fx_t, 4)
        records.append(rec)
    if not records:
        return {"error": "可对比的历史样本不足", "code": code, "name": name}
    biases = [r["bias"] for r in records]
    mae = sum(abs(b) for b in biases) / len(biases)
    return {"code": code, "name": name,
            "underlying": composite_label(code) or und.get("sa"),
            "weight": w, "lag": lag_for(und, code=code),
            "count": len(records), "mae": round(mae, 4),
            "median": round(statistics.median(biases), 4),
            "rmse": round((sum(b * b for b in biases) / len(biases)) ** 0.5, 4),
            "records": records[-days:]}


def backtest_nav_estimate(code, days=60, fx_map=None, mode="index"):
    """
    回测估算净值精度（与历史行为一致）。
    mode: "index" 指数代理 / "holdings" 持仓估算 / "auto" 自动择优
          （auto 返回被选中模式 + 两模式 MAE 对比 idx_mae/hld_mae）。
    """
    if mode == "holdings":
        res = holdings_backtest(code, days, fx_map)
        if isinstance(res, dict) and "error" not in res:
            res["mode"] = "holdings"
        return res
    if mode == "auto":
        choice = choose_mode(code, days)
        res = (holdings_backtest(code, days, fx_map)
               if choice["mode"] == "holdings" else _backtest_index(code, days, fx_map))
        if isinstance(res, dict) and "error" not in res:
            res["mode"] = choice["mode"]
            res["idx_mae"] = choice.get("idx_mae")
            res["hld_mae"] = choice.get("hld_mae")
        return res
    return _backtest_index(code, days, fx_map)


def compute_ranking(codes, target_date=None, threshold=THRESHOLD):
    """并行计算多基金某日快照，按官方溢价降序排列。"""
    codes = [c.strip() for c in codes if c.strip()]
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    fx_map = fetch_fx()
    # 预取去重后的显式标的（注册表 / UNDERLYING_MAP），写入缓存，避免 worker 内重复抓取触发限流
    explicit = set()
    explicit_unds = []
    for c in codes:
        reg = FUND_REGISTRY.get(c)
        name = fetch_fund_name(c) or ""
        und = underlying_for(c, name, reg)
        if und:
            key = und.get("sa") or str(und)
            if key not in explicit:
                explicit.add(key)
                explicit_unds.append(und)
    # 并行预取去重后的标的行情（美股标的走 stockanalysis.com 跨境最慢，串行会拖垮冷启动；
    # 并行后冷启动时间大幅下降，且 UND_CACHE 进程内永久缓存，预热后不再重抓）。
    if explicit_unds:
        with ThreadPoolExecutor(max_workers=min(RANKING_MAX_WORKERS, len(explicit_unds))) as _pe:
            list(_pe.map(lambda u: get_underlying_cached(u, 15), explicit_unds))
    results = []
    with ThreadPoolExecutor(max_workers=RANKING_MAX_WORKERS) as exe:
        futures = {exe.submit(compute_one_rank, c, target_date, fx_map, threshold): c for c in codes}
        for f in as_completed(futures):
            c = futures[f]
            try:
                results.append(f.result())
            except Exception as e:
                results.append({"code": c, "name": f"基金{c}", "error": str(e)})

    def sort_key(r):
        if r.get("error"):
            return (2, 0)
        p = r.get("premium")
        if p is None:
            return (1, 0)
        return (0, -p)
    results.sort(key=sort_key)
    return {"date": target_date, "threshold": threshold, "count": len(results), "rows": results}


def build_csv(rows, control, code, name, oil_gas=False, use_fx=True):
    import io
    sio = io.StringIO()
    w = csv.writer(sio)
    head = ["日期", "价格", "价格涨跌%", "净值", "净值涨跌%", "估算净值", "估值溢价%"]
    if use_fx:
        head += ["汇率", "汇率涨跌"]
    if oil_gas:
        head += ["XOP收盘", "XOP溢价%"]
    head += ["申购状态", "限购金额(元)", "套利信号"]
    w.writerow(head)
    for r in rows:
        sig, _ = signal_for_premium(r["est_premium"] if r["est_premium"] is not None else r["premium"])
        limit = control.get("purchase_limit")
        row = [
            r["date"], fmt_num(r["price"], 4), fmt_pct(r["price_change"], plus=True),
            fmt_num(r["real_nav"], 4) if r["real_nav"] else "待公布",
            fmt_pct(r["nav_change"], plus=True), fmt_num(r["est_nav"], 4),
            fmt_pct(r["est_premium"], plus=True),
        ]
        if use_fx:
            row += [fmt_num(r["fx"], 4), fmt_pct(r["fx_change"], plus=True)]
        if oil_gas:
            row += [fmt_num(r["xop"], 2), fmt_pct(r["premium"], plus=True)]
        row += [
            control.get("subscribe_status", ""), limit if limit is not None else "",
            sig,
        ]
        w.writerow(row)
    return sio.getvalue()


# ---------------------------------------------------------------------------
# 公共样式（界面一、界面二复用）
# ---------------------------------------------------------------------------
COMMON_CSS = r"""
:root{color-scheme:dark;
  --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#c9d1d9; --muted:#8b949e; --title:#f0f6fc;
  --input-bg:#0d1117; --input-text:#f0f6fc; --btn:#1f6feb; --btn-hover:#388bfd; --row-hover:#1c2128;
  --th-bg:#1f6feb; --th-text:#fff; --pos:#ff5b5b; --neg:#2ecc71; --est:#f2a900; --code-bg:#0d1117; --code-text:#79c0ff;
  --sb-warn-bg:#2a1416; --sb-warn-border:#ff4d4f55; --sb-warn-label:#d98b8b;
  --sb-ok-bg:#13251a; --sb-ok-border:#52c41a55; --sb-ok-label:#7ec89a;
  --sb-info-bg:#161b22; --sb-info-border:#30363d; --sb-info-label:#8b949e;
}
:root[data-theme="light"]{color-scheme:light;
  --bg:#ffffff; --panel:#f5f7fa; --border:#e3e8ef; --text:#1f2933; --muted:#6b7280; --title:#111827;
  --input-bg:#ffffff; --input-text:#111827; --btn:#2563eb; --btn-hover:#3b82f6; --row-hover:#f0f4f8;
  --th-bg:#2563eb; --th-text:#ffffff; --pos:#dc2626; --neg:#16a34a; --est:#d97706; --code-bg:#f1f5f9; --code-text:#2563eb;
  --sb-warn-bg:#fef2f2; --sb-warn-border:#fca5a5; --sb-warn-label:#b91c1c;
  --sb-ok-bg:#f0fdf4; --sb-ok-border:#86efac; --sb-ok-label:#15803d;
  --sb-info-bg:#f5f7fa; --sb-info-border:#e3e8ef; --sb-info-label:#6b7280;
}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei","Segoe UI",sans-serif;background:var(--bg);color:var(--text);margin:0;padding:20px;transition:background .2s,color .2s}
.wrap{max-width:1280px;margin:0 auto}
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}
.titles{flex:1;min-width:0}
h1{font-size:22px;margin:0 0 4px;color:var(--title)}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.top-actions{display:flex;align-items:flex-start;gap:8px;flex:none}
.theme-btn{background:var(--panel);color:var(--title);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;white-space:nowrap;flex:none}
a.theme-btn{text-decoration:none}
.theme-btn:hover{border-color:var(--btn);color:var(--btn)}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:12px;color:var(--muted)}
.field input,.field textarea,.field select{background:var(--input-bg);border:1px solid var(--border);border-radius:8px;color:var(--input-text);padding:8px 10px;font-size:14px}
.field input:focus,.field textarea:focus,.field select:focus{outline:none;border-color:var(--btn)}
button{background:var(--btn);color:#fff;border:none;border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer;font-weight:600}
button:hover{background:var(--btn-hover)}
button:disabled{opacity:.6;cursor:wait}
.fund-title{font-size:22px;font-weight:600;color:var(--title);margin-left:auto;padding-left:12px;white-space:nowrap}
.fund-title small{color:var(--muted);font-size:13px;font-weight:400;margin-left:8px}
.statusbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;background:var(--sb-info-bg);border:1px solid var(--sb-info-border);border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px}
.statusbar.warn{border-color:var(--sb-warn-border);background:var(--sb-warn-bg)}
.statusbar.ok{border-color:var(--sb-ok-border);background:var(--sb-ok-bg)}
.statusbar.info{border-color:var(--sb-info-border);background:var(--sb-info-bg)}
.status-item{display:flex;align-items:center;gap:6px}
.status-label{color:var(--muted)}
.statusbar.warn .status-label{color:var(--sb-warn-label)}
.statusbar.ok .status-label{color:var(--sb-ok-label)}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.sitem{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center}
.sitem .l{color:var(--muted);font-size:12px;margin-bottom:4px}
.sitem .v{font-size:18px;font-weight:600;color:var(--title)}
/* 回测精度面板：指标卡在上、说明脚注在下，整体更有序 */
.vmetrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px}
.vnote{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--muted);font-size:12px;line-height:1.7;text-align:left;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:10px}
.vnote b{color:var(--text);font-weight:600}
/* 排行表：名称列左对齐、代码超链接、可点击筛选的统计卡片 */
.name{text-align:left}
.codelink{color:var(--code-text);text-decoration:none;font-weight:600}
.codelink:hover{text-decoration:underline}
.sitem.clickable{cursor:pointer;transition:border-color .15s,box-shadow .15s}
.sitem.clickable:hover{border-color:var(--btn)}
.sitem.clickable.active{border-color:var(--btn);box-shadow:inset 0 0 0 2px var(--btn);background:var(--row-hover)}
.pos{color:var(--pos);font-weight:600}
.neg{color:var(--neg);font-weight:600}
.est{color:var(--est);font-style:italic}
.tablebox{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:8px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;table-layout:auto}
th,td{border:1px solid var(--border);padding:8px 10px;text-align:right;vertical-align:middle;white-space:nowrap}
th{background:var(--th-bg);color:var(--th-text);font-weight:600;text-align:center;position:sticky;top:0}
td:first-child{text-align:left}
.op-cell{width:64px;text-align:center;white-space:nowrap}
.sig-cell{white-space:normal;min-width:104px;text-align:center;line-height:1.35}
.ver{display:inline-block;margin-left:8px;font-size:12px;font-weight:600;color:var(--th-text);background:var(--th-bg);border-radius:999px;padding:1px 10px;vertical-align:middle}
tbody tr:hover{background:var(--row-hover)}
.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600;white-space:nowrap}
.note{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px;font-size:12px;line-height:1.7;color:var(--muted)}
.note ul{margin:6px 0;padding-left:18px}.note li{margin:3px 0}
#loading{color:var(--muted);padding:20px;text-align:center}
#err{color:var(--pos);padding:14px}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;color:var(--code-text)}
/* 响应式布局：窄屏（手机）自适应 */
@media (max-width:760px){
  body{padding:12px;padding-top:max(12px,env(safe-area-inset-top))}
  .topbar{flex-direction:column;align-items:stretch;gap:10px}
  .top-actions{align-self:flex-end}
  .theme-btn{align-self:flex-end}
  .panel{flex-direction:column;align-items:stretch;gap:10px}
  .field{width:100%}
  .field input,.field textarea,.field select{width:100%}
  button{width:100%}
  .fund-title{margin-left:0;margin-top:2px;font-size:18px}
  h1{font-size:18px}
  .sub{font-size:12px}
  .summary{grid-template-columns:repeat(2,1fr)}
  .sitem .v{font-size:16px}
  .statusbar{font-size:12px;gap:8px}
  .tablebox{padding:4px}
  th,td{padding:6px 8px;font-size:12px}
}
@media (max-width:420px){
  .summary{grid-template-columns:1fr}
}
"""

# ---------------------------------------------------------------------------
# 交互网页界面一（由 / 返回，数据通过 /api/data 拉取）
# ---------------------------------------------------------------------------
PAGE_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon.svg">
<title>LOF/ETF 套利数据看板</title>
<style>""" + COMMON_CSS + r"""</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>LOF / ETF 基金套利数据看板 <span class="ver">V1.2</span></h1>
    <div class="sub">填基金代码 → 实时拉取净值/价格/标的/汇率/申购状态，自动算溢价率与套利信号。默认近 10 个交易日，日期倒序（最新在顶端）。</div>
  </div>
  <div class="top-actions">
    <a class="theme-btn" href="/ranking" title="基金溢价排行表">排行表</a>
    <button id="themeBtn" class="theme-btn" onclick="toggleTheme()" title="切换日间 / 夜间模式"><span id="themeIcon">🌙</span><span id="themeLbl">夜间</span></button>
  </div>
</div>

<div class="panel">
  <div class="field"><label>基金代码</label><input id="code" value="162411"></div>
  <div class="field"><label>近 N 个交易日</label><input id="days" value="10" type="number" min="3" max="60"></div>
  <div class="field"><label>标的ETF代码(可选)</label><input id="und" placeholder="如 XOP/QQQ/SPY" value=""></div>
  <div class="field"><label>溢价率阈值 %</label><input id="threshold" value="1.5" type="number" step="0.1" min="0.1" max="10"></div>
  <div class="field"><label>估值模式</label><select id="mode">
    <option value="auto">自动择优</option>
    <option value="index">指数代理</option>
    <option value="holdings">持仓估算</option>
  </select></div>
  <button id="btn" onclick="load()">查询</button>
  <div id="fund-title" class="fund-title"></div>
</div>

<div id="statusbar" class="statusbar" style="display:none"></div>
<div id="summary" class="summary"></div>
<div id="validate" class="summary" style="display:none"></div>
<div id="loading">加载中…</div>
<div id="err"></div>
<div class="tablebox" id="tablebox" style="display:none"><table id="tbl"></table></div>

<div class="note">
<b>套利要点</b>
<ul>
  <li><b>溢价</b> = (价格 − 净值) / 净值；<b>估值溢价</b> = (价格 − 估算净值) / 估算净值。<b>误差</b> = (估算净值 − 实际官方净值) / 实际官方净值 × 100%，表示估算与真实净值的偏差；最新一日净值待公布时显示「—」。红色=溢价/上涨，绿色=折价/下跌；黄色斜体=净值待公布(用估算)。</li>
  <li><b>申购状态</b> 是套利前提：若显示 <b>暂停申购</b>，即使溢价再高也无法做「申购→卖出」套利；<b>限大额申购</b> 会受每日上限约束（见顶部状态条）。折价赎回套利则看赎回状态。</li>
  <li>估算净值 = NAV(T-1) × [1 + w × (P − 1)]，其中 P = 标的(T)/标的(T-1) × 汇率(T)/汇率(T-1)，w 为仓位系数；w 默认 0.95，并已按各标的的历史回测自动校准到 4 位小数（更贴近真实传导比例）。QDII 净值 T+1 公布，受美股时差、汇率、跟踪误差影响，存在偏差，仅供参考，不构成投资建议。</li>
</ul>
</div>
</div>
<script>
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentMode="auto";
function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon');
  const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){
  const cur = (document.documentElement.getAttribute('data-theme')==='light') ? 'dark' : 'light';
  applyTheme(cur);
}
function initTheme(){
  let t='dark';
  try{ t = localStorage.getItem('arb_theme') || 'dark'; }catch(e){}
  applyTheme(t);
}
initTheme();
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

async function load(){
  const code=document.getElementById('code').value.trim();
  const days=document.getElementById('days').value.trim();
  const und=document.getElementById('und').value.trim();
  const threshold=document.getElementById('threshold').value.trim();
  currentMode=document.getElementById('mode').value.trim();
  const btn=document.getElementById('btn');
  btn.disabled=true; document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('summary').innerHTML='';
  document.getElementById('statusbar').style.display='none';
  document.getElementById('fund-title').innerHTML='';
  try{
    let url='/api/data?code='+encodeURIComponent(code)+'&days='+encodeURIComponent(days)
          +'&threshold='+encodeURIComponent(threshold)+'&mode='+encodeURIComponent(currentMode);
    if(und) url+='&underlying='+encodeURIComponent(und);
    const r=await fetch(url); const d=await r.json();
    if(d.error){ throw new Error(d.error); }
    render(d);
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
  }
}

function render(d){
  const code=d.code, name=d.name||('基金'+code);
  // 右侧大标题：基金名称 + 代码
  document.getElementById('fund-title').innerHTML=esc(name)+' <small>'+esc(code)+'</small>';

  // 交易状态条（申购状态、限购、赎回）—— 这是基金当前状态，不是每日变化数据
  const c=d.control||{};
  const st=c.subscribe_status||'';
  const stCol=STATUS_COLORS[st]||'#8c8c8c';
  const bar=document.getElementById('statusbar');
  bar.style.display='flex';
  let barClass='info', barHtml='';
  if(st){
    barClass = st==='暂停申购'?'warn':(st==='限大额申购'?'ok':'ok');
    let hint='';
    if(st==='暂停申购') hint='当前无法做「申购套利」，仅折价赎回套利可行（需看赎回状态）。';
    else if(st==='限大额申购') hint='可做申购套利，但受每日上限约束。';
    else if(st==='开放申购') hint='申购通道正常开放。';
    barHtml='<div class="status-item"><span class="status-label">申购状态</span>'
          +'<span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st)+'</span></div>'
          +'<div class="status-item"><span class="status-label">限购金额</span><span>'+(c.purchase_limit_text?esc(c.purchase_limit_text):'—')+'</span></div>'
          +'<div class="status-item"><span class="status-label">赎回状态</span><span>'+esc(c.redeem_status||'—')+'</span></div>'
          +'<div class="status-item"><span class="status-label">申购起点</span><span>'+(c.purchase_min!=null?esc(c.purchase_min+'元'):'—')+'</span></div>'
          +'<div class="status-item" style="margin-left:auto;color:#8b949e">'+hint+'</div>';
  }else{
    barHtml='<div class="status-item">ℹ️ 申购状态获取失败（可能网络受限），请手动核对基金公告。</div>';
  }
  bar.className='statusbar '+barClass;
  bar.innerHTML=barHtml;

  // 摘要卡片（原油/油气基金才显示 XOP 收盘）
  const s=d.summary||{};
  const showOil = !!d.is_oil_gas;
  const summ=[
    ['最新场内价', fmtNum(s.latest_price,4)],
    ['最新估值溢价', fmtPct(s.latest_premium), s.latest_premium>0?'pos':(s.latest_premium<0?'neg':'')],
  ];
  if(d.use_fx!==false){
    summ.push(['最新 USD/CNY', fmtNum(s.latest_fx,4)]);
  }
  if(showOil){
    summ.splice(2,0,['最新 XOP 收盘', fmtNum(s.latest_xop,2)]);
  }
  document.getElementById('summary').innerHTML=summ.map(it=>
    '<div class="sitem"><div class="l">'+it[0]+'</div><div class="v '+(it[2]||'')+'">'+it[1]+'</div></div>'
  ).join('');

  // 表格：日期 价格 涨跌% 净值 净值涨跌幅 估算净值 估值溢价 误差 [汇率 汇率涨跌]
  //       （原油/油气基金追加 XOP收盘、XOP溢价） 申购状态 限购金额 套利信号
  const showFx = d.use_fx!==false;
  const head=['日期','价格','涨跌%','净值','净值涨跌幅','估算净值','估值溢价','误差'];
  if(showFx) head.push('汇率','汇率涨跌');
  if(showOil) head.push('XOP收盘','XOP溢价');
  head.push('申购状态','限购金额','套利信号');
  const limitTxt = c.purchase_limit!=null ? esc(c.purchase_limit+'元') : '—';
  let rowsHtml=d.rows.map(r=>{
    const navCell = r.real_nav!=null? fmtNum(r.real_nav,4)
        : '<span class="est">'+fmtNum(r.est_nav,4)+'<br><small>净值待公布</small></span>';
    const sigR = r.est_premium!=null? r.est_premium : r.premium;
    const sigTxt = sigR==null?'—':(sigR>d.threshold?'溢价·可申购':(sigR<-d.threshold?'折价·可赎回':'平价'));
    const sigC = sigR==null?'':(sigR>d.threshold?'pos':(sigR<-d.threshold?'neg':''));
    let cells='<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+navCell+'</td>'
      +'<td class="'+cls(r.nav_change)+'">'+fmtPct(r.nav_change,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td class="'+cls(r.nav_err)+'">'+(r.nav_err!=null?fmtPct(r.nav_err,true):'—')+'</td>';
    if(showFx){
      cells += '<td>'+fmtNum(r.fx,4)+'</td>'
             + '<td class="'+cls(r.fx_change)+'">'+fmtPct(r.fx_change,true)+'</td>';
    }
    if(showOil){
      cells += '<td>'+fmtNum(r.xop,2)+'</td>'
             + '<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>';
    }
    const stCol=STATUS_COLORS[c.subscribe_status||'']||'#8c8c8c';
    cells += '<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(c.subscribe_status||'—')+'</span></td>'
           + '<td>'+limitTxt+'</td>'
           + '<td class="'+sigC+'">'+sigTxt+'</td>';
    return '<tr>'+cells+'</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML='<tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+rowsHtml;
  document.getElementById('tablebox').style.display='block';
  loadValidate(code);
}

async function loadValidate(code){
  const box=document.getElementById('validate');
  box.style.display='none'; box.innerHTML='';
  try{
    const r=await fetch('/api/validate?code='+encodeURIComponent(code)+'&days=30&mode='+encodeURIComponent(currentMode));
    const d=await r.json();
    if(d.error) return;
    let comp='';
    if(d.idx_mae!=null && d.hld_mae!=null){
      comp=' · 自动择优→'+(d.mode==='holdings'?'持仓':'指数')
        +' · 指数MAE '+esc(d.idx_mae)+'% · 持仓MAE '+esc(d.hld_mae)+'%'
        +(d.mode==='holdings' && d.coverage!=null?(' · 覆盖 '+Math.round(d.coverage*100)+'%'):'');
    }else if(d.mode==='holdings'){
      comp=' · 模式=持仓估算'+(d.coverage!=null?(' · 覆盖 '+Math.round(d.coverage*100)+'%'):'');
    }else if(d.mode==='index'){
      comp=' · 模式=指数代理';
    }
    box.innerHTML='<div class="vmetrics">'
      +'<div class="sitem"><div class="l">估算精度 MAE</div><div class="v">±'+esc(d.mae)+'%</div></div>'
      +'<div class="sitem"><div class="l">中位数偏差</div><div class="v '+(d.median>0?'pos':(d.median<0?'neg':''))+'">'+fmtPct(d.median,true)+'</div></div>'
      +'<div class="sitem"><div class="l">RMSE</div><div class="v">'+esc(d.rmse)+'%</div></div>'
      +'</div>'
      +'<div class="vnote">基于 <b>'+esc(d.count)+'</b> 个交易日回测 · w=<b>'+esc(Number(d.weight).toFixed(4))+'</b> · 滞后窗口 lag=<b>'+esc(d.lag)+'</b> · 标的=<b>'+esc(d.underlying)+'</b>'+comp+' · MAE 越小说明估算越稳。</div>';
    box.style.display='block';
  }catch(e){}
}
document.getElementById('code').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('days').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('threshold').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
// 支持从排行表点击代码跳转：?code=XXXX 预填并自动查询
(function(){
  try{
    const p=new URLSearchParams(location.search);
    const c=(p.get('code')||'').trim();
    if(/^\d{6}$/.test(c)){ document.getElementById('code').value=c; }
  }catch(e){}
})();
load();
// 注册 Service Worker，支持「添加到主屏幕 / 离线看壳」
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{
    navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err));
  });
}
</script>
</body></html>"""

# ---------------------------------------------------------------------------
# 交互网页界面二（由 /ranking 返回，数据通过 /api/ranking 拉取）
# ---------------------------------------------------------------------------
PAGE2_HTML = r"""<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon.svg">
<title>LOF/ETF 基金溢价排行表</title>
<style>""" + COMMON_CSS + r"""
/* 界面二专属样式 */
.watchlist{width:100%;min-height:60px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px}
.add-row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.add-row .field{flex:1;min-width:120px}
.add-row button{padding:9px 14px}
/* 代码清单：挪到查询行右侧，点击展开为下拉编辑菜单（拉菜单） */
.codelist{margin-left:auto;flex:none;min-width:240px;max-width:520px;align-self:flex-end}
.codelist>summary{list-style:none;cursor:pointer;display:flex;flex-direction:column;gap:3px;
  background:var(--input-bg);border:1px solid var(--border);border-radius:8px;padding:8px 12px;
  color:var(--text);font-size:13px;user-select:none}
.codelist>summary::-webkit-details-marker{display:none}
.codelist>summary:hover{border-color:var(--btn)}
.codelist .cl-head{display:flex;align-items:center;gap:8px;font-weight:600;color:var(--title)}
.codelist .cl-head .chev{transition:transform .15s;color:var(--muted)}
.codelist[open] .cl-head .chev{transform:rotate(180deg)}
.codelist .cl-preview{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.codelist .cl-body{margin-top:10px;padding-top:10px;border-top:1px dashed var(--border)}
/* 排行表格：表头锁定 + 横向滚动显示全部列（手机端不再截断中间列） */
.rank-scroll{overflow:auto;max-height:74vh;-webkit-overflow-scrolling:touch}
.rank-scroll table{font-size:12px;table-layout:auto;width:max-content;min-width:100%}
.rank-scroll th,.rank-scroll td{padding:7px 8px;white-space:nowrap}
.rank-scroll th{position:sticky;top:0;z-index:3}
.summary2{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.rank-bar{background:var(--sb-info-bg);border:1px solid var(--sb-info-border);border-radius:10px;padding:12px 14px;display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-bottom:16px;font-size:13px}
.rank-bar .k{color:var(--muted)}
.rank-bar .v{font-weight:600;color:var(--title)}
.del-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:2px 8px;font-size:12px;border-radius:4px;cursor:pointer}
.del-btn:hover{background:#ff4d4f22;border-color:#ff4d4f55;color:#ff4d4f}
.pin-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:2px 7px;font-size:12px;border-radius:4px;cursor:pointer;margin-right:4px;opacity:.55;filter:grayscale(1)}
.pin-btn.on{opacity:1;filter:none;border-color:#ffc53d88;background:#ffc53d1a}
.pin-btn:hover{background:#ffc53d22;border-color:#ffc53d}
.op-cell .pin-btn{margin-right:4px}
.sort-hint{color:var(--muted);font-size:12px;margin-left:8px}
.toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:var(--btn);color:#fff;
  padding:8px 18px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:50}
.toast.show{opacity:1}
@media (max-width:760px){
  .summary2{grid-template-columns:repeat(2,1fr)}
  .add-row .field{width:100%}
  .codelist{margin-left:0;max-width:none;width:100%;align-self:stretch}
  .rank-scroll{max-height:66vh}
}
@media (max-width:420px){
  .summary2{grid-template-columns:1fr}
}
</style></head><body>
<div class="wrap">
<div class="topbar">
  <div class="titles">
    <h1>LOF / ETF 基金溢价排行表 <span class="ver">V1.2</span></h1>
    <div class="sub">多基金按单日官方溢价排序，支持更换日期、增删基金代码，数据实时拉取。</div>
  </div>
  <div class="top-actions">
    <a class="theme-btn" href="/" title="返回单基金套利看板">套利看板</a>
    <button id="themeBtn" class="theme-btn" onclick="toggleTheme()" title="切换日间 / 夜间模式"><span id="themeIcon">🌙</span><span id="themeLbl">夜间</span></button>
  </div>
</div>

<div class="panel">
  <div class="field"><label>查询日期</label><input id="rdate" type="date"></div>
  <div class="field"><label>溢价率阈值 %</label><input id="threshold" value="1.5" type="number" step="0.1" min="0.1" max="10"></div>
  <button id="btn" onclick="load()">查询排行</button>
  <details class="codelist" id="codelist">
    <summary>
      <span class="cl-head"><span id="clCount">基金清单</span><span class="chev">▾</span></span>
      <span class="cl-preview" id="clPreview"></span>
    </summary>
    <div class="cl-body">
      <div class="field" style="width:100%"><label>基金代码清单（逗号 / 空格 / 分号 / 换行分隔）</label>
        <textarea id="watchlist" class="watchlist" placeholder="例如：162411, 161130, 164824"></textarea></div>
      <div class="add-row">
        <div class="field"><label>添加基金代码</label><input id="addCode" placeholder="6 位基金代码"></div>
        <button onclick="addCode()">添加</button>
        <button onclick="saveList();toast('已保存设置')" style="background:var(--panel);color:var(--text);border:1px solid var(--border)">保存设置</button>
        <button onclick="resetList()" style="background:var(--panel);color:var(--text);border:1px solid var(--border)">恢复默认</button>
        <span class="sort-hint">默认按官方溢价降序；点击表头可切换排序</span>
      </div>
    </div>
  </details>
</div>

<div class="rank-bar" id="rankbar" style="display:none"></div>
<div id="summary2" class="summary2"></div>
<div id="loading">加载中…</div>
<div id="err"></div>
<div class="tablebox rank-scroll" id="tablebox" style="display:none"><table id="tbl"></table></div>

<div class="note">
<b>说明</b>
<ul>
  <li><b>官方溢价</b> = (场内价格 − 最近公布净值) / 净值；<b>估算溢价</b> = (场内价格 − 估算净值) / 估算净值。红色表示溢价、绿色表示折价。</li>
  <li>查询日期若为非交易日，会自动落到最近一个 &le; 该日期的交易日。估算净值 = 锚定净值 × (标的_t / 标的_锚) × (汇率_t / 汇率_锚)，与套利看板算法一致；QDII 基金（原油/黄金/纳指/标普/印度等）按各自海外标的估算，国内基金回退为最近净值。</li>
  <li>删除某行后基金代码会自动从清单中移除；添加代码后点击「查询排行」即可刷新；修改清单后点「保存设置」可永久记住，下次打开不再丢失。</li>
</ul>
</div>
</div>
<script>
const DEFAULT_WATCHLIST=["160140","164705","164824","501312","164906","160717","501300","160719","167301","161126","160632","161116","161831","160924","161124","164701","160639","163208","160216","164812","160143","161032","160225","160416","160922","161130","161127","161226","161725","160415","160644","501025","162719","501012","161040","161812","161125","161128","501018","160723","161129","501225"];
const STATUS_COLORS={"暂停申购":"#ff4d4f","限大额申购":"#fa8c16","开放申购":"#52c41a"};
let currentRows=[], sortKey='premium', sortDesc=true, currentFilter=null, currentThreshold=1.5, currentMeta=null;

function applyTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  const icon=document.getElementById('themeIcon'); const lbl=document.getElementById('themeLbl');
  if(icon) icon.textContent = (t==='light') ? '☀️' : '🌙';
  if(lbl) lbl.textContent  = (t==='light') ? '日间' : '夜间';
  try{ localStorage.setItem('arb_theme', t); }catch(e){}
}
function toggleTheme(){ applyTheme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light'); }
function initTheme(){ let t='dark'; try{ t=localStorage.getItem('arb_theme')||'dark'; }catch(e){} applyTheme(t); }
initTheme();
function fmtNum(v,d=4){ return v==null?"—":Number(v).toFixed(d); }
function fmtPct(v,plus=true){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+v.toFixed(2)+"%"; }
function cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function parseWatchlist(){
  const raw=document.getElementById('watchlist').value;
  return [...new Set(raw.split(/[,，;；\s]+/).map(x=>x.trim()).filter(x=>/^\d{6}$/.test(x)))];
}
function setWatchlist(arr){ document.getElementById('watchlist').value = arr.join('\n'); }
function refreshCodeListUI(){
  const list=parseWatchlist();
  const cnt=document.getElementById('clCount');
  const prev=document.getElementById('clPreview');
  if(cnt) cnt.textContent='基金 '+list.length+' 只';
  if(prev) prev.textContent = list.length? list.slice(0,14).join(' ') + (list.length>14?' …':'') : '（空）';
}
function loadList(){
  let list;
  try{ list = JSON.parse(localStorage.getItem('arb_ranking_list')); }catch(e){}
  if(!Array.isArray(list) || list.length===0) list = DEFAULT_WATCHLIST;
  setWatchlist(list);
  refreshCodeListUI();
}
function saveList(){ localStorage.setItem('arb_ranking_list', JSON.stringify(parseWatchlist())); }

// 置顶（钉选）状态：localStorage 持久化，数组顺序即置顶排列顺序
let pins=[];
function loadPins(){ try{ const p=JSON.parse(localStorage.getItem('fundarb_pins')); if(Array.isArray(p)) pins=p.filter(x=>typeof x==='string'); }catch(e){} }
function savePins(){ try{ localStorage.setItem('fundarb_pins', JSON.stringify(pins)); }catch(e){} }
function togglePin(code){
  const i=pins.indexOf(code);
  if(i>=0) pins.splice(i,1); else pins.push(code);
  savePins(); renderBody();
}
function clearPins(){ pins=[]; savePins(); renderBody(); }
function addCode(){
  const inp=document.getElementById('addCode'); const c=inp.value.trim();
  if(!/^\d{6}$/.test(c)){ alert('请输入 6 位基金代码'); return; }
  const list=parseWatchlist();
  if(list.includes(c)){ alert('该代码已在清单中'); inp.value=''; return; }
  list.push(c); setWatchlist(list); saveList(); refreshCodeListUI(); inp.value='';
  load();
}
function removeCode(c){
  const list=parseWatchlist().filter(x=>x!==c); setWatchlist(list); saveList(); refreshCodeListUI(); load();
}
function resetList(){ setWatchlist(DEFAULT_WATCHLIST); saveList(); refreshCodeListUI(); load(); }
function toast(msg){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._tm); t._tm=setTimeout(()=>t.classList.remove('show'), 1600);
}

function today(){ const d=new Date(); const p=n=>String(n).padStart(2,'0'); return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate()); }
function initDate(){
  const d=document.getElementById('rdate');
  let saved; try{ saved=localStorage.getItem('arb_ranking_date'); }catch(e){}
  d.value = saved || today();
}

document.getElementById('addCode').addEventListener('keydown',e=>{ if(e.key==='Enter') addCode(); });

document.getElementById('rdate').addEventListener('change',()=>{
  try{ localStorage.setItem('arb_ranking_date', document.getElementById('rdate').value); }catch(e){}
});

async function load(){
  const date=document.getElementById('rdate').value;
  const threshold=document.getElementById('threshold').value;
  const codes=parseWatchlist();
  if(codes.length===0){ alert('请至少输入一个基金代码'); return; }
  saveList();
  try{ localStorage.setItem('arb_ranking_date', date); }catch(e){}
  const btn=document.getElementById('btn'); btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('err').textContent=''; document.getElementById('tablebox').style.display='none';
  document.getElementById('rankbar').style.display='none'; document.getElementById('summary2').innerHTML='';
  try{
    const url='/api/ranking?date='+encodeURIComponent(date)+'&codes='+encodeURIComponent(codes.join(','))+'&threshold='+encodeURIComponent(threshold);
    const r=await fetch(url); const d=await r.json();
    if(d.error){ throw new Error(d.error); }
    currentRows=d.rows||[]; sortKey='premium'; sortDesc=true; render(d);
  }catch(e){
    document.getElementById('err').textContent='加载失败：'+e.message;
  }finally{
    document.getElementById('loading').style.display='none'; btn.disabled=false;
  }
}

function sortRows(key){
  if(sortKey===key) sortDesc=!sortDesc; else { sortKey=key; sortDesc=true; }
  const isStr = ['code','name','date','subscribe_status','signal'].includes(key);
  currentRows.sort((a,b)=>{
    let av=a[sortKey], bv=b[sortKey];
    if(a.error) av=null; if(b.error) bv=null;
    if(av==null && bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    if(isStr) return sortDesc? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    return sortDesc? (bv-av) : (av-bv);
  });
  renderBody();
}
function render(meta){
  currentMeta=meta; currentThreshold=meta.threshold;
  const rows=currentRows;
  const ok=rows.filter(r=>!r.error);
  const premium=ok.filter(r=>r.premium!=null);
  const maxPrem = premium.length? premium.reduce((a,b)=>a.premium>b.premium?a:b) : null;
  const minPrem = premium.length? premium.reduce((a,b)=>a.premium<b.premium?a:b) : null;

  const bar=document.getElementById('rankbar');
  bar.style.display='flex';
  bar.innerHTML='<div class="status-item"><span class="k">查询日期</span><span class="v">'+esc(meta.date)+'</span></div>'
    +'<div class="status-item"><span class="k">基金数</span><span class="v">'+rows.length+'</span></div>'
    +'<div class="status-item"><span class="k">成功</span><span class="v">'+ok.length+'</span></div>'
    +(maxPrem?'<div class="status-item"><span class="k">最高溢价</span><span class="v pos">'+fmtPct(maxPrem.premium)+' '+esc(maxPrem.name)+'</span></div>':'')
    +(minPrem?'<div class="status-item"><span class="k">最高折价</span><span class="v neg">'+fmtPct(minPrem.premium)+' '+esc(minPrem.name)+'</span></div>':'')
    +(pins.length?'<div class="status-item clickable" onclick="clearPins()" title="取消全部置顶"><span class="k">已置顶</span><span class="v" style="color:#ffc53d">'+pins.length+' 只 · 清除</span></div>':'');

  renderSummary();
  sortKey='premium'; sortDesc=true; sortRows('premium');
}

// 统计卡片：三项数值可点击筛选；再次点击或「清除筛选」取消
function renderSummary(){
  const meta=currentMeta; if(!meta) return;
  const rows=currentRows;
  const ok=rows.filter(r=>!r.error);
  const up=ok.filter(r=>r.premium>meta.threshold).length;
  const down=ok.filter(r=>r.premium<-meta.threshold).length;
  const sub=ok.filter(r=>r.subscribe_status&&r.subscribe_status!=='暂停申购'&&r.premium>meta.threshold).length;
  const card=(lbl,val,cls,type)=>'<div class="sitem clickable'+(currentFilter===type?' active':'')+'" onclick="setFilter(\''+type+'\')" title="点击筛选符合条件的基金"><div class="l">'+lbl+'</div><div class="v '+cls+'">'+val+'</div></div>';
  let html=[
    card('溢价 > '+meta.threshold+'%', up, 'pos', 'premium'),
    card('折价 < -'+meta.threshold+'%', down, 'neg', 'discount'),
    card('可申购套利', sub, '', 'subscribe'),
    '<div class="sitem"><div class="l">数据异常</div><div class="v">'+(rows.length-ok.length)+'</div></div>',
  ];
  if(currentFilter){
    html.push('<div class="sitem clickable active" onclick="setFilter(null)" title="清除筛选"><div class="l">清除筛选</div><div class="v">✕</div></div>');
  }
  document.getElementById('summary2').innerHTML=html.join('');
}

function applyFilter(r){
  if(r.error) return false;
  if(currentFilter==='premium')    return r.premium>currentThreshold;
  if(currentFilter==='discount')   return r.premium<-currentThreshold;
  if(currentFilter==='subscribe')  return r.subscribe_status && r.subscribe_status!=='暂停申购' && r.premium>currentThreshold;
  return true;
}

function setFilter(type){
  currentFilter = (currentFilter===type && type!==null) ? null : type;
  renderSummary();   // 刷新卡片高亮
  renderBody();      // 按筛选重绘表格
}

function renderBody(){
  const head=[
    {k:'code',l:'代码'},{k:'name',l:'名称'},{k:'date',l:'日期'},
    {k:'price',l:'价格'},{k:'price_change',l:'涨幅%'},{k:'nav',l:'净值'},{k:'nav_date',l:'净值日期'},
    {k:'premium',l:'官方溢价'},{k:'est_nav',l:'估算净值'},{k:'est_premium',l:'估算溢价'},
    {k:'subscribe_status',l:'申购状态'},{k:'purchase_limit',l:'限购金额'},{k:'signal',l:'套利信号'},{k:'',l:'操作'}
  ];
  const hHtml=head.map(h=>{ const cls=(h.l==='操作')?' class="op-cell"':''; return h.k? '<th'+cls+' style="cursor:pointer" onclick="sortRows(\''+h.k+'\')" title="点击排序">'+esc(h.l)+'</th>' : '<th'+cls+'>'+esc(h.l)+'</th>'; }).join('');
  let rows = currentFilter ? currentRows.filter(applyFilter) : currentRows;
  // 置顶排序：被钉选的基金浮到表首（按 pins 数组顺序），其余保持当前排序在后
  if(pins.length){
    const pinnedSet=new Set(pins); const pinned=[], unpinned=[];
    for(const r of rows){ if(!r.error && pinnedSet.has(r.code)) pinned.push(r); else unpinned.push(r); }
    pinned.sort((a,b)=> pins.indexOf(a.code)-pins.indexOf(b.code));
    rows = pinned.concat(unpinned);
  }
  const rowsHtml=rows.map(r=>{
    if(r.error) return '<tr><td>'+esc(r.code)+'</td><td colspan="14" style="text-align:left;color:var(--muted)">'+esc(r.name)+' — '+esc(r.error)+'</td></tr>';
    const st=r.subscribe_status||''; const stCol=STATUS_COLORS[st]||'#8c8c8c';
    const limitTxt = r.purchase_limit!=null ? esc(r.purchase_limit+'元') : '—';
    const sigC = r.signal_cls==='premium'?'pos':(r.signal_cls==='discount'?'neg':'');
    return '<tr>'
      +'<td class="code"><a class="codelink" href="/?code='+esc(r.code)+'">'+esc(r.code)+'</a></td>'
      +'<td class="name" title="'+esc(r.name)+'">'+esc(r.short||r.name)+'</td>'
      +'<td>'+esc(r.date)+'</td>'
      +'<td>'+fmtNum(r.price,4)+'</td>'
      +'<td class="'+cls(r.price_change)+'">'+fmtPct(r.price_change,true)+'</td>'
      +'<td>'+fmtNum(r.nav,4)+'</td>'
      +'<td>'+esc(r.nav_date||'—')+'</td>'
      +'<td class="'+cls(r.premium)+'">'+fmtPct(r.premium,true)+'</td>'
      +'<td>'+fmtNum(r.est_nav,4)+'</td>'
      +'<td class="'+cls(r.est_premium)+'">'+fmtPct(r.est_premium,true)+'</td>'
      +'<td><span class="badge" style="background:'+stCol+'22;color:'+stCol+';border:1px solid '+stCol+'55">'+esc(st||'—')+'</span></td>'
      +'<td>'+limitTxt+'</td>'
      +'<td class="'+sigC+' sig-cell">'+esc(r.signal)+'</td>'
      +'<td class="op-cell"><button class="pin-btn'+(pins.includes(r.code)?' on':'')+'" onclick="togglePin(\''+esc(r.code)+'\')" title="置顶/取消置顶">📌</button><button class="del-btn" onclick="removeCode(\''+esc(r.code)+'\')" title="移除">×</button></td>'
      +'</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML='<tr>'+hHtml+'</tr>'+rowsHtml;
  document.getElementById('tablebox').style.display='block';
}

loadList(); loadPins(); initDate(); load();
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{ navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW 注册失败：',err)); });
}
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# PWA 资源（manifest / service worker / 图标）
# ---------------------------------------------------------------------------
MANIFEST_JSON = r"""{
  "name": "LOF/ETF 基金套利数据看板",
  "short_name": "套利看板",
  "description": "实时拉取 LOF/ETF 净值、价格、标的、汇率与申购状态，计算溢价率与套利信号。",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#0d1117",
  "theme_color": "#0d1117",
  "orientation": "portrait",
  "icons": [
    {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
  ]
}"""

ICON_SVG = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0d1117"/>
  <rect x="96" y="300" width="56" height="116" rx="8" fill="#2ecc71"/>
  <rect x="176" y="240" width="56" height="176" rx="8" fill="#2ecc71"/>
  <rect x="256" y="180" width="56" height="236" rx="8" fill="#ff5b5b"/>
  <rect x="336" y="120" width="56" height="296" rx="8" fill="#ff5b5b"/>
  <path d="M120 200 L256 150 L392 110" fill="none" stroke="#f0f6fc" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M372 96 L398 108 L380 132 Z" fill="#f0f6fc"/>
</svg>"""

SW_JS = r"""const CACHE='fundarb-v1.2';
const SHELL=['/','/ranking','/manifest.json','/icon.svg'];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',e=>{
  const url=new URL(e.request.url);
  // 数据接口：网络优先，失败回退缓存
  if(url.pathname.startsWith('/api/')){
    e.respondWith(
      fetch(e.request).then(r=>{const cp=r.clone();caches.open(CACHE).then(c=>c.put(e.request,cp));return r;})
        .catch(()=>caches.match(e.request))
    );
    return;
  }
  // 静态壳：缓存优先，回退网络
  e.respondWith(
    caches.match(e.request).then(c=>c||fetch(e.request).then(r=>{const cp=r.clone();caches.open(CACHE).then(ca=>ca.put(e.request,cp));return r;}))
  );
});
"""


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    _DIR = os.path.dirname(os.path.abspath(__file__))

    def _serve_file(self, fname, fallback, ctype):
        p = os.path.join(self._DIR, fname)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                body = f.read()
        else:
            body = fallback
        self._send(200, body, ctype)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        # 安全响应头：防 MIME 嗅探 / 点击劫持 / referrer 泄露 / 非法嵌入
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        # 跨域仅放行本地/同源（含 file:// 的独立 HTML）；杜绝任意站点跨域调用
        origin = self.headers.get("Origin")
        if origin and (re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin) or origin == "null"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    # 简易限流（单 IP 滑动窗口），防接口被刷
    _RL = {}
    _RL_LOCK = threading.Lock()
    _RL_LIMIT = 200    # 每个时间窗口内最大请求数
    _RL_WINDOW = 60     # 窗口长度（秒）

    def _client_ip(self):
        # 云平台（Render/Railway/CloudBase）请求经反向代理转发，self.client_address[0]
        # 是代理边缘 IP；取 X-Forwarded-For 首段才是真实访客，限流才不会误伤全体或失效。
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def _rate_ok(self):
        now = time.time()
        ip = self._client_ip()
        with Handler._RL_LOCK:
            # 防内存无限增长：IP 计数过多时整体清空（个人部署流量极低，清零影响可忽略）
            if len(Handler._RL) > 5000:
                Handler._RL.clear()
            buf = Handler._RL.get(ip)
            if buf is None:
                buf = []
                Handler._RL[ip] = buf
            buf[:] = [t for t in buf if now - t < Handler._RL_WINDOW]
            if len(buf) >= Handler._RL_LIMIT:
                return False
            buf.append(now)
        return True

    # ---- 计算结果内存缓存（TTL）----
    # 让同一查询（同基金/同日期）在 TTL 内重复访问秒回，避免每次冷取数。
    # 日内数据 120s 内几乎不变，精度无损。
    _API_CACHE = {}
    _API_CACHE_LOCK = threading.Lock()
    _API_CACHE_TTL = 120  # 秒（单基金 /api/data、/api/validate 日内变化快，缓存 2 分钟）
    _API_CACHE_TTL_RANK = 300  # 秒（排行官方溢价基于已公布净值，日内变化慢，缓存 5 分钟，延长热窗口）

    def _cached(self, key, ttl, producer):
        now = time.time()
        with self._API_CACHE_LOCK:
            hit = self._API_CACHE.get(key)
            if hit and hit[0] > now:
                return hit[1]
        val = producer()  # 在锁外执行重计算，避免阻塞其它请求
        with self._API_CACHE_LOCK:
            self._API_CACHE[key] = (now + ttl, val)
        return val

    def do_GET(self):
        parsed = urlparse(self.path)
        # 接口限流（静态资源与页面不限）
        if parsed.path.startswith("/api/") and not self._rate_ok():
            self._send(429, json.dumps({"error": "请求过于频繁，请稍后再试"}))
            return
        if parsed.path == "/manifest.json":
            self._serve_file("manifest.json", MANIFEST_JSON, "application/manifest+json; charset=utf-8")
            return
        if parsed.path == "/sw.js":
            self._serve_file("sw.js", SW_JS, "application/javascript; charset=utf-8")
            return
        if parsed.path == "/icon.svg":
            self._serve_file("icon.svg", ICON_SVG, "image/svg+xml")
            return
        if parsed.path in ("/", "/index.html"):
            self._send(200, PAGE_HTML, "text/html; charset=utf-8")
            return
        if parsed.path in ("/ranking", "/ranking.html"):
            self._send(200, PAGE2_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/data":
            qs = parse_qs(parsed.query)
            code = qs.get("code", ["162411"])[0]
            if not _valid_code(code):
                self._send(400, json.dumps({"error": "基金代码格式非法，应为 6 位数字"}))
                return
            try:
                days = int(qs.get("days", ["10"])[0])
            except ValueError:
                days = 10
            days = max(3, min(60, days))
            try:
                threshold = float(qs.get("threshold", ["1.5"])[0])
            except ValueError:
                threshold = 1.5
            threshold = max(0.1, min(10.0, threshold))
            start = qs.get("start", [""])[0]
            end = qs.get("end", [""])[0]
            if start and not _valid_date(start):
                start = ""
            if end and not _valid_date(end):
                end = ""
            underlying = qs.get("underlying", [""])[0] or None
            if underlying and not _valid_und(underlying):
                underlying = None
            mode = qs.get("mode", [""])[0] or None
            if mode not in ("auto", "holdings", "index"):
                mode = None
            cache_key = f"data|{code}|{days}|{threshold}|{start}|{end}|{underlying}|{mode}"
            try:
                data = self._cached(cache_key, Handler._API_CACHE_TTL,
                                    lambda: compute(code, days, start, end, underlying, threshold, mode))
                data = dict(data)
                data["error"] = None
                self._send(200, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "code": code}, ensure_ascii=False))
            return
        if parsed.path == "/api/ranking":
            qs = parse_qs(parsed.query)
            date = qs.get("date", [""])[0]
            if date and not _valid_date(date):
                self._send(400, json.dumps({"error": "日期格式非法，应为 YYYY-MM-DD"}))
                return
            if not date:
                date = datetime.now().strftime("%Y-%m-%d")
            codes_raw = qs.get("codes", [""])[0]
            codes = [c.strip() for c in _RE_SEP.split(codes_raw or "") if _valid_code(c.strip())]
            codes = codes[:100]
            if not codes:
                codes = RANKING_WATCHLIST
            try:
                threshold = float(qs.get("threshold", ["1.5"])[0])
            except ValueError:
                threshold = 1.5
            threshold = max(0.1, min(10.0, threshold))
            cache_key = f"rank|{date}|{threshold}|{','.join(codes)}"
            try:
                data = self._cached(cache_key, Handler._API_CACHE_TTL_RANK,
                                    lambda: compute_ranking(codes, date, threshold))
                self._send(200, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "date": date, "codes": codes}, ensure_ascii=False))
            return
        if parsed.path == "/api/csv":
            qs = parse_qs(parsed.query)
            code = qs.get("code", ["162411"])[0]
            if not _valid_code(code):
                self._send(400, json.dumps({"error": "基金代码格式非法，应为 6 位数字"}))
                return
            try:
                days = int(qs.get("days", ["10"])[0])
            except ValueError:
                days = 10
            data = compute(code, days)
            csv_text = build_csv(data["rows"], data["control"], code, data["name"],
                                 oil_gas=data.get("is_oil_gas", False),
                                 use_fx=data.get("use_fx", True))
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8-sig")
            self.send_header("Content-Disposition", f'attachment; filename="arb_{code}.csv"')
            # 与全局安全策略一致：补齐全套响应头，跨域仅放行本地/同源，不再用 * 放行任意站点
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            origin = self.headers.get("Origin")
            if origin and (re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin) or origin == "null"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(csv_text.encode("utf-8-sig"))
            return
        if parsed.path == "/api/validate":
            qs = parse_qs(parsed.query)
            code = qs.get("code", ["162411"])[0]
            if not _valid_code(code):
                self._send(400, json.dumps({"error": "基金代码格式非法，应为 6 位数字"}))
                return
            try:
                days = int(qs.get("days", ["30"])[0])
            except ValueError:
                days = 30
            days = max(5, min(120, days))
            mode = qs.get("mode", [""])[0] or None
            if mode not in ("auto", "holdings", "index"):
                mode = "auto" if code in HOLDINGS_MODE else "index"
            cache_key = f"valid|{code}|{days}|{mode}"
            try:
                data = self._cached(cache_key, Handler._API_CACHE_TTL,
                                    lambda: backtest_nav_estimate(code, days, mode=mode))
                self._send(200, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "code": code}, ensure_ascii=False))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass


def main():
    import os
    # 云部署时读取平台注入的 PORT（如 Render / Railway / CloudBase），本地默认 8000
    env_port = os.environ.get("PORT")
    try:
        port = int(env_port) if env_port else 8000
    except ValueError:
        port = 8000
    # 本地默认只监听回环地址 127.0.0.1（不暴露到局域网）；
    # 云平台由 PORT 环境变量触发对外 0.0.0.0；也可用 HOST 环境变量强制覆盖。
    host = os.environ.get("HOST") or ("0.0.0.0" if env_port else "127.0.0.1")
    httpd = ThreadingHTTPServer((host, port), Handler)
    # 后台校准各标的仓位系数 w（历史回测网格搜索），完成后持久化到 weights_cache.json
    _threading.Thread(target=calibrate_all_weights, daemon=True).start()
    # 加载持仓择优缓存（24h 持久化，避免每次重复抓取 10 只重仓行情）
    load_holdings_choice_cache()
    # 预热 + 周期刷新：启动后先算默认基金与排行填满缓存；之后每 60s 重算一次，
    # 使首页(/api/data 默认 162411)与排行页在实例常驻期间始终命中缓存、秒出。
    # _prewarm_running 防止上一次排行重算未结束时又重叠启动（避免并发猛刷上游被限流）。
    _prewarm_running = {"rank": False}
    def _prewarm_loop():
        while True:
            # 默认基金（快）
            try:
                Handler._API_CACHE[f"data|162411|10|1.5|||None|None"] = (
                    time.time() + Handler._API_CACHE_TTL, compute("162411", 10))
            except Exception:
                pass
            # 排行（重，带重叠保护）
            if not _prewarm_running["rank"]:
                _prewarm_running["rank"] = True
                try:
                    _d = datetime.now().strftime("%Y-%m-%d")
                    Handler._API_CACHE[f"rank|{_d}|1.5|{','.join(RANKING_WATCHLIST)}"] = (
                        time.time() + Handler._API_CACHE_TTL_RANK, compute_ranking(RANKING_WATCHLIST))
                except Exception:
                    pass
                finally:
                    _prewarm_running["rank"] = False
            time.sleep(60)
    _threading.Thread(target=_prewarm_loop, daemon=True).start()
    url = f"http://localhost:{port}"
    print("=" * 60)
    print("  LOF/ETF 套利看板已启动")
    print(f"  在浏览器打开：{url}  (HOST={host} PORT={port})")
    print("  按 Ctrl+C 停止")
    print("=" * 60)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
