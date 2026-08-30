# -*- coding: utf-8 -*-
"""
LOF / ETF 基金套利数据看板（网页交互版）

运行：python fund_arb.py
  -> 自动在本机启动本地服务（默认 http://localhost:8000）
  -> 浏览器打开后，填入基金代码，自动拉取并展示数据

网页功能：
  - 填写基金代码（如 162411）→ 自动刷新
  - 估算净值所用「标的 ETF」按内置基金表自动匹配（如华宝油气→XOP、纳指→QQQ、标普→SPY）
  - 默认近 10 个交易日，日期倒序（最新在顶端）
  - 表格含：汇率、价格、净值、标的收盘、溢价、估算净值、估值溢价、申购状态、限购金额、套利信号

数据源优先级（自动兜底，本机通常全部可用）：
  - 单位净值：东方财富 api.fund.eastmoney.com
  - 场内收盘价：东方财富 push2his -> 腾讯财经
  - 标的收盘：东方财富全球行情 -> 腾讯财经 -> stockanalysis.com
  - USD/CNY 汇率：CFETS 人民币中间价(chinamoney.com.cn) -> frankfurter/新浪即期兜底
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
import collections
from fund_arb_tpl import (COMMON_CSS, PAGE_HTML, PAGE2_HTML, PAGE3_HTML, PAGE4_HTML, PAGE5_HTML, MANIFEST_JSON, ICON_SVG, ICON_PNG_192, ICON_PNG_512, SW_JS)

# 导出表格/图片浮动条（来源：公众号 航城大叔），在线页面统一注入
EXPORT_BAR_HTML = ""
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_bar.html"), encoding="utf-8") as _eb:
        EXPORT_BAR_HTML = _eb.read()
except Exception:
    EXPORT_BAR_HTML = ""


# 界面版本（用于页面展示与 PWA 缓存区分）
VERSION = "V1.3"

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
RANKING_MAX_WORKERS = int(os.environ.get("FUND_ARB_MAX_WORKERS", "8"))  # 提高并行度：44 只基金冷计算/预热更快（东财等上游对并发容忍度高）；可用 FUND_ARB_MAX_WORKERS 覆盖

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
    "160140": _u("SPY"), "164705": {"tx": "hkHSI", "sa": "HSI"}, "501312": _u("QQQ"), "164906": _u("KWEB"),
    "160717": _u("FXI"), "501300": _u("AGG"), "160719": _u("GLD"), "161126": _u("XLV"),
    "161116": _u("GLD"), "161831": _u("FXI"), "160924": {"tx": "hkHSI", "sa": "HSI"}, "161124": {"sa": "HSSI", "hk_sina": True},
    "164701": _u("GLD"), "163208": _u("XOP"), "160216": _u("DBC"), "160416": _u("XOP"),
    "161130": _u("QQQ"), "161127": _u("XBI"),
    # 161226 国投瑞银白银期货：投资上海期货交易所白银期货，用国内白银连续合约 AG0，无需 USD/CNY 换汇。
    "161226": {"sina_futures": "AG0", "sa": "AG0", "use_fx": False},
    "160644": _u("KWEB"),
    "501025": _u("FXI"), "162719": _u("IEO"), "161125": _u("SPY"), "161128": _u("XLK"),
    "501018": _u("USO"), "161129": _u("USO"), "501225": _u("SOXX"),
    "164824": _u("INDA"),
    # ---- 国内 A 股指数型 LOF：用对应宽基/行业指数实时行情做盘中估算 ----
    # 中证/国证指数走腾讯 sz/sh 代码（日 K 已含当日实时值），use_fx=False。
    # 公式自动变为 估算净值 = 上一净值 × (指数今日/指数昨日)，盘中随指数实时变动，
    # 不再退回「抄上一交易日净值」的兜底。w 取 0.98（指数满仓跟踪 + 现金拖累折中）。
    "161725": {"tx": "sz399997", "sa": "399997", "use_fx": False},  # 招商中证白酒 → 中证白酒
    "160632": {"tx": "sz399987", "sa": "399987", "use_fx": False},  # 鹏华酒 → 中证酒
    "160143": {"tx": "sz399006", "sa": "399006", "use_fx": False},  # 南方创业板 → 创业板指
    "161032": {"tx": "sz399998", "sa": "399998", "use_fx": False},  # 富国煤炭 → 中证煤炭
    "160225": {"tx": "sz399976", "sa": "399976", "use_fx": False},  # 国泰新能源 → 中证新能源车
    "160706": {"tx": "sh000300", "sa": "000300", "use_fx": False},  # 嘉实沪深300 → 沪深300
    "160119": {"tx": "sh000905", "sa": "000905", "use_fx": False},  # 南方中证500 → 中证500
    "161726": {"tx": "sz399441", "sa": "399441", "use_fx": False},  # 招商国证生物医药 → 国证生物医药
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
    "HSSI": 0.95,                                            # 恒生综合小型股指数（161124 易方达港小盘，业绩基准 95%×指数 + 5%×活期）
    "AGG": 0.90,                                             # 债券
    # 国内 A 股指数代理（sa=指数代码）：指数满仓 LOF，w 取 0.98
    "399997": 0.98, "399987": 0.98, "399006": 0.98,
    "399998": 0.98, "399976": 0.98, "000300": 0.98, "000905": 0.98, "399441": 0.98,
}

# 按基金代码强制指定 w（覆盖按标的/校准的默认值）。
# 黄金类 w 直接钉死为【最小化 MAE 回测校准值】（已验证优于季报名义权益比 0.9637）：
#   160719 0.884 -> MAE 0.465%  (vs 0.9637 -> 0.486%)
#   161116 0.898 -> MAE 0.253%  (vs 0.9637 -> 0.254%)
#   164701 1.0   -> MAE 0.163%  (vs 0.9637 -> 0.181%)
# 说明：calibrate_fund 对复合标的(黄金)因合成标的数据窗被限制在~30日、样本<40 而返回
# 「无结果」无法自校准，故此处钉死已验证的最优值，保证任意环境都拿到最低估算误差。
FUND_WEIGHT = {
    "160719": 0.884,   # 嘉实黄金（MAE 最小化校准值）
    "161116": 0.898,   # 易方达黄金
    "164701": 1.0,     # 汇添富黄金
    "164705": 0.95,    # 汇添富恒生：改用 HSI 恒生指数本身代理（EWH=MSCI香港错配，MAE 1.05%→0.044%）
    "160924": 0.95,    # 大成恒生：同上，HSI 恒生指数代理
}

# 复合标的：部分基金同时持有【港股 + 美股】同主题资产（如 160644 港美互联），
# 单一代理（KWEB 仅美股）无法覆盖港股那一腿，导致背离交易日误差爆表（±7%）。
# 这里把多个成分代理按权重合成为一条「合成标的序列」，仅用收益率合成（绝对价位无关），
# 与下游 w/lag 公式完全兼容。权重之和应为 1.0；成分 und 格式同 UNDERLYING_MAP。
COMPOSITE_UNDERLYING = {
    # 黄金类 LOF（160719 嘉实黄金 / 161116 易方达黄金 / 164701 汇添富黄金）：
    # 持有 GLD（美股黄金 ETF）+ 欧洲黄金 ETC；以 160719 为例，2026Q2 季报权重
    # GLD 52.6% + GLD-EU 47.4%。估值与微信文章（东哥/楼二爷）口径一致：
    #   估算净值 = 昨净值 × (1 + w × ((GLD比×52.6% + GLD-EU比×47.4%) × CNYt/CNYt-1 − 1))
    # GLD-EU 不是某只欧洲 ETF，而是【同一只 GLD 在美东 11:30（北京时间约 23:30）
    # 的盘中快照】——文章用东方财富 GLD 小时线(klt=60)取每天 23:30 那根 bar 收盘价验证，
    # 与 GLD 偏差<0.5%。因此欧洲腿直接由 GLD 小时线派生（gld_eu=True），无需任何欧金源。
    # 东财小时线取不到时本腿退化、复合仅剩 GLD 腿（权重归一到 1.0），结果≈纯 GLD。
    "160719": [
        {"sa": "GLD", "w": 0.526},
        {"gld_eu": True, "w": 0.474},
    ],
    "161116": [
        {"sa": "GLD", "w": 0.526},
        {"gld_eu": True, "w": 0.474},
    ],
    "164701": [
        {"sa": "GLD", "w": 0.526},
        {"gld_eu": True, "w": 0.474},
    ],
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
    # 160216 国泰大宗商品(QDII-LOF)：持有 GLD(黄金ETF)+SLV(白银ETF)+USO(原油ETF) 多资产篮子，
    # 单一 DBC(广谱商品ETF) 代理与「黄金+白银+原油」真实持仓结构偏离较大，是估算误差来源。
    # 复合篮子对标参考站 palmmicro 披露的 160216 仓位校准值（GLD 110.903 / SLV 11.111 / USO 10.656），
    # 归一化为权重 GLD 0.836 / SLV 0.084 / USO 0.080。该权重为参考站标定口径，建议后续用基金季报
    # 真实持仓或历史回测再校准。同时见 HOLDINGS_MODE["160216"]="auto"：能抓到真实十大持仓时用真实权重、
    # 并经 choose_mode 按 MAE 择优，失败回退到本复合篮子。
    "160216": [
        {"sa": "GLD", "w": 0.836},
        {"sa": "SLV", "w": 0.084},
        {"sa": "USO", "w": 0.080},
    ],
    # 160723 嘉实原油(QDII-LOF)：业绩基准=WTI原油价格，主要投资于跟踪原油价格的公募基金(含ETF)。
    # 采用参考站(haoetf)口径的「原油ETF篮子」：CRUD/USO/OILK/BNO/BRNT 等权加权，
    # 截图实证估值误差 0.01~0.21%，远优于原单一 USO 映射（USO 单标有 contango 展期损耗偏离）。
    # 权重为截图披露值(合计~93%)，代码第659行按 total_w 自动归一，无需手动归一到 1.0；
    # 第6只ETF截图未披露，暂略。复合成分强制 w=1.0/lag=1（compute/compute_one_rank 已对
    # COMPOSITE_UNDERLYING 统一处理），不再乘单一标的 weight_for/lag_for，避免估值失真。
    # 注：CRUD/OILK/BRNT 为相对小众美股ETF，若价格源取不到，_composite_xop_uncached 会
    # try/except 跳过该成分、剩余成分仍合成，不影响运行（仅略偏）。
    "160723": [
        {"sa": "CRUD", "w": 0.1887},
        {"sa": "USO",  "w": 0.1878},
        {"sa": "OILK", "w": 0.1854},
        {"sa": "BNO",  "w": 0.1837},
        {"sa": "BRNT", "w": 0.1855},
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
# 计算固定窗口：估算/校准/择优一律用 30 交易日，保证误差稳定；
# 界面「显示近 N 日」只控制表格展示行数，不影响计算精度。
CALC_DAYS = 30

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
        if not (und or {}).get("hk_sina"):
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
    if code and code in FUND_WEIGHT:
        return FUND_WEIGHT[code]
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


# ---------------------------------------------------------------------------
# 国内指数 / 行业 LOF：用「跟踪指数日内涨跌」估算当日净值（对标 haoetf 实时估值）
# 背景：原逻辑对无 QDII 标的的国内基金，est_nav 直接回退成官方净值，导致
#       「估算净值」列与「净值」列恒等（用户反馈「估算净值=前一天净值」）。
#       对指数 / 行业 LOF，其净值日内变动≈跟踪指数变动，故：
#           est_nav = 官方净值 × (1 + 指数日内涨跌% × w)，w 默认 1.0（指数基金完全复制）
# 取数：东财 push2 批量接口（与行业轮动 sector_live 同源），按「指数名称含预期关键词」
#       确认 secid 命中，名称不符 / 缺数据则回退官方净值，绝不给出错误估算。
# 说明：主动 / 混合 / FOF 类 LOF 无单一跟踪指数，est_nav 回退官方净值本就合理（其净值
#       由持仓 EOD 计算、次日披露，盘中没有单一可代理的日内标的）。
# ---------------------------------------------------------------------------
DOMESTIC_INDEX_MAP = {
    # 基金代码: (东财指数代码, 名称命中关键词, 仓位系数 w)
    "160225": ("399976", "新能源车", 1.0),   # 国泰国证新能源汽车
    "160221": ("399395", "有色金属", 1.0),   # 国泰国证有色金属
    "160626": ("000935", "信息技术", 1.0),   # 鹏华中证信息技术
    "160629": ("399971", "传媒", 1.0),       # 鹏华中证传媒
    "160628": ("399965", "地产", 1.0),       # 鹏华中证800地产
    "160630": ("399973", "国防", 1.0),       # 鹏华中证国防
    "160625": ("399966", "保险", 1.0),       # 鹏华中证800证券保险
    "160631": ("399986", "银行", 1.0),       # 鹏华中证银行
    "160637": ("399006", "创业板", 1.0),     # 鹏华创业板
    "160633": ("399975", "证券公司", 1.0),   # 鹏华中证全指证券公司
    "161024": ("399967", "军工", 1.0),       # 富国中证军工
    "161032": ("399998", "煤炭", 1.0),       # 富国中证煤炭
    "161026": ("399974", "国企改革", 1.0),   # 富国中证国有企业改革
    "161029": ("399986", "银行", 1.0),       # 富国中证银行
    "161028": ("399976", "新能源车", 1.0),   # 富国中证新能源汽车
    "161025": ("399970", "移动互联网", 1.0), # 富国中证移动互联网
    "161037": ("930599", "高端制造", 1.0),   # 富国中证高端制造增强
    "161039": ("000852", "中证1000", 1.0),  # 富国中证1000增强
    "161122": ("399803", "生物科技", 1.0),   # 易方达中证万得生物科技
    "161725": ("399997", "白酒", 1.0),       # 招商中证白酒
    "161631": ("930713", "人工智能", 1.0),   # 融通人工智能
    "161812": ("399330", "深证100", 1.0),    # 银华深证100
    "161724": ("399998", "煤炭", 1.0),       # 招商中证煤炭等权
    "161720": ("399975", "证券公司", 1.0),   # 招商中证全指证券公司
    "161227": ("399330", "深证100", 1.0),    # 国投瑞银深证100
    "163115": ("399967", "军工", 1.0),       # 申万菱信中证军工
    "163113": ("399707", "申万证券", 1.0),   # 申万菱信中证申万证券行业
    "163116": ("399814", "电子", 1.0),       # 申万中证申万电子行业
    "163118": ("399809", "医药", 1.0),       # 申万菱信中证申万医药生物
    "165525": ("399995", "基建", 1.0),       # 中信保诚中证基建工程
    "501005": ("930707", "精准医疗", 1.0),   # 汇添富中证精准医疗
    "501009": ("930743", "生物科技", 1.0),   # 汇添富中证生物科技A
    "501010": ("930743", "生物科技", 1.0),   # 汇添富中证生物科技C
    "501016": ("399707", "申万证券", 1.0),   # 国泰中证申万证券行业
    "501019": ("399368", "航天军工", 1.0),   # 国泰国证航天军工
    "501030": ("399806", "环境治理", 1.0),   # 汇添富中证环境治理
    "501043": ("000300", "沪深300", 1.0),    # 汇添富沪深300
    "501050": ("000016", "上证50", 1.0),     # 华夏上证50AH优选
    "501057": ("930997", "新能源汽车", 1.0), # 汇添富中证新能源汽车产业A
    "501058": ("930997", "新能源汽车", 1.0), # 汇添富中证新能源汽车产业C
    "501059": ("000824", "国企红利", 1.0),   # 西部利得国企红利增强
    "502000": ("000905", "中证500", 1.0),    # 西部利得中证500增强
    "502010": ("399975", "证券公司", 1.0),   # 易方达中证全指证券公司
    "502013": ("399991", "一带一路", 1.0),   # 长盛中证申万一带一路
    "502048": ("000016", "上证50", 1.0),     # 易方达上证50
    "502023": ("399440", "钢铁", 1.0),       # 鹏华国证钢铁行业
    "502053": ("399975", "证券公司", 1.0),   # 长盛中证证券公司
    # 其余有明确跟踪指数的非「指数」命名 LOF
    "160222": ("399396", "食品饮料", 1.0),   # 国泰国证食品饮料
    "160632": ("399987", "酒", 1.0),         # 鹏华酒
    "160706": ("000300", "沪深300", 1.0),    # 嘉实沪深300ETF联接
    "161033": ("930721", "智能汽车", 1.0),   # 富国中证智能汽车
}

_IDX_CHG_CACHE = {}          # index_code -> (chg_pct, ts)
_IDX_CHG_LOCK = _threading.Lock()
_IDX_CHG_TTL = 60            # 同一指数 60s 内复用（盘中变化快，短缓存）


def _idx_push2_changes(idx_meta):
    """批量取指数日内涨跌(%)。idx_meta: {index_code: (命中关键词, w)}。
    返回 {index_code: chg_pct}。按 f12(代码) 精确命中 index_code（东财指数名常被缩写，
    故不依赖名称关键词，直接信任代码映射）；对每个代码同时试 1.(SH)/0.(SZ) 两种前缀。
    分块查询（每块≤20）避免 secids 过多被接口截断；多镜像轮询+重试。"""
    import random as _random
    if not idx_meta:
        return {}
    codes = list(idx_meta.keys())
    hosts = ["%d.push2.eastmoney.com" % _random.randint(1, 99) for _ in range(8)]
    hosts += ["push2.eastmoney.com", "push2delay.eastmoney.com"]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    out = {}
    for i in range(0, len(codes), 20):
        chunk = codes[i:i + 20]
        secids = []
        for ic in chunk:
            secids.append("1." + ic)
            secids.append("0." + ic)
        for host in hosts:
            try:
                url = ("https://%s/api/qt/ulist.np/get?fields=%s&secids=%s"
                       "&ut=fa5fd1943c7b386f172d6893bfba10b&_=%d" % (
                           host, "f3,f12,f14", ",".join(secids), int(time.time() * 1000)))
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
                    "Accept": "application/json, text/plain, */*"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
                diff = ((j or {}).get("data") or {}).get("diff") or []
                for x in diff:
                    code = (x.get("f12") or "").strip()
                    chg = x.get("f3")
                    if chg is not None and code in idx_meta:
                        out[code] = round(chg / 100.0, 4)
            except Exception as e:
                print(f"    [指数涨跌] {host} 取数失败: {e}")
                continue
    return out


def get_index_chg(index_code):
    """单只指数日内涨跌(%)，带缓存；失败返回 None（调用方回退官方净值）。"""
    with _IDX_CHG_LOCK:
        c = _IDX_CHG_CACHE.get(index_code)
        if c and (time.time() - c[1]) < _IDX_CHG_TTL:
            return c[0]
    meta = {index_code: (DOMESTIC_INDEX_MAP.get(index_code) or ("", 1.0))[0:2]}
    chg = _idx_push2_changes(meta).get(index_code)
    with _IDX_CHG_LOCK:
        _IDX_CHG_CACHE[index_code] = (chg, time.time())
    return chg


def get_index_chg_batch(idx_meta):
    """top 扫描一次性批量取所有候选指数日内涨跌。返回 {index_code: chg_pct}。"""
    if not idx_meta:
        return {}
    return _idx_push2_changes(idx_meta)


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


COMPOSITE_CACHE = {}          # code -> (blend, label, ts) 复合标的合成结果缓存
COMPOSITE_CACHE_TTL = 600
COMPOSITE_BUILD_LOCK = threading.Lock()
_COMPOSITE_BUILDING = {}        # code -> Event 单飞锁


def _build_composite_xop(code, n):
    """对港美双市场基金，将多个成分代理按权重合成一条序列。
    返回 (date->合成价, 来源标签) 或 None。绝对价位无关，下游 w/lag 公式兼容。
    带 TTL 缓存 + 单飞锁：每次网页1 查询同一基金只重建一次，并发请求复用同一结果。"""
    cached = COMPOSITE_CACHE.get(code)
    if cached and (time.time() - cached[2]) < COMPOSITE_CACHE_TTL:
        return cached[0], cached[1]
    with COMPOSITE_BUILD_LOCK:
        ev = _COMPOSITE_BUILDING.get(code)
        if ev is not None:
            holder = True
        else:
            ev = threading.Event()
            _COMPOSITE_BUILDING[code] = ev
            holder = False
    if holder:
        ev.wait(40)
        cached = COMPOSITE_CACHE.get(code)
        if cached:
            return cached[0], cached[1]
    try:
        res = _composite_xop_uncached(code, n)
    finally:
        with COMPOSITE_BUILD_LOCK:
            _COMPOSITE_BUILDING.pop(code, None)
        ev.set()
    if res:
        COMPOSITE_CACHE[code] = (res[0], res[1], time.time())
    return res


def _composite_xop_uncached(code, n):
    """实际合成（无缓存），供 _build_composite_xop 单飞调用。"""
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
            elif c.get("gld_eu"):
                # 黄金欧洲腿：GLD 在美东 11:30(北京约23:30)的快照序列，单位同 GLD
                m = fetch_gld_eu_series(n)
                if m:
                    merge_seed_xop(m)
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
    """取标的序列：若 code 配置为复合标的则返回合成序列，否则走原单标的逻辑。
    无标的（und 为 None）时返回空序列，供下游按普通基金处理。"""
    if code and code in COMPOSITE_UNDERLYING:
        res = _build_composite_xop(code, n)
        if res:
            return res
    if und is None:
        return {}, "无标的"
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
_HTTP_CACHE = collections.OrderedDict()   # 有序字典，超出上限时淘汰最旧条目（近似 LRU）
_HTTP_CACHE_LOCK = threading.Lock()
_HTTP_CACHE_TTL = 90  # 秒
_MAX_HTTP_CACHE = int(os.environ.get("FUND_ARB_HTTP_CACHE_MAX", "2000"))  # 单进程缓存上限，防长稳运行内存增长

# ---- 数据源熔断器 ----
# 腾讯K线/东财K线等上游不稳定时（如腾讯持续501），每只基金都要先打一次坏源
# 再兜底，44只×1.1s/只累计7-8s。熔断器在连续失败3次后ban 60s，期间直接跳过
# 该源走兜底，单只从1.1s降到0.15s。源恢复后ban期过期自动重试。
_CB_FAIL_THRESH = 3
_CB_BAN_SECS = 60
_TX_KLINE_CB = {"name": "腾讯K线", "fails": 0, "ban_until": 0.0, "lock": threading.Lock()}
_EM_KLINE_CB = {"name": "东财K线", "fails": 0, "ban_until": 0.0, "lock": threading.Lock()}


def _cb_banned(cb):
    return time.time() < cb["ban_until"]


def _cb_fail(cb):
    with cb["lock"]:
        cb["fails"] += 1
        if cb["fails"] >= _CB_FAIL_THRESH and cb["ban_until"] < time.time():
            cb["ban_until"] = time.time() + _CB_BAN_SECS
            print(f"    [熔断] {cb['name']} 连续失败 {cb['fails']} 次，熔断 {_CB_BAN_SECS}s")


def _cb_ok(cb):
    with cb["lock"]:
        if cb["fails"] or cb["ban_until"]:
            cb["fails"] = 0
            cb["ban_until"] = 0.0


def bj_now():
    """北京时间（UTC+8，中国不实行夏令时）。返回 naive datetime 表示北京墙钟。

    注意：绝不可用 datetime.fromtimestamp(time.time() + 8 * 3600)——fromtimestamp
    会按「进程本地时区」再转换一次，本机为 UTC+8 时会双加 8 小时（服务器为 UTC 时恰好
    正确，于是本地与线上结论不一致，极难排查）。实测本机曾因此把 08-30 23:57 算成
    08-31 07:57，使 _last_trading_day() 返回「未来」的 08-31。统一用 UTC 基准加 8 小时。
    """
    return (datetime.utcnow() + timedelta(hours=8))


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
                if val is None:
                    raise ValueError("上游返回 null（无数据）")
                with _HTTP_CACHE_LOCK:
                    _HTTP_CACHE[key] = (now + _HTTP_CACHE_TTL, val)
                    if len(_HTTP_CACHE) > _MAX_HTTP_CACHE:
                        _HTTP_CACHE.popitem(last=False)
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
                    if len(_HTTP_CACHE) > _MAX_HTTP_CACHE:
                        _HTTP_CACHE.popitem(last=False)
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


def fetch_kline_eastmoney(secid, n=20, klt=101):
    if _cb_banned(_EM_KLINE_CB):
        raise RuntimeError("东财K线熔断中")
    fields2 = "f51,f52,f53,f54,f55,f56,f57,f58"
    hosts = ["https://push2his.eastmoney.com", "https://push2delay.eastmoney.com"]
    last_err = None
    for host in hosts:
        try:
            url = (f"{host}/api/qt/stock/kline/get?secid={secid}"
                   f"&fields1=f1,f2,f3,f4,f5,f6&fields2={fields2}"
                   f"&klt={klt}&fqt=0&end=20500101&lmt={n}"
                   f"&ut=fa5fd1943c7b386f172d6893dbfba10b")
            data = http_get_json(url, referer="https://quote.eastmoney.com/", timeout=8, retries=1)
            if not isinstance(data, dict):
                raise ValueError("东财返回非预期格式")
            klines = (data.get("data") or {}).get("klines", [])
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
            _cb_ok(_EM_KLINE_CB)
            return out, f"东财({host.split('.')[0]})"
        except Exception as e:
            last_err = e
    _cb_fail(_EM_KLINE_CB)
    raise last_err or Exception("东财 K 线无数据")


# ---------------------------------------------------------------------------
# GLD-EU：同一只 GLD 在美东 11:30（北京时间约 23:30）的盘中快照序列
# ---------------------------------------------------------------------------
# 微信文章（东哥/楼二爷）验证：GLD-EU 并不是某只欧洲上市 ETF，而是【同一只 GLD
# 锁定在美东 11:30（欧洲休市前后）时刻的价格】。用东方财富 GLD 小时线(klt=60)取每天
# 北京时间 23:30 那一根 bar 的收盘价，与真实值五日吻合在 ±0.03% 以内。因此欧洲腿
# 直接由 GLD 小时线派生，无需任何欧洲黄金数据源。取不到时返回 {}（复合退化为纯 GLD）。
GLD_EU_CACHE = {}
GLD_EU_TTL = 3600

def _extract_2330(klines):
    """klines: list of (datetime_str, close)。每天取最接近北京时间 23:30 的那根 bar。
    允许 00:30 近似（冬令时美东 11:30 = 北京 00:30）。返回 {日期: 收盘价}。"""
    by_day = {}
    for ts, close in klines:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        except Exception:
            continue
        day = dt.strftime("%Y-%m-%d")
        hm = dt.hour * 60 + dt.minute
        if not (dt.hour >= 21 or dt.hour <= 4):   # 只看美股盘中和盘后时段(北京晚间)
            continue
        dist = abs(hm - (23 * 60 + 30))
        cur = by_day.get(day)
        if cur is None or dist < cur[1]:
            by_day[day] = (close, dist)
    return {d: v[0] for d, v in by_day.items()}

def fetch_gld_eu_series(n=400):
    """取 GLD-EU 序列（GLD 在美东 11:30 的快照），单位与 GLD 一致(USD)。
    优先东财小时线(klt=60，试多个 GLD secid)，取不到返回 {}。"""
    with UND_LOCK:
        c = GLD_EU_CACHE.get("gld_eu")
        if c and (time.time() - c[1]) < GLD_EU_TTL:
            return c[0]
    series = {}
    for secid in ["107.GLD", "105.GLD", "106.GLD", "100.GLD"]:
        try:
            kl = fetch_kline_eastmoney(secid, max(n, 80), klt=60)
        except Exception:
            kl = None
        if kl:
            series = _extract_2330(kl[0])
            if series:
                break
    with UND_LOCK:
        GLD_EU_CACHE["gld_eu"] = (series, time.time())
    if series:
        print(f"    [GLD-EU] 东财小时线派生 {len(series)} 天（美东11:30快照）")
    else:
        print("    [GLD-EU] 东财小时线不可用，复合退化为纯 GLD")
    return series


def fetch_kline_tencent(symbol, n=20):
    if _cb_banned(_TX_KLINE_CB):
        raise RuntimeError("腾讯K线熔断中")
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={symbol},day,,,{n},qfq")
    try:
        data = http_get_json(url, retries=1)
    except Exception as e:
        _cb_fail(_TX_KLINE_CB)
        raise
    if not isinstance(data, dict):
        _cb_fail(_TX_KLINE_CB)
        return []
    node = (data.get("data") or {}).get(symbol)
    if not node:
        _cb_fail(_TX_KLINE_CB)
        return []
    arr = node.get("qfqday") or node.get("day") or []
    out = []
    for row in arr:
        try:
            out.append((row[0], float(row[2])))
        except (IndexError, ValueError):
            pass
    out.sort()
    _cb_ok(_TX_KLINE_CB)
    return out


def fetch_kline_sina(symbol, n=25):
    """新浪财经 K 线（LOF/ETF 场内价格备用源）。symbol 形如 sz164705 / shXXXXXX。"""
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={n}")
    try:
        data = http_get_json(url, referer="https://finance.sina.com.cn/", timeout=8, retries=2)
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


def fetch_hk_index_sina(symbol="HSSI", n=5):
    """新浪港股指数日 K（hq.sinajs.cn 实时）。symbol 如 HSSI（恒生综合小型股指数）。
    新浪港股指数实时仅含「现价 + 昨收」两个点，据此构造 {上一自然日: 昨收, 今日: 现价}，
    供下游 build_rows 以 T-1 官方净值锚点估算当日净值（与 164705/160924 用 hkHSI 思路一致，
    但直接用恒生综合小型股指数本身，成分完全匹配 161124 易方达港小盘，替代错配的 EWH）。
    返回 [(date, price), ...] 按日期升序；失败返回 []。"""
    sym = "hk" + symbol.upper()
    url = "https://hq.sinajs.cn/list=" + sym
    try:
        txt = http_get_text(url, referer="https://finance.sina.com.cn/", timeout=10, retries=2, encoding="gbk")
    except Exception as e:
        print(f"    [港股指数] {sym} 实时失败: {e}")
        return []
    m = re.search(r'="([^"]*)"', txt)
    if not m:
        return []
    parts = m.group(1).split(",")
    if len(parts) < 9:
        return []
    try:
        # 新浪港股指数格式: [0]代码 [1]中文名 [2]今开 [3]昨收 [4]最高 [5]最低 [6]现价 [7]涨跌额 [8]涨跌幅
        # 实测对照东财 124.HSSI: f43=现价(1333.63)=parts[6], f60=昨收(1316.73)=parts[3]
        price = float(parts[6])       # 现价
        prev = float(parts[3])        # 昨收
    except (ValueError, IndexError):
        return []
    if price <= 0 or prev <= 0:
        return []
    # 日期键用「UTC 安全」的北京时间（bj_now 依赖进程时区，本地 UTC+8 会双加 8h）
    bj = datetime.utcnow() + timedelta(hours=8)
    today = bj.strftime("%Y-%m-%d")
    yday = (bj - timedelta(days=1)).strftime("%Y-%m-%d")
    return [(yday, prev), (today, price)]


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
    自动向下一个源回退，避免看板出现数据断层。被熔断的源直接跳过。"""
    sources = []
    if not _cb_banned(_EM_KLINE_CB):
        sources.append(("东财", lambda: fetch_kline_eastmoney(em_sec, n)))
    sources.append(("新浪财经", lambda: (fetch_kline_sina(tx_sym, n), "新浪财经")))
    if not _cb_banned(_TX_KLINE_CB):
        sources.append(("腾讯财经", lambda: (fetch_kline_tencent(tx_sym, n), "腾讯财经")))
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
    # 所有价格源均不可用（如场外基金无场内价、上游限流）：返回空序列，
    # 由下游用净值日期兜底展示，避免整个查询崩溃。
    return [], "无数据"


def fetch_price_tencent(tx_sym, n=15):
    """场内历史价：腾讯K线(主) → 新浪K线(兜底)。单源 501/限频时自动切换，避免网页2整页打不开。
    腾讯被熔断时直接走新浪，省去每只1.1s的白等。"""
    if not _cb_banned(_TX_KLINE_CB):
        try:
            r = fetch_kline_tencent(tx_sym, n)
            if r:
                return r, "腾讯财经"
        except Exception as e:
            url = getattr(e, "url", "")
            print(f"    [价格] 腾讯K线失败({tx_sym}) {url}: {e}")
    else:
        print(f"    [价格] 腾讯K线熔断中，直接走新浪({tx_sym})")
    print(f"    [价格] 改用新浪K线({tx_sym})")
    try:
        s = fetch_kline_sina(tx_sym, n)
        if s:
            return s, "新浪财经"
    except Exception as e:
        url = getattr(e, "url", "")
        print(f"    [价格] 新浪K线失败({tx_sym}) {url}: {e}")
    raise RuntimeError("价格获取失败: 腾讯与新浪均无数据")


def fetch_underlying_stockanalysis(code="XOP", n=25):
    url = f"https://stockanalysis.com/api/symbol/e/{code}/history?range=6M&period=Daily"
    # 冷路径兜底：原 timeout=15×retries=3（单只重仓最坏 45s）会拖垮持仓估算；
    # 降到 8×2（最坏 16s），且上游响应已被 _HTTP_CACHE 缓存 90s，重复请求秒回。
    data = http_get_json(url, timeout=8, retries=2)
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
    # 新浪港股指数（恒生综合小型股指数 HSSI 等）：实时现价+昨收两日序列，
    # 直接用指数本身做代理（161124 易方达港小盘），替代 EWH 成分错配。
    hk_sina = (und or {}).get("hk_sina")
    if hk_sina:
        try:
            r = fetch_hk_index_sina(hk_sina if isinstance(hk_sina, str) else "HSSI", n)
            if r:
                results.append((r, "新浪港股指数"))
        except Exception as e:
            print(f"    [兜底] 新浪港股指数标的失败：{e}")
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


def fetch_fx_cfets(start, end):
    """人民币对美元中间价（CFETS / 中国货币网，央行授权发布，LOF 估值招募书规定口径）。
    数据源：chinamoney.com.cn CcprHisNew 接口；返回 [(date, 中间价), ...]。"""
    import urllib.request as _ur
    url = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.chinamoney.com.cn/chinese/bkccpr/",
        "Origin": "https://www.chinamoney.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }
    body = ("startDate=%s&endDate=%s&currency=USD/CNY&pageNum=1&pageSize=400"
            % (start, end)).encode("utf-8")
    req = _ur.Request(url, data=body, headers=headers, method="POST")
    with _ur.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    records = (data.get("records") or []) if isinstance(data, dict) else []
    out = []
    for rec in records:
        d = rec.get("date")
        vals = rec.get("values")
        if isinstance(vals, list) and vals:
            try:
                out.append((d, float(vals[0])))
            except (TypeError, ValueError):
                pass
        elif isinstance(rec.get("rate"), (int, float, str)):
            try:
                out.append((d, float(rec["rate"])))
            except (TypeError, ValueError):
                pass
    out.sort()
    return out


FX_FETCH_LOCK = _threading.Lock()   # 单飞：避免并行估值的多个 worker 同时重抓汇率（惊群）

def fetch_fx(days=400):
    """获取 USD/CNY 汇率历史。主源为 CFETS 人民币中间价（央行口径），失败再退回
    frankfurter(ECB) + 新浪即期兜底；结果缓存 1 小时。days 控制回溯窗口（校准需较长）。"""
    global FX_CACHE, FX_CACHE_TS
    with FX_FETCH_LOCK:
        if FX_CACHE and (time.time() - FX_CACHE_TS) < 3600:
            return FX_CACHE
        today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    # 主源：CFETS 人民币中间价（央行口径，招募书规定）
    try:
        rows = fetch_fx_cfets(start, today)
        if rows:
            out.update(dict(rows))
            print(f"    [汇率] CFETS 中间价取到 {len(rows)} 天")
    except Exception as e:
        print(f"    [兜底] CFETS 中间价失败：{e}")
    # 兜底：frankfurter(ECB) + 新浪即期（非中间价，仅主源不可用时）
    if not out:
        try:
            rows = fetch_fx_frankfurter(start, today)
            out.update(dict(rows))
            if rows:
                print(f"    [汇率] frankfurter 取到 {len(rows)} 天")
        except Exception as e:
            print(f"    [兜底] frankfurter 汇率失败：{e}")
    try:
        latest = fetch_fx_sina_latest()
        if latest is not None and today not in out:
            out[today] = latest
            print(f"    [汇率] 新浪财经最新 USD/CNY = {latest:.4f}（兜底即期）")
    except Exception as e:
        print(f"    [兜底] 新浪财经汇率失败：{e}")
    if not out:
        out.update(SEED_FX)
        print("    [汇率] 使用内置 seed 数据兜底")
        FX_CACHE = out
        FX_CACHE_TS = time.time()
        return out
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
    # 160216 国泰大宗商品：多资产(QDII-LOF)，单一 DBC 代理误差大。
    # 自动择优：能抓到真实十大持仓(GLD/SLV/USO…)时用真实权重篮子，否则回退复合标的(GLD+SLV+USO)。
    "160216": "auto",
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

_HOLDINGS_BUILD_LOCK = threading.Lock()
_HOLDINGS_BUILDING = {}       # code -> Event 单飞锁：并发请求同一基金持仓指数只构建一次


def build_holdings_index(code, n=60):
    """合成持仓收益指数（date->价，已折入 USD/HKD→CNY 换汇）。返回 (index_map, meta) 或 (None, {error})。
    带 TTL 缓存 + 单飞锁：并发请求同一基金只构建一次，其余等待复用结果。"""
    cached = HOLDINGS_INDEX_CACHE.get(code)
    if cached and (time.time() - cached[2]) < HOLDINGS_INDEX_TTL:
        return cached[0], cached[1]
    with _HOLDINGS_BUILD_LOCK:
        ev = _HOLDINGS_BUILDING.get(code)
        if ev is not None:
            holder = True
        else:
            ev = threading.Event()
            _HOLDINGS_BUILDING[code] = ev
            holder = False
    if holder:
        ev.wait(40)
        cached = HOLDINGS_INDEX_CACHE.get(code)
        if cached:
            return cached[0], cached[1]
    try:
        res = _build_holdings_index_uncached(code, n)
        # 构建完成后写回 TTL 缓存：既让并发等待者命中，也保证后续请求直接秒回
        if res and res[0]:
            HOLDINGS_INDEX_CACHE[code] = (res[0], res[1], time.time())
        return res
    finally:
        with _HOLDINGS_BUILD_LOCK:
            _HOLDINGS_BUILDING.pop(code, None)
        ev.set()


def _build_holdings_index_uncached(code, n=60):
    """实际合成（无缓存），供 build_holdings_index 单飞调用。"""
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

def holdings_backtest(code, days=30, fx_map=None):
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

def choose_mode(code, days=30):
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


# ---- 基金元信息短期缓存（per-code，TTL 默认 600s）----
# fetch_fund_name/control/info 为同基金反复取（排行/全市场扫描/枢轴预暖多次触发），
# 加一层进程内短缓存避免重复打东财 fundf10；与 _HTTP_CACHE 解耦，跨扫描复用。
_FINFO_CACHE = {}            # (func, code) -> (ts, value)
_FINFO_LOCK = threading.Lock()
_FINFO_TTL = int(os.environ.get("FUND_ARB_FINFO_TTL", "600"))


def _cached_finfo(func_name, code, producer):
    key = (func_name, code)
    now = time.time()
    with _FINFO_LOCK:
        e = _FINFO_CACHE.get(key)
        if e and (now - e[0]) < _FINFO_TTL:
            return e[1]
    val = producer()
    with _FINFO_LOCK:
        _FINFO_CACHE[key] = (now, val)
    return val


def fetch_fund_name(code, retries=2):
    return _cached_finfo("name", code, lambda: _fetch_fund_name_raw(code, retries))


def _fetch_fund_name_raw(code, retries=2):
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
    return _cached_finfo("control", code, lambda: _fetch_fund_control_raw(code, retries))


def _fetch_fund_control_raw(code, retries=3):
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
    return _cached_finfo("info", code, lambda: _fetch_fund_info_raw(code, retries))


def _fetch_fund_info_raw(code, retries=2):
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


# 申赎通道是否对个人投资者开放（用于套利信号与统计）
# 说明：ETF/部分封基「场内交易」只有二级市场买卖，无个人现金申赎，
#       无法做「申购→卖出」或「买入→赎回」套利，只能赚价差。
SUBSCRIBE_OPEN = ("开放申购", "限大额申购")   # 可现金申购（限大额仅受每日上限约束）
REDEEM_OPEN = ("开放赎回",)                   # 可赎回

# 纯债(纯债券)LOF 细分类型：不参与套利计算与统计（网页3剔除）。
# 来源：东财 fundcode_search.js 的基金类型字段(type)，细分到「债券型-xxx / QDII-纯债 / 指数型-固收」。
# 注意：债券型-混合一级 / 混合二级（含少量权益）、混合型-偏债、QDII-混合债 不算纯债，仍参与套利。
PURE_BOND_TYPES = ("债券型-长债", "债券型-中短债", "债券型-利率债", "债券型-信用债",
                   "QDII-纯债", "指数型-固收")

# 非债基（网页3 用户硬条件）：在 PURE_BOND_TYPES 纯债之上，进一步剔除所有含债/固收基金。
# 规则：类型名含「债」字（债券型-*、混合型-偏债、QDII-混合债 等）一律剔除；
#       另显式剔除指数型-固收 / 指数型-债券 这类不含「债」字的固定收益品种。
def is_bond_fund(ftype):
    return ("债" in (ftype or "")) or (ftype in ("指数型-固收", "指数型-债券"))


def signal_for_premium(premium, threshold=THRESHOLD, subscribe_status="", redeem_status=""):
    """套利信号：综合溢价方向与申赎通道，避免「场内交易/暂停申购」却提示「可申购套利」。

    - 溢价 且 可申购(开放/限大额) → 溢价·可申购套利（可操作）
    - 溢价 但 不可申购(场内交易/暂停申购/封闭/未知) → 溢价·仅场内（仅能卖已持仓，非套利）
    - 折价 且 可赎回 → 折价·可赎回套利（可操作）
    - 折价 但 不可赎回 → 折价·仅场内
    """
    if premium is None:
        return "—", ""
    if premium > threshold:
        if subscribe_status in SUBSCRIBE_OPEN:
            return "溢价·可申购套利", "premium"
        return "溢价·仅场内", "premium_lock"
    if premium < -threshold:
        if redeem_status in REDEEM_OPEN:
            return "折价·可赎回套利", "discount"
        return "折价·仅场内", "discount_lock"
    return "平价(观察)", "flat"


def merge_seed_xop(xop_map):
    """seed 兜底：把历史校准日期的标的价补进缺失日。仅用于「在线接口整体失败」时，
    对 hk_sina（新浪港股指数实时两日序列）不适用——seed 是 7 月的旧值，与 HSSI 量级
    完全不同（1316 vs 174），混入会污染 build_rows 的 P 比值，导致估算荒谬。"""
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


def build_rows(price_map, nav_map, xop_map, fx_map, days=30, start="", end="",
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
    # 价格缺失（如场外基金无场内价/上游限流）时，用净值日期兜底，保证有行可看
    all_dates = sorted(price_map.keys()) or nav_dates
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


def compute(code, days=30, display_days=None, start="", end="", underlying=None, threshold=THRESHOLD, mode=None):
    """核心计算：返回可直接序列化为 JSON 的字典。
    days: 计算窗口（估算/校准/择优用），固定 CALC_DAYS=30；
    display_days: 界面表格展示行数（仅切片，不参与计算）；
    mode: 估值模式覆盖（"auto"/"holdings"/"index"）；None 时取 HOLDINGS_MODE 配置。"""
    calc_days = CALC_DAYS
    if display_days is None:
        display_days = days
    display_days = max(3, min(60, int(display_days)))
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

    print(f">>> [{code}] {name} · 计算{calc_days}日/显示{display_days}日 ｜ 标的={underlying_label or '无'} ｜ 模式={mode_cfg}")
    nav = fetch_nav(code, max(calc_days, 25) + 5)
    print(f"    净值 {len(nav)} 条，最新: {nav[-1] if nav else None}")
    price, psrc = fetch_price(em_sec, tx_sym, max(calc_days, 25) + 5)
    print(f"    价格 [{psrc}] {len(price)} 条，最新: {price[-1] if price else None}")
    fx = fetch_fx()
    print(f"    汇率 {len(fx)} 天，最新: {sorted(fx.items())[-1]}")

    # 默认按指数代理准备估算源
    xop, xsrc = resolve_xop(code, und, max(calc_days, 25) + 5)
    print(f"    标的 [{xsrc}] {len(xop)} 条，最新: {sorted(xop.items())[-1] if xop else None}")
    xop_map = dict(xop)
    fx_map = fx
    if code in COMPOSITE_UNDERLYING:
        # 复合序列已按权重合成，下游 w/lag 须用 1.0/1（与 compute_one_rank 一致）
        w_use, lag_use = 1.0, 1
    else:
        w_use = weight_for(und, code=code) if und else None
        lag_use = lag_for(und, code=code) if und else 1
    use_fx_flag = und.get("use_fx", True) if und else True
    # hk_sina（新浪港股指数实时两日序列）不做 seed 兜底：SEED_XOP 是 7 月美股旧值，
    # 与 HSSI 量级(1300+)完全不同，混入会把 P 比值算爆（曾出现 est_nav=6.35 荒谬值）。
    seed_xop = (merge_seed_xop(xop_map) if (und and not und.get("hk_sina")) else 0)
    seed_fx = merge_seed_fx(fx_map)
    if seed_xop or seed_fx:
        print("    [注意] 部分标的/汇率使用 seed 兜底（本机通常被实时数据覆盖）")

    # 持仓估算分支：auto 先择优，holdings 强制；失败回退指数代理
    if effective in ("holdings", "auto"):
        try:
            if effective == "auto":
                choice = choose_mode(code, max(calc_days, 30))
                effective = choice["mode"]
                mode_info.update(choice)
            if effective == "holdings":
                hindex, hmeta = build_holdings_index(code, max(calc_days, 25) + 5)
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

    nav_map = dict(nav)
    price_map = dict(price)
    # 纯指数/ETF（无标的，场内价本就≈净值）：场内价抓取失败（熔断/限流/上游抖动）时，
    # 用最新净值兜底，避免自选池/估值页出现「无价格数据」。价差将≈0（ETF 价格≈净值），
    # 远比空白有用；盘中实时价恢复后下一次强制刷新即自动覆盖为真实场内价。
    if not price_map and und is None and nav_map:
        price_map = dict(nav_map)
        psrc = psrc + "(净值兜底)" if psrc else "净值兜底"
        print(f"    [价格兜底] 场内价抓取失败，改用净值({len(price_map)}日)作为价格")

    # —— 今日估算行（官方净值 T+1 公布前的盘中视图）——
    # 详细表默认只显示「已公布官方净值」的日期；QDII/普通基金官方净值常于 T+1 下午才公布，
    # 盘中看不到当日行。此处若 K线未含当日，用盘中实时价补一只今日行；并尽量用实时标的/
    # 汇率补全，使今日行能算出估算净值（净值标记为「待公布」）。官方净值公布后该日期会自动
    # 出现正式行，不会重复。仅对「有标的」的基金生效（无标的国内基金无盘中锚点，保持原样）。
    today = bj_now().strftime("%Y-%m-%d")
    if und:
        if today not in price_map:
            try:
                _q = _fetch_lof_quotes_tencent([code])
                if _q.get(code, {}).get("price"):
                    price_map[today] = _q[code]["price"]
                    print(f"    [今日行] K线未含当日，已用盘中实时价 {price_map[today]} 补 {today}")
            except Exception as e:
                print(f"    [今日行] 实时价获取失败: {e}")
        if today not in xop_map and code not in COMPOSITE_UNDERLYING:
            # 复合篮子 xop 为归一化序列，而 und 是单一标的（如 DBC），其腾讯实时绝对价
            # 与归一化序列量级错配；且复合篮子含美股/商品 ETF，日间≈隔夜收盘、无实时变动意义。
            # 故跳过 live 微调，由 build_rows 用上一交易日 xop 推算今日净值（量级正确）。
            _lx = _live_xop_price(und)
            if _lx is not None:
                xop_map[today] = _lx
        if use_fx_flag and today not in fx_map:
            _lfx = fetch_fx_sina_latest()
            if _lfx is not None:
                fx_map[today] = _lfx

    rows = build_rows(price_map, nav_map, xop_map, fx_map,
                      days=display_days, start=start, end=end, anchor_date=ANCHOR_DATE, und=und, code=code,
                      w_override=w_use, lag_override=lag_use, use_fx=use_fx_flag)
    rows.reverse()   # 倒序：日期最新在顶端

    control = fetch_fund_control(code)

    if rows:
        latest = rows[0]
        sig_premium = latest["est_premium"] if latest["est_premium"] is not None else latest["premium"]
        sig_text, sig_cls = signal_for_premium(sig_premium, threshold,
                                                control.get("subscribe_status", ""),
                                                control.get("redeem_status", ""))
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
        "tz": "北京时间 (UTC+8)",
        "server_bj": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "server_ts": int(time.time()),
    }


_LIVE_XOP_CACHE = {}   # {sa: (ts, price)} 盘中实时标的价（60s 有效）

def _live_xop_price(und):
    """取标的当日盘中实时价（经腾讯行情），用于把估算净值从 T-1 锚点推进到盘中（对标 haoetf 实时估值）。
    失败/无数据返回 None，调用方回退到历史收盘价，不影响原有估算。美股/商品标的在北京时间日间
    多为上一美股收盘，此时实时价≈收盘，结果近似不变；仅国内/商品期货类标的会真正随盘中变动。"""
    tx = (und or {}).get("tx")
    if not tx:
        return None
    sa = (und or {}).get("sa")
    now = time.time()
    c = _LIVE_XOP_CACHE.get(sa)
    if c and now - c[0] < 60:
        return c[1]
    try:
        rows, _ = fetch_price_tencent(tx, 1)
        if rows:
            price = rows[-1][1]
            if price and price > 0:
                _LIVE_XOP_CACHE[sa] = (now, price)
                return price
    except Exception as e:
        print(f"    [实时标的] {sa} 获取失败: {e}")
    return None


_LIVE_HOLD_EST_CACHE = {}   # code -> (ts, port_ret, idx_chg)，60s 有效，缓存组合收益率(与锚点解耦)
_HOLD_SNAP_CACHE = {}        # 腾讯代码 -> (ts, price, prev)，60s 有效，跨基金共享，避免重复批量请求
_HOLD_SNAP_LOCK = threading.Lock()


def _prefetch_holdings_snapshot(symbols, ttl=60):
    """一次性批量预取若干持仓股的实时价+昨收，写入共享缓存；精算循环内直接命中，零额外请求。
    仅补取缓存失效的符号；快照已在缓存内的跳过。返回成功写入数。"""
    symbols = list(dict.fromkeys(s for s in symbols if s))
    now = time.time()
    need = [s for s in symbols if (now - _HOLD_SNAP_CACHE.get(s, (0,))[0]) > ttl]
    if not need:
        return 0
    written = 0
    for i in range(0, len(need), 60):
        chunk = need[i:i + 60]
        try:
            snap = pivot_snap_batch(chunk)
        except Exception as e:
            print(f"    [持仓快照预取] 批量失败: {e}")
            continue
        with _HOLD_SNAP_LOCK:
            for s, q in snap.items():
                if q.get("price") and q.get("prev"):
                    _HOLD_SNAP_CACHE[s] = (time.time(), q["price"], q["prev"])
                    written += 1
    return written


def _prefetch_top_holdings(cands):
    """网页3全市场扫描冷启动优化：并发预热所有候选基金的前十大重仓(写 HOLDINGS_RAW_CACHE)
    与持仓股实时快照(写 _HOLD_SNAP_CACHE)，使后续精算循环内 fetch_holdings/快照均命中缓存、零额外请求，
    避免逐只打行情把冷启动拖过 onrender 请求超时。单次失败不影响其余(该基金优雅回退净值兜底)。"""
    # 1) 并发取持仓，收集全部持仓股腾讯代码
    syms = []
    if not cands:
        return
    with ThreadPoolExecutor(max_workers=8) as fe:
        futs = {fe.submit(fetch_holdings, c): c for c in cands}
        for f in as_completed(futs):
            try:
                h = f.result()
            except Exception:
                continue
            for (_, _, m, s) in h:
                syms.append(_tencent_sym_for_holding(m, s))
    if syms:
        n = _prefetch_holdings_snapshot(syms)
        print(f"    [TOP榜] 预取持仓快照 {n} 只，候选 {len(cands)} 只", flush=True)


def _tencent_sym_for_holding(market, sym):
    """把持仓 (market, sym) 转成腾讯行情代码。持有函数已规整：HK->hk00xxx, A->6位, US->ticker。"""
    if market == "HK":
        return sym
    if market == "US":
        return "us" + sym
    return ("sh" if sym[0] == "6" else "sz") + sym


def live_holdings_estimate(code, anchor_nav, target_date, fx_map):
    """方案B：用前十大重仓 + 腾讯实时行情合成「当前交易日盘中实时估值」。
    返回 (est_nav, index_change_pct) 或 None（无持仓/取数失败则回退到净值兜底）。
    本质同天天基金估值：est = 锚点净值 × (1 + Σ 重仓权重 × (实时价/昨收 - 1))，
    仅用已验证可用的「东财持仓 + 腾讯批量实时快照」，不依赖被地域封锁的 fundgz 估值接口。
    缓存的是组合收益率(port_ret)而非绝对估值，调用方再乘各自锚点净值，避免锚点错配。"""
    cached = _LIVE_HOLD_EST_CACHE.get(code)
    if cached and (time.time() - cached[0]) < 60:
        port_ret, idx_chg = cached[1], cached[2]
        return (anchor_nav * (1 + port_ret)) if anchor_nav else None, idx_chg
    try:
        holdings = fetch_holdings(code)
        if not holdings:
            return None
        syms = [_tencent_sym_for_holding(m, s) for (_, _, m, s) in holdings]
        _prefetch_holdings_snapshot(syms)   # 补取缺失快照(网页3已全量预热则此处直接命中)
        now = time.time()
        fx = fetch_fx() if any(m in ("US", "HK") for _, _, m, _ in holdings) else None
        fx_keys = sorted(fx.keys()) if fx else []
        port_ret = 0.0
        got = 0
        total_w = 0.0
        for (name, w, market, sym) in holdings:
            tsym = _tencent_sym_for_holding(market, sym)
            c = _HOLD_SNAP_CACHE.get(tsym)
            if not c or now - c[0] > 60 or not c[1] or not c[2] or c[2] <= 0:
                continue
            price, prevc = c[1], c[2]
            local_ret = price / prevc - 1
            if market in ("US", "HK") and fx and fx_keys:
                fx_t = _fx_at(fx, target_date)
                cur = [k for k in fx_keys if k <= target_date]
                fx_p = fx[cur[-2]] if len(cur) >= 2 else fx_t
                fx_ret = (fx_t / fx_p - 1) if (fx_t and fx_p) else 0.0
            else:
                fx_ret = 0.0
            port_ret += w * ((1 + local_ret) * (1 + fx_ret) - 1)
            total_w += w
            got += 1
        if got == 0 or not anchor_nav or anchor_nav == 0:
            return None
        idx_chg = port_ret * 100
        _LIVE_HOLD_EST_CACHE[code] = (time.time(), port_ret, idx_chg)
        est = anchor_nav * (1 + port_ret)
        print(f"    [持仓实时估值] {code}: 命中{got}只/权重{round(total_w*100,1)}% "
              f"组合变动{round(idx_chg,3)}% -> est_nav={est:.4f}")
        return est, idx_chg
    except Exception as e:
        print(f"    [持仓实时估值] {code} 失败: {e}")
        return None


def compute_one_rank(code, target_date, fx_map, threshold=THRESHOLD, index_chg_map=None):
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
    und = underlying_for(code, name, reg)
    n = 15
    try:
        nav_rows = fetch_nav(code, n)
        nav_map = dict(nav_rows)
    except Exception as e:
        return {"code": code, "name": name, "error": f"净值获取失败: {e}"}
    try:
        price_rows, psrc = fetch_price(em_sec, tx_sym, n)
        price_map = dict(price_rows)
    except Exception as e:
        return {"code": code, "name": name, "error": f"价格获取失败: {e}"}

    # —— 今日行补充（与套利看板 compute() 完全一致）——
    # K线未含当日时，用盘中实时价补今日，使 TOP/排行与看板的估算溢价基于同一天价格，
    # 避免「看板显示今日盘中、TOP 停在上交易日收盘」造成的溢价口径差异。
    today = bj_now().strftime("%Y-%m-%d")
    # 仅在【已开盘的交易时段】补今日行。旧实现不判断时段，于是周末/夜间/开盘前也会拿
    # 腾讯返回的「上一交易日收盘价」写进 price_map[today]，制造「今天已有数据」的假象——
    # 排行表随即把日期标成今天、数值却是上一交易日收盘价（用户最在意的日期错位）。
    _bj = bj_now()
    _mkt_open = _is_trading_day(_bj) and (_bj.hour > 9 or (_bj.hour == 9 and _bj.minute >= 30))
    if und and _mkt_open and today not in price_map:
        try:
            _q = _fetch_lof_quotes_tencent([code])
            if _q.get(code, {}).get("price"):
                price_map[today] = _q[code]["price"]
                print(f"    [{code}] 今日行补盘中价 {price_map[today]}")
        except Exception as e:
            print(f"    [{code}] 今日行实时价失败: {e}")

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
    index_change = None
    if price and nav and nav != 0:
        premium = (price - nav) / nav * 100

    # 与网页1(套利看板)保持一致：持仓/自动模式时，用「持仓估算 vs 指数代理 取误差更小者」的择优结果
    mode_cfg = HOLDINGS_MODE.get(code, "index")
    est_mode = mode_cfg
    hindex = None
    if mode_cfg in ("auto", "holdings"):
        try:
            if mode_cfg == "auto":
                choice = choose_mode(code, 30)
                est_mode = choice["mode"]
            if est_mode == "holdings":
                hindex, _hmeta = build_holdings_index(code, 30)
                if not hindex:
                    est_mode = "index"
        except Exception as e:
            est_mode = "index"
            print(f"    [{code}] 持仓择优失败，回退指数代理: {e}")

    # und 已在上方解析（今日行补充用）
    # 注：原「前十大重仓实时估值(live_holdings_estimate)」分支已移除——套利看板 compute()
    # 不调用该逻辑，保留会造成 TOP 与看板估算净值/溢价不一致（用户反馈"TOP 估算不准"）。
    # 无标的国内基金在下方与看板一致回退官方净值；持仓配置基金由 est_mode==holdings 的
    # 合成持仓指数(build_holdings_index)分支处理（与看板同源）。
    if und and est_nav is None:
        try:
            # 持仓模式：用合成持仓指数作为估算标的（换汇已折入），w=1、lag=1、不再乘汇率
            if est_mode == "holdings" and hindex:
                xop_map = hindex
                xsrc = "持仓"
                use_fx = False
                w = 1.0
                lag = 1
            else:
                xop_map, xsrc = resolve_xop(code, und, n)
                if not und.get("hk_sina"):
                    merge_seed_xop(xop_map)
                use_fx = und.get("use_fx", True)
                if code in COMPOSITE_UNDERLYING:
                    # 复合序列(_build_composite_xop)已按权重合成归一化日收益累积，
                    # 下游 w/lag 公式须用 w=1.0、lag=1，否则会再乘单一标的权重复调导致估值离谱
                    w = 1.0
                    lag = 1
                else:
                    w = weight_for(und, code=code)
                    lag = lag_for(und, code=code)
            # 今日行补充：与套利看板一致，盘中把今日实时标的价/汇率补进 map，
            # 使 P 的日期对齐到今日（实时标的失败时回退上一交易日，行为同看板）
            if d == bj_now().strftime("%Y-%m-%d"):
                if code not in COMPOSITE_UNDERLYING and today not in xop_map:
                    _lx = _live_xop_price(und)
                    if _lx is not None:
                        xop_map[today] = _lx
                if use_fx and today not in fx_map:
                    try:
                        _lfx = fetch_fx_sina_latest()
                        if _lfx is not None:
                            fx_map[today] = _lfx
                    except Exception:
                        pass
            # 严格 T-1 对齐：以目标日 d 为 T，取 T-1 日官方净值作锚
            # FV(T) = NAV(T-1) × [1 + w × (P - 1)]
            # P = XOP(T)/XOP(T-1) × (FX(T)/FX(T-1) if use_fx else 1)
            xop_dates = sorted(xop_map.keys())
            nav_t1_date = prev_date_lt(nav_dates, d)
            xop_t_date = prev_trade_day(xop_dates, d)
            if xop_t_date:
                idx = xop_dates.index(xop_t_date)
                k = max(0, idx - lag)
                xop_t1_date = xop_dates[k]
            else:
                xop_t1_date = None

            nav_t1 = nav_map.get(nav_t1_date) if nav_t1_date else None
            xop_t = xop_map.get(xop_t_date) if xop_t_date else None
            xop_t1 = xop_map.get(xop_t1_date) if xop_t1_date else None

            if nav_t1 and xop_t1 and xop_t and price:
                # 盘中实时微调：若取得到标的当日实时价，用它替代上一交易日收盘作锚点，
                # 使估算净值随盘中变动（对标 haoetf「实时估值=最新估值+实时期货微调」）。
                # 仅对"查看当日"生效；美股/商品标的日间实时价≈收盘，结果近似不变，安全。
                xop_t_eff = xop_t
                if d == bj_now().strftime("%Y-%m-%d") and und.get("tx") and code not in COMPOSITE_UNDERLYING:
                    # 复合篮子 xop 为归一化序列，und 单一标的实时绝对价与之量级错配，跳过 live 微调
                    live = _live_xop_price(und)
                    if live and live > 0:
                        xop_t_eff = live
                if use_fx:
                    fx_t = fx_map.get(xop_t_date) if xop_t_date else None
                    fx_t1 = fx_map.get(xop_t1_date) if xop_t1_date else None
                    if fx_t1 and fx_t:
                        P = (xop_t_eff / xop_t1) * (fx_t / fx_t1)
                    else:
                        P = None
                else:
                    P = xop_t_eff / xop_t1
                if P is not None:
                    est_nav = nav_t1 * (1 + w * (P - 1))
                    est_premium = (price - est_nav) / est_nav * 100
                    index_change = pct(xop_t_eff, xop_t1)
        except Exception as e:
            print(f"    [{code}] 估算净值失败: {e}")
    # 国内指数 / 行业 LOF：无 QDII 标的时，用「跟踪指数日内涨跌」估算当日净值（对标 haoetf 实时估值）
    #   est_nav = 官方净值 × (1 + 指数日内涨跌% × w)；取数失败 / 无映射则回退官方净值（原行为）。
    # 主动 / 混合 / FOF 无单一跟踪指数，自然走回退（其净值次日披露，盘中没有可代理的日内标的）。
    if est_nav is None and nav is not None and price is not None:
        # 与套利看板 compute() 完全一致：无 QDII 标的的国内基金直接回退官方净值，
        # 官方溢价 = (价格 - 最新净值) / 最新净值。不做 DOMESTIC_INDEX_MAP 指数日内估算，
        # 避免与看板口径不一致（用户对比两页时出现"TOP 估算不准"）。
        est_nav = nav
        est_premium = premium

    sig_premium = est_premium if est_premium is not None else premium
    sig_text, sig_cls = signal_for_premium(sig_premium, threshold,
                                            control.get("subscribe_status", ""),
                                            control.get("redeem_status", ""))

    return {
        "code": code, "name": name, "short": short_name(code, name),
        "date": d, "time": "15:00",
        "price": price, "price_change": price_change,
        "nav": nav, "nav_date": nav_d, "nav_change": nav_change,
        "premium": premium,
        "est_nav": est_nav, "est_premium": est_premium, "index_change": index_change,
        "est_mode": est_mode,
        "subscribe_status": control.get("subscribe_status", ""),
        "purchase_limit": control.get("purchase_limit"),
        "purchase_limit_text": control.get("purchase_limit_text", ""),
        "redeem_status": control.get("redeem_status", ""),
        "signal": sig_text, "signal_cls": sig_cls,
        "error": None,
    }


def _backtest_index(code, days=30, fx_map=None):
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
        if not und.get("hk_sina"):
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


def backtest_nav_estimate(code, days=30, fx_map=None, mode="index"):
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
        # 必须用北京时区口径：datetime.now() 取的是服务器本地时区（线上为 UTC），
        # 会整体偏 8 小时使日期标签错位。排行表支持盘中补价，故这里仍取「今天」。
        target_date = bj_now().strftime("%Y-%m-%d")
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
    # 成交额(万元)：网页2 表格流动性列（失败不影响排行）
    try:
        turn_map = fetch_turnover(codes)
    except Exception as e:
        print(f"    [排行] 成交额获取失败: {e}")
        turn_map = {}
    for r in results:
        if not r.get("error"):
            r["turnover"] = turn_map.get(r["code"])
    return {"date": target_date, "threshold": threshold, "count": len(results), "rows": results,
            "tz": "北京时间 (UTC+8)",
            "server_bj": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
            "server_ts": int(time.time())}


# ---------------------------------------------------------------------------
# 网页3：TOP 套利榜 —— 全市场 LOF 粗筛 + 精算 + 条件过滤
# ---------------------------------------------------------------------------
# LOF 代码段：深市 16xxxx（含 18 打头的少数封转开不计），沪市 501xxx-506xxx
_LOF_CODE_RE = re.compile(r"^(16\d{4}|50[0-6]\d{3})$")

_LOF_LIST_CACHE = {"ts": 0.0, "data": None}          # 全市场 LOF 代码+名称（12h）
_MARKET_TABLE_CACHE = {"ts": 0.0, "data": None}      # 东财场内基金表（10min）
_SCALE_CACHE = {}                                     # {code: (ts, 规模亿元)}（24h）

# ---- 磁盘持久化缓存（提速#2：休眠/重启后首个请求秒回旧数据，后台静默刷新）----
# API 结果（轻量、高频写→去抖）与重数据源（场内表/LOF清单，低频写）分开落盘，
# 避免每次 API 持久化都重写几十 MB 的场内表。_render 重启/免费实例休眠后文件仍在，
# 启动时 _hydrate_from_disk 回填内存，首个请求即可秒回（含可能过期的旧数据）。
CACHE_API_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fund_arb_cache_api.json")
CACHE_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fund_arb_cache_data.json")
_DISK_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_REFRESHING = set()          # 后台刷新去重：同一 key 只允许一个刷新线程
_PERSIST_LAST = {"t": 0.0}  # API 持久化去抖时间戳


def _persist_api():
    """把 API 结果缓存落盘（去抖 30s，避免高频写）。"""
    now = time.time()
    if now - _PERSIST_LAST["t"] < 30.0:
        return
    _PERSIST_LAST["t"] = now
    try:
        with open(CACHE_API_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in Handler._API_CACHE.items()}, f, ensure_ascii=False)
        os.replace(CACHE_API_FILE + ".tmp", CACHE_API_FILE)
    except Exception as e:
        print(f"    [缓存] API 持久化失败: {e}")


def _persist_data():
    """把重数据源缓存（场内表/LOF清单/流通市值）落盘；调用点均为低频更新，无需去抖。"""
    try:
        store = {"lof_list": _LOF_LIST_CACHE, "market_table": _MARKET_TABLE_CACHE,
                 "float_caps": _FLOAT_CAP_CACHE,
                 # F10 总规模（24h 有效）落盘：线上实例休眠/重部署后无需逐只重抓
                 # （东财对该页面有 514 限频，全量重抓会耗时数十秒且全部失败）
                 "scale": {c: v for c, v in _SCALE_CACHE.items() if v and v[1] is not None}}
        with open(CACHE_DATA_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False)
        os.replace(CACHE_DATA_FILE + ".tmp", CACHE_DATA_FILE)
    except Exception as e:
        print(f"    [缓存] 数据源持久化失败: {e}")


def _hydrate_from_disk():
    """启动时从磁盘回填内存缓存（含可能过期的旧数据），使休眠/重启后首个请求秒回。"""
    try:
        if os.path.exists(CACHE_API_FILE):
            with open(CACHE_API_FILE, "r", encoding="utf-8") as f:
                api = json.load(f)
            for k, v in api.items():
                if k.startswith("top|"):
                    continue    # 跳过 TOP 榜旧缓存，强制重算（避免规模过滤修复前旧数据残留）
                Handler._API_CACHE[k] = tuple(v) if isinstance(v, list) and len(v) == 2 else v
        if os.path.exists(CACHE_DATA_FILE):
            with open(CACHE_DATA_FILE, "r", encoding="utf-8") as f:
                store = json.load(f)
            ll = store.get("lof_list")
            if isinstance(ll, dict) and ll.get("data"):
                _LOF_LIST_CACHE["ts"], _LOF_LIST_CACHE["data"] = ll.get("ts", 0.0), ll["data"]
            mt = store.get("market_table")
            if isinstance(mt, dict) and mt.get("data"):
                _MARKET_TABLE_CACHE["ts"], _MARKET_TABLE_CACHE["data"] = mt.get("ts", 0.0), mt["data"]
            fc = store.get("float_caps")
            if isinstance(fc, dict) and fc.get("data"):
                _FLOAT_CAP_CACHE["ts"], _FLOAT_CAP_CACHE["data"] = fc.get("ts", 0.0), fc["data"]
            sc = store.get("scale")
            if isinstance(sc, dict):
                # 过期的条目是安全的：fetch_fund_scale 有 24h 校验，过期会重新抓取
                for c, v in sc.items():
                    if c not in _SCALE_CACHE and isinstance(v, list) and len(v) == 2:
                        _SCALE_CACHE[c] = tuple(v)
        # TOP 套利榜全量快照回填（冷启动秒回历史候选，无需等全市场重算）
        # 历史教训：曾因规模过滤修复暂跳过回填（if False），导致 onrender 冷启动
        # 快照为空 → 全市场冷算在美西节点取不到东财行情 → 榜单缩水且估算全部回退
        # 官方净值（用户反馈"TOP 估算跟前一天一模一样"）。现恢复回填。
        if os.path.exists(TOP_SNAP_FILE):
            try:
                with open(TOP_SNAP_FILE, encoding="utf-8") as _tf:
                    _s = json.load(_tf)
                if _s.get("rows"):
                    with _TOP_SNAP_LOCK:
                        _TOP_SNAPSHOT.update(ts=_s.get("ts", 0.0), date=_s.get("date"),
                                             universe=_s.get("universe", 0),
                                             tradable=_s.get("tradable", 0),
                                             candidates=_s.get("candidates", 0),
                                             rows=_s.get("rows", []))
                    print(f"    [缓存] 已从磁盘回填 TOP 全量快照（{len(_s.get('rows', []))} 候选行）")
            except Exception as _e:
                print(f"    [缓存] TOP快照回填失败: {_e}")
        print(f"    [缓存] 已从磁盘回填 {len(Handler._API_CACHE)} 条 API 结果（含可能过期的旧数据）")
    except Exception as e:
        print(f"    [缓存] 磁盘回填失败: {e}")
TOP_DISCOUNT_GATE = -2.0    # 折价侧门槛：估算溢价 < -2% 且开放赎回
TOP_MAX_CANDIDATES = 80     # 粗筛后进入精算的最大候选数


def fetch_all_lof_codes():
    """全市场 LOF 代码清单 [(code, name), ...]，来源：天天基金全部基金代码表。"""
    now = time.time()
    if _LOF_LIST_CACHE["data"] and now - _LOF_LIST_CACHE["ts"] < 12 * 3600:
        return _LOF_LIST_CACHE["data"]
    txt = http_get_text("https://fund.eastmoney.com/js/fundcode_search.js",
                        referer="https://fund.eastmoney.com/", timeout=25, retries=2)
    m = re.search(r"\[\[.*\]\]", txt, re.S)
    if not m:
        raise RuntimeError("基金代码表解析失败")
    arr = json.loads(m.group(0))
    data = [(a[0], a[2], (a[3] if len(a) > 3 else "")) for a in arr if _LOF_CODE_RE.match(a[0])]
    if data:
        _LOF_LIST_CACHE.update(ts=now, data=data)
        _persist_data()
    return data


_LOF_QUOTE_MEM = {}          # {code: (expire_ts, quote)} 进程内短缓存，见下方说明
_LOF_QUOTE_MEM_TTL = 90.0    # 秒：盘中价更新快，缓存只用于削峰（TOP 扫描内的重复请求）


def _fetch_lof_quotes_tencent(codes):
    """腾讯批量实时行情（主源）。返回 {code: {price, volume(手), amount(万元), trade_date, trade_time}}。

    进程内短缓存（90s）：TOP 全市场扫描会先批量取一次全市场行情，随后精算循环里
    每只基金又单独调一次本函数补盘中价——旧实现因此产生 200+ 次重复 HTTP 请求。
    缓存后这些调用全部命中内存、零网络开销（盘中价新鲜度由调用方决定是否强取）。
    """
    out = {}
    now = time.time()
    miss = []
    for c in codes:
        hit = _LOF_QUOTE_MEM.get(c)
        if hit and hit[0] > now:
            out[c] = hit[1]
        else:
            miss.append(c)
    if not miss:
        return out
    fresh = {}
    for i in range(0, len(miss), 60):
        chunk = miss[i:i + 60]
        q = ",".join(deduce_exchange(c)[1] for c in chunk)
        try:
            txt = http_get_text("https://qt.gtimg.cn/q=" + q, timeout=10, retries=2, encoding="gbk")
        except Exception as e:
            print(f"    [行情] 腾讯批次失败: {e}")
            continue
        for seg in txt.split(";"):
            if "~" not in seg:
                continue
            f = seg.split("~")
            if len(f) < 31:
                continue
            try:
                code = f[2].strip()
                price = float(f[3])
                vol = float(f[6] or 0)
                # 字段 [37] = 当日成交额(万元)，网页2/网页3「成交额(万元)」列的数据源
                amount = float(f[37]) if len(f) > 37 and f[37] else None
            except (ValueError, IndexError):
                continue
            if price > 0:
                ts = f[30]
                fresh[code] = {"price": price, "volume": vol, "amount": amount,
                               "trade_date": ts[:8] if len(ts) >= 8 else "",
                               "trade_time": ts}
    for c, v in fresh.items():
        _LOF_QUOTE_MEM[c] = (now + _LOF_QUOTE_MEM_TTL, v)
        out[c] = v
    return out


def _parse_sina_realtime(txt):
    """解析新浪 hq.sinajs.cn 实时返回，转成与腾讯同构的 {code:{...}}。"""
    out = {}
    for seg in txt.split(";"):
        seg = seg.strip()
        if "hq_str_" not in seg or "=\"" not in seg:
            continue
        try:
            sym = seg.split("hq_str_")[1].split("=")[0]
            body = seg.split("\"", 1)[1].rsplit("\"", 1)[0]
        except Exception:
            continue
        if not body:
            continue
        f = body.split(",")
        if len(f) < 10:
            continue
        try:
            code = sym[2:] if sym[:2] in ("sz", "sh") else sym
            price = float(f[3])
            vol = float(f[8] or 0) / 100.0          # 新浪为股，转手
            amount = float(f[9] or 0) / 10000.0      # 元转万元
        except (ValueError, IndexError):
            continue
        if price > 0:
            ts = f[30] if len(f) > 30 else ""
            out[code] = {"price": price, "volume": vol, "amount": amount,
                         "trade_date": ts.replace("-", "")[:8] if ts else "",
                         "trade_time": (ts + " " + f[31]) if len(f) > 31 and f[31] else ts}
    return out


def _fetch_lof_quotes_sina(codes):
    """新浪实时行情（腾讯兜底源）。返回同构字典。"""
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        q = ",".join(deduce_exchange(c)[1] for c in chunk)
        try:
            txt = http_get_text("https://hq.sinajs.cn/list=" + q,
                                referer="https://finance.sina.com.cn/", timeout=10, retries=2, encoding="gbk")
        except Exception as e:
            print(f"    [行情] 新浪批次失败: {e}")
            continue
        out.update(_parse_sina_realtime(txt))
    return out


def fetch_lof_quotes(codes):
    """场内实时行情：腾讯(主) → 新浪(兜底)。单源 501/限频时自动切换，避免网页3整页打不开。
    返回 {code: {price, volume, amount, trade_date, trade_time}}。"""
    out = {}
    try:
        out.update(_fetch_lof_quotes_tencent(codes))
    except Exception as e:
        print(f"    [行情] 腾讯实时整体失败: {e}")
    miss = [c for c in codes if c not in out]
    if miss:
        try:
            out.update(_fetch_lof_quotes_sina(miss))
        except Exception as e:
            print(f"    [行情] 新浪实时整体失败: {e}")
    return out


def fetch_market_fund_table():
    """东财场内基金净值表（t=8）：{code: {nav, nav_date, subscribe, redeem, limit}}。
    limit 为限购金额(元)，>=1e9 视为不限购(None)；缓存 10 分钟。"""
    now = time.time()
    if _MARKET_TABLE_CACHE["data"] and now - _MARKET_TABLE_CACHE["ts"] < 600:
        return _MARKET_TABLE_CACHE["data"]
    dt = int(now * 1000)
    url = ("https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx?t=8&lx=1&letter=&gsid=&text="
           f"&sort=zdf,desc&page=1,20000&dt={dt}&atfc=&onlySale=0")
    txt = http_get_text(url, referer="https://fund.eastmoney.com/fund.html", timeout=25, retries=2)
    m = re.search(r"datas:(\[\[.*?\]\])", txt, re.S)
    if not m:
        raise RuntimeError("场内基金表解析失败")
    data = json.loads(m.group(1).replace("'", '"'))
    year = bj_now().strftime("%Y")
    out = {}
    for r in data:
        try:
            nav = float(r[3]) if r[3] else None
        except (ValueError, TypeError):
            nav = None
        nav_date = f"{year}-{r[4]}" if r[4] else None   # 'MM-DD' -> 'YYYY-MM-DD'
        limit = None
        try:
            v = float(r[9])
            limit = None if v >= 1e9 else v             # 1e9+ = 不限购
        except (ValueError, TypeError, IndexError):
            pass
        # 申购状态归一化：东财场内表 r[5] 原始值可能是 "限大额"（不带"申购"），
        # 与 SUBSCRIBE_OPEN / F10 解析的 "限大额申购" 不一致，会导致限大额基金在
        # TOP 榜终筛被整条剔除。此处按 F10 解析口径统一归一化。
        raw_sub = (r[5] or "").strip()
        if "暂停申购" in raw_sub:
            sub = "暂停申购"
        elif "限大额" in raw_sub or "限购" in raw_sub:
            sub = "限大额申购"
        elif "开放申购" in raw_sub:
            sub = "开放申购"
        else:
            sub = raw_sub
        # 赎回状态 r[6] 原始值已是 "开放赎回" 等规范表述，与 REDEEM_OPEN 一致，无需归一化
        out[r[0]] = {"nav": nav, "nav_date": nav_date,
                     "subscribe": sub, "redeem": (r[6] or "").strip(),
                     "limit": limit}
    if out:
        _MARKET_TABLE_CACHE.update(ts=now, data=out)
        _persist_data()
    return out


def fetch_fund_scale(code):
    """基金资产规模（亿元），来源东财 F10 基本概况页；失败返回 None。缓存 24h。"""
    hit = _SCALE_CACHE.get(code)
    if hit and time.time() - hit[0] < 24 * 3600:
        return hit[1]
    scale = None
    try:
        txt = http_get_text(f"https://fundf10.eastmoney.com/jbgk_{code}.html",
                            referer="https://fundf10.eastmoney.com/", timeout=15, retries=2)
        m = re.search(r"资产规模</th>\s*<td[^>]*>([\d,.]+)亿元", txt)
        if m:
            scale = float(m.group(1).replace(",", ""))
    except Exception as e:
        print(f"    [TOP榜] {code} 规模获取失败: {e}")
    _SCALE_CACHE[code] = (time.time(), scale)
    return scale


# ---------------------------------------------------------------------------
# 二级市场可交易规模（场内流通市值，亿元）：网页3 TOP 榜「条件2」筛选用。
# 主来源东财 push2delay ulist.np 的 f21（见 _fetch_float_cap_batch）；
# 与「总规模(资产规模)」不同——LOF 大量份额在场外，场内可交易规模远小于总规模，
# 套利必须看场内可交易规模。缓存 10 分钟。失败时回落板块 clist / 单只 F10 总规模。
# ---------------------------------------------------------------------------
_FLOAT_CAP_CACHE = {"ts": 0.0, "data": {}}      # push2 场内流通市值（10min 有效）
_FLOAT_CAP_BACKOFF = {"until": 0.0}              # 限频退避：失败后背刺期内复用旧值、不重试

def _em_quote_hosts():
    """东财行情域名轮换顺序：push2delay 排最前。

    实测（含线上 onrender 与本机）：push2.eastmoney.com 及其数字镜像
    (1.push2 / 23.push2 …) 常直接 RemoteDisconnected，而 push2delay 稳定可达
    （0.1~0.5s）。旧实现把 push2 硬编码为唯一域名，导致线上场内流通市值恒为空、
    退化成逐只 F10 兜底（59s 且被 514 限频）——这是 TOP 榜线上跑不完的根因之一。
    """
    import random as _r
    hosts = ["push2delay.eastmoney.com"]
    hosts += ["%d.push2.eastmoney.com" % _r.randint(1, 99) for _ in range(4)]
    hosts += ["push2.eastmoney.com"]
    return hosts


def _fetch_float_cap_batch(codes, batch=60):
    """批量取任意代码的场内流通市值：push2 ulist.np 的 f21 字段（元→亿元）。

    与板块 clist 的区别：ulist.np 支持显式 secids，不受东财板块收录限制。
    实测全市场 610 只 LOF 分 11 批、2.2s 完成，覆盖 463 只（板块 clist 仅 137 只）。
    """
    out, sec = {}, []
    for c in codes:
        try:
            sec.append((c, deduce_exchange(c)[0]))
        except Exception:
            pass
    hosts = _em_quote_hosts()
    for i in range(0, len(sec), batch):
        ids = ",".join(s for _, s in sec[i:i + batch])
        got = None
        for host in hosts:
            try:
                url = (f"https://{host}/api/qt/ulist.np/get?fields=f12,f21&secids={ids}"
                       f"&ut=fa5fd1943c7b386f172d6893dbfba10b")
                j = json.loads(http_get_text(url, referer="https://quote.eastmoney.com/",
                                             timeout=12, retries=1))
                got = (j.get("data") or {}).get("diff") or []
                if got:
                    break
            except Exception:
                continue
        for it in (got or []):
            code, v = it.get("f12"), it.get("f21")
            if code and isinstance(v, (int, float)) and v > 0:
                out[code] = v / 1e8
    return out


def _fetch_float_cap_by_board():
    """兜底：东财 LOF 场内基金板块 clist（MK0025-0028）分页拉取。仅覆盖 ~137 只，
    作为 ulist.np 不可用时的降级路径（保持 push2delay 优先的域名轮换）。"""
    out = {}
    hosts = _em_quote_hosts()
    for mk in ("MK0025", "MK0026", "MK0027", "MK0028"):
        for pn in range(1, 10):
            got, items = None, []
            for host in hosts:
                try:
                    url = (f"https://{host}/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
                           f"&fltt=2&invt=2&fid=f3&fs=b:{mk}"
                           f"&fields=f12,f21&ut=7eea3edcaed734bea9cbfc24409ed989")
                    j = json.loads(http_get_text(url, referer="https://quote.eastmoney.com/",
                                                 timeout=12, retries=1))
                    items = (j.get("data") or {}).get("diff") or []
                    got = True
                    break
                except Exception:
                    continue
            if not got:
                break
            if not items:
                break
            for it in items:
                code, v = it.get("f12"), it.get("f21")
                if code and v not in (None, "", "-"):
                    try:
                        out[code] = float(v) / 1e8
                    except (ValueError, TypeError):
                        pass
            if len(items) < 100:
                break
    return out


def fetch_float_market_cap(codes=None):
    """全市场 LOF 二级市场可交易规模（场内流通市值，亿元）；内存缓存 10 分钟。

    主路径：push2delay ulist.np 批量取 f21（见 _fetch_float_cap_batch）；
    兜底路径：板块 clist。规模数据变化慢，旧值对粗筛/终筛足够。
    鲁棒性：失败时进入 30 分钟退避，期间复用上一次成功值（可能为磁盘回填的旧值），
    避免对东财连续高频重试而拉长限频窗口。
    """
    now = time.time()
    if _FLOAT_CAP_CACHE["data"] and now - _FLOAT_CAP_CACHE["ts"] < 600:
        return _FLOAT_CAP_CACHE["data"]          # 新鲜数据，直接返回
    if now < _FLOAT_CAP_BACKOFF["until"]:
        return _FLOAT_CAP_CACHE["data"] or {}     # 退避期内：复用旧值，不重试
    if codes is None:
        try:
            codes = [c for c, _, _ in fetch_all_lof_codes()]
        except Exception:
            codes = []
    out = _fetch_float_cap_batch(codes) if codes else {}
    if not out:
        out = _fetch_float_cap_by_board()
    if out:
        _FLOAT_CAP_CACHE.update(ts=now, data=out)
        _FLOAT_CAP_BACKOFF["until"] = 0.0
        _persist_data()                           # 落盘，使重启/限频窗口后仍可用旧值
        return out
    # 失败或空响应：进入退避，复用上一次好数据（可能为磁盘回填）
    print("    [TOP榜] 场内流通市值全部路径失败（退避30min，复用旧值）")
    _FLOAT_CAP_BACKOFF["until"] = now + 1800
    return _FLOAT_CAP_CACHE["data"] or {}


# ---------------------------------------------------------------------------
# 成交额(万元)：网页2/网页3 表格流动性列。来源腾讯当日行情字段[37]（复用 fetch_lof_quotes）。
# 说明：东财基金日K线(push2his)不返回 LOF 场内成交额，故采用腾讯当日成交额作为流动性代理；
# 若需在盘前(09:30 前)查看「前一日」全量成交额，此时腾讯[37]即上一交易日数据。按 code 缓存 6h。
# ---------------------------------------------------------------------------
_TURNOVER_CACHE = {}

def fetch_turnover(codes):
    """返回 {code: 成交额(万元) 或 None}，来源腾讯当日行情字段[37]。"""
    now = time.time()
    out, miss = {}, []
    for c in codes:
        h = _TURNOVER_CACHE.get(c)
        if h and now - h[0] < 6 * 3600:
            out[c] = h[1]
        else:
            miss.append(c)
    if miss:
        qt = fetch_lof_quotes(miss)
        for c in miss:
            v = qt.get(c, {}).get("amount")
            out[c] = v
            _TURNOVER_CACHE[c] = (now, v)
    return out


# ---- TOP 套利榜「全量快照」：重计算只后台跑一次，参数化视图内存秒回 ----
# 对齐 haoetf/palmmicro：用户请求只做 filter+sort，不再触发全市场网络扫描。
TOP_SNAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fund_arb_cache_top.json")
_TOP_SNAPSHOT = {"ts": 0.0, "date": None, "universe": 0, "tradable": 0,
                "candidates": 0, "filter_trace": {}, "rows": []}
_TOP_SNAP_LOCK = _threading.Lock()


# ---- 近5日入选历史（口袋支点 / TOP / 可转债 三页统计表数据源）----
# 每次成功生成当日结果时，把入选名单（精简字段）追加到 history_entries.json，
# 前端三页各自 fetch /api/history?type=... 渲染「近5个交易日入选统计表」。
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history_entries.json")
_HISTORY_LOCK = _threading.Lock()
HISTORY_MAX_DAYS = 5   # 只保留最近 5 个交易日

def _history_load():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"    [历史] 读取失败: {e}")
    return {}

def _history_save(data):
    try:
        with open(HISTORY_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(HISTORY_FILE + ".tmp", HISTORY_FILE)
    except Exception as e:
        print(f"    [历史] 写入失败: {e}")

def history_append(kind, date, entries):
    """追加当日入选记录。kind: pivot/top/cb；entries: 精简字段列表。
    跨日自然累积；同一天多轮扫描按 code 合并去重（后到覆盖同 code），不丢已入选信号。"""
    if not entries:
        return
    with _HISTORY_LOCK:
        data = _history_load()
        bucket = data.setdefault(kind, {})
        merged = {}
        for e in bucket.get(date, []):
            merged[e.get("code")] = e
        for e in entries:
            merged[e.get("code")] = e
        bucket[date] = list(merged.values())
        # 只保留最近 5 个交易日（按日期字符串排序取后 5）
        dates = sorted(bucket.keys())
        for old in dates[:-HISTORY_MAX_DAYS]:
            bucket.pop(old, None)
        _history_save(data)

def history_payload(kind, days=5):
    """返回近 N 个交易日的入选记录（按日期升序拼接，附 date 字段）。
    线上节点（onrender 美国节点）无法连通东财/腾讯行情，扫描恒失败，
    history_entries.json 长期为空 → 近5日统计表空白。此时回退用已提交的
    pivot_snapshot.json / cb_snapshot.json（随仓库发布、redeploy 不丢）派生单日入选记录，
    保证线上也能展示最近一个交易日的入选清单；用户在本机/国内节点运行后，实时历史会自然覆盖。
    """
    with _HISTORY_LOCK:
        data = _history_load()
        bucket = data.get(kind, {})
        dates = sorted(bucket.keys())[-days:]
        out = []
        for d in dates:
            for e in bucket.get(d, []):
                row = dict(e)
                row["date"] = d
                out.append(row)
        if out:
            # 合并：若已提交快照的交易日比实时历史更新（用户本地扫了新快照但还没推
            # history_entries.json），把该最新一日补进表尾，保证「近N日」始终含最新扫描日，
            # 避免 onrender 上「今天刷新后历史被快照覆盖/变空」的观感。
            out_dates = {r.get("date") for r in out}
            max_hist = max(out_dates) if out_dates else ""
            snap_rows = _history_from_snapshot(kind)
            if snap_rows:
                snap_latest = snap_rows[-1].get("date")
                if snap_latest and snap_latest > max_hist and snap_latest not in out_dates:
                    existing = {r.get("code") for r in out if r.get("date") == snap_latest}
                    for e in snap_rows:
                        if e.get("code") not in existing:
                            out.append(e)
            return out[-days:]
    # 回退：实时历史为空 → 用快照派生（仅当没有真实历史时）
    snap_rows = _history_from_snapshot(kind)
    if snap_rows:
        return snap_rows[-days:]
    return []


def _history_from_snapshot(kind):
    """从已提交的快照文件派生近 N 日入选记录（线上兜底）。"""
    if kind == "pivot":
        fn = PIVOT_SNAP_FILE
        entries_fn = _pivot_history_entries
    elif kind == "cb":
        fn = CB_SNAP_FILE
        entries_fn = _cb_history_entries
    else:
        return []
    try:
        if not os.path.exists(fn):
            return []
        with open(fn, "r", encoding="utf-8") as f:
            snap = json.load(f)
        td = snap.get("trade_date") or snap.get("updated") or (snap.get("picks") and "")
        if not td:
            return []
        # trade_date 可能是 "2026-08-21"；取前10字符作日期
        date_str = td[:10] if isinstance(td, str) else ""
        entries = entries_fn(snap)
        if not entries:
            return []
        return [{**e, "date": date_str} for e in entries]
    except Exception as e:
        print(f"    [历史] 快照派生失败({kind}): {e}")
        return []

def _pivot_history_entries(res):
    """口袋支点：A级及以上（S/A）入选记录。"""
    out = []
    for p in (res.get("picks") or []):
        g = p.get("grade", "")
        if g in ("S", "A"):
            out.append({
                "code": p.get("code"), "name": p.get("name"),
                "grade": g, "price": p.get("close"),  # 入选日价格
            })
    return out

def _top_history_entries(rows, threshold=1.5):
    """TOP 套利：估算溢价 ≥ threshold（默认1.5%）的入选记录。"""
    out = []
    for r in rows:
        sp = r.get("est_premium") if r.get("est_premium") is not None else r.get("premium")
        if sp is None or sp < threshold:
            continue
        out.append({
            "code": r.get("code"), "name": r.get("name"),
            "price": r.get("price"), "nav": r.get("nav"),
            "est_premium": round(sp, 2),
        })
    return out

def _cb_history_entries(res):
    """可转债：严格折价（is_discount）入选记录。"""
    out = []
    for p in (res.get("picks") or []):
        if not p.get("is_discount"):
            continue
        out.append({
            "code": p.get("code"), "name": p.get("name"),
            "price": p.get("price"),              # 转债入选日价
            "stock_code": p.get("stock_code"), "stock_name": p.get("stock_name"),
            "stock_price": p.get("stock_price"),  # 正股入选日价
            "convert_price": p.get("convert_price"),  # 入选日转股价
            "arb": p.get("arb"),
        })
    return out

def _persist_top_snapshot():
    """把 TOP 全量快照落盘（去抖 30s），使冷启动也能秒回历史候选。"""
    now = time.time()
    if now - _PERSIST_LAST.get("top", 0.0) < 30.0:
        return
    _PERSIST_LAST["top"] = now
    try:
        with _TOP_SNAP_LOCK:
            snap = dict(_TOP_SNAPSHOT)
        with open(TOP_SNAP_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(TOP_SNAP_FILE + ".tmp", TOP_SNAP_FILE)
    except Exception as e:
        print(f"    [缓存] TOP快照持久化失败: {e}")

def _top_finalize(base_rows, threshold, dgate, top_n):
    """对阈值前的候选行按 threshold/dgate 终筛 + 信号 + 排序 + 截断。纯内存，毫秒级。
    不回写共享快照行（避免不同阈值并发互相污染信号字段）。"""
    out = []
    for r in base_rows:
        sp = r.get("est_premium") if r.get("est_premium") is not None else r.get("premium")
        if sp is None:
            continue
        redeem = r.get("redeem_status", "")
        if not (sp >= threshold or (sp < dgate and redeem in REDEEM_OPEN)):
            continue
        sig_text, sig_cls = signal_for_premium(sp, threshold, r.get("subscribe_status", ""), redeem)
        row = dict(r)
        row["signal"], row["signal_cls"] = sig_text, sig_cls
        out.append(row)
    def _rank(r):
        st = r.get("subscribe_status")
        return 0 if st == "限大额申购" else (1 if st == "开放申购" else 2)
    def _est(r):
        e = r.get("est_premium")
        return e if e is not None else (r.get("premium") or 0)
    out.sort(key=lambda r: (_rank(r), -_est(r), -(r.get("turnover") or 0)))
    return out[:top_n]

def serve_top_from_snapshot(date, threshold, dgate, top_n=20):
    """优先从全量快照秒回；快照缺失/过期才走完整冷算（并填充快照）。
    快照判据：日期匹配 + 有行即用（不卡 TTL）——onrender 美西节点取不到东财行情，
    冷算只会产出缩水+全部回退官方净值的劣质榜单；磁盘快照是本机/自动化在国内
    定时算好的完整结果，日期一致时直接秒回，保证线上 TOP 与排行口径一致。"""
    with _TOP_SNAP_LOCK:
        snap = (dict(_TOP_SNAPSHOT) if (_TOP_SNAPSHOT["date"] == date
                and _TOP_SNAPSHOT["rows"]) else None)
    if snap:
        rows = _top_finalize(snap["rows"], threshold, dgate, top_n)
        return {"date": date, "threshold": threshold, "dgate": dgate,
                "universe": snap["universe"], "tradable": snap["tradable"],
                "candidates": snap["candidates"], "count": len(rows), "rows": rows,
                "filter_trace": snap.get("filter_trace", {}),
                "tz": "北京时间 (UTC+8)", "server_bj": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
                "server_ts": int(time.time()), "snapshot": True}
    return compute_top_arbitrage(date, threshold, dgate, top_n)


def compute_top_arbitrage(target_date=None, threshold=1.5, dgate=TOP_DISCOUNT_GATE, top_n=20):
    """全市场 LOF 中筛选 TOP 套利机会（网页3数据源）。

    同时满足：
      1. 当天在 A 股场内可交易（有实时行情且最近交易日成交量>0）；
      2. 二级市场可交易规模（场内流通市值）>= 1 亿元（非总规模）；
      3. 限购金额 > 1 元，或不限购（暂停申购视为限购 0 元，不满足）；
      4. 估算溢价率 >= threshold(默认1.5%)，或 估算溢价率 < dgate(默认-2%) 且开放(场内)赎回。
    筛选后【不】按筛选条件排序，而是用默认排序：① 申购状态（限大额申购 > 开放申购）② 估算溢价由高到低 ③ 成交额由大到小，取前 top_n 名；估算算法与排行表 compute_one_rank 完全一致。
    """
    if not target_date:
        # 默认取【已收盘】的最近交易日，而非今天：避免开盘前/盘中把标签写成当天、
        # 数值却仍是上一交易日的错位（见 _last_closed_trading_day 说明）。
        target_date = _last_closed_trading_day()
    _t0 = time.time()
    def _lap(tag):
        print(f"    [TOP榜·耗时] {tag}: {time.time() - _t0:.1f}s", flush=True)
    lof = fetch_all_lof_codes()                      # 缓存 12h，几乎瞬时
    codes = [c for c, _, _ in lof]
    _lap(f"LOF清单 {len(lof)}只")
    # 前置取数：流通市值串行优先（push2 分页请求对并发敏感，与行情/场内表并行时容易超时失败），
    # 其余三项（行情/场内表/汇率）并行发起。
    float_caps = fetch_float_market_cap(codes)   # push2delay 批量取 f21（场内流通市值）
    _lap(f"场内流通市值 {len(float_caps)}只")
    with ThreadPoolExecutor(max_workers=3) as _fe:
        f_q = _fe.submit(fetch_lof_quotes, codes)
        f_m = _fe.submit(fetch_market_fund_table)    # 已降超时至 25s
        f_fx = _fe.submit(fetch_fx)
        quotes = f_q.result()
        market = f_m.result()
        fx_map = f_fx.result()
    _lap("行情/场内表/汇率")

    # -- 粗筛：可交易 + 非纯债 + 有净值 + 二级市场流通规模 ≥ 1 亿元 即进入精算候选 --
    # 注意：此处【不再】用官方净值溢价门槛预筛候选。原因：限大额/QDII 基金的
    # 估算溢价常远高于官方溢价（净值滞后 T+1/T+2 + 标的当日波动），若按官方溢价
    # 高低挑前 N 名，这类高估算溢价的套利目标会被漏选。实测案例：160216 国泰商品
    # 官方 -1.14% 但估算 +2.86%、501312 华宝海外科技 官方 -1.35% 但估算 +1.92%、
    # 161729 招商瑞利 官方 -0.35% 但估算 -2.29%，均因官方溢价小未进候选池。故对
    # 所有可交易、非纯债、有净值的基金精算估算溢价，再由终筛四条件 + 排序取 TOP。
    # 二级市场流通规模（场内流通市值，亿元）：东财 push2 LOF 板块(MK0025-0028)全市场拉取，
    # 在此做初筛——push2 有规模且 < 1 亿直接剔除；push2 未覆盖(sc=None)的也剔除，
    # 因为东财场内板块未收录 = 场内不活跃，二级市场规模大概率不达标（用户硬条件 > 1 亿）。
    # 仅当 push2 整体失败（float_caps 为空字典）时，None 回退到终筛 F10 总规模兜底。
    fc_available = bool(float_caps)   # push2 是否正常返回了数据
    print(f"    [TOP榜] float_caps={len(float_caps)}只 fc_available={fc_available}", flush=True)
    # 粗筛前并发预取 push2 未覆盖基金的 F10 总规模：东财 LOF 板块(MK0025-0028)覆盖不全，
    # 大量二级规模≥1亿 的 LOF 不在其中；若直接剔除会漏候选。用 F10 总规模兜底预取，
    # 使粗筛规模判断更准确，同时避免这些基金进入精算拖慢（终筛亦可复用此结果）。
    # 注意：F10 规模【不再】对全部未覆盖基金预取。旧实现会对 610 只逐个打 fundf10
    # 页面，实测全量触发东财 514 限频、耗时 54s 且结果全部为 None（等于白跑），还把候选
    # 从 233 只误杀到 122 只。改为：先用 ulist.np 的场内流通市值过筛，仅对通过
    # 「可交易+非债基+有净值」但 ulist 未覆盖的少数候选再补 F10 总规模（见 _ensure_scale）。
    f10_scale = {}
    tradable = 0
    n_after_bond = 0
    n_after_nav = 0
    n_after_scale = 0
    cands = []
    need_scale = []          # ulist 未覆盖、待 F10 兜底的候选
    for code, name, ftype in lof:
        q = quotes.get(code)
        if not q or q["volume"] <= 0:
            continue        # 条件1：场内无行情/无成交
        tradable += 1
        if is_bond_fund(ftype):
            continue        # 非债基：债基/含债/固收类型剔除（用户硬条件，不参与候选/精算/入榜）
        n_after_bond += 1
        mk = market.get(code)
        if not mk or not mk["nav"]:
            continue        # 条件：有最新净值
        n_after_nav += 1
        sc = float_caps.get(code)
        if sc is None:
            need_scale.append(code)     # 场内流通市值缺失 → 稍后用 F10 总规模兜底判定
            continue
        if sc < 1.0:
            continue        # 场内可交易规模 < 1 亿：剔除
        n_after_scale += 1
        cands.append(code)

    # F10 兜底：只对上面「场内规模缺失」的候选补取总规模（数量通常 < 60，且结果落盘复用）
    if need_scale:
        print(f"    [TOP榜] F10 总规模兜底 {len(need_scale)} 只（ulist 未覆盖）...", flush=True)
        with ThreadPoolExecutor(max_workers=6) as _fe2:
            _futs = {_fe2.submit(fetch_fund_scale, c): c for c in need_scale}
            for _f in as_completed(_futs):
                _c = _futs[_f]
                try:
                    f10_scale[_c] = _f.result()
                except Exception:
                    f10_scale[_c] = None
        for code in need_scale:
            sc = f10_scale.get(code)
            if sc is not None and sc >= 1.0:
                n_after_scale += 1
                cands.append(code)
        _persist_data()      # 规模缓存落盘，避免下次冷启动重复抓取
        _lap(f"F10总规模兜底 {len(need_scale)}只")
    # 粗筛漏斗：逐阶段剔除数量，便于网页透明展示「为什么候选这么多/这么少」并核对规模过滤是否生效
    filter_trace = {
        "universe": len(lof),
        "tradable": tradable,
        "excluded_bond": tradable - n_after_bond,      # 非债基剔除
        "excluded_no_nav": n_after_bond - n_after_nav,  # 无净值剔除
        "excluded_scale": n_after_nav - n_after_scale,  # 场内规模<1亿/不明 剔除
        "covered_by_float_cap": len(float_caps),        # ulist.np 取到场内流通市值的只数
        "f10_fallback": len(need_scale),                # 走 F10 总规模兜底的只数
        "candidates": len(cands),                       # 进入精算的候选（非债基 + 规模≥1亿 + 有净值）
    }

    _lap(f"粗筛完成：候选 {len(cands)} 只")
    # -- 国内指数 LOF：一次性批量取跟踪指数日内涨跌，供 compute_one_rank 估算当日净值 --
    _idx_meta = {}
    for c in cands:
        _dm = DOMESTIC_INDEX_MAP.get(c)
        if _dm:
            _idx_meta[_dm[0]] = (_dm[1], _dm[2] if len(_dm) > 2 else 1.0)
    _idx_chg_map = {}
    if _idx_meta:
        try:
            _idx_chg_map = get_index_chg_batch(_idx_meta)
            print(f"    [TOP榜] 跟踪指数日内涨跌取数 {len(_idx_chg_map)}/{len(_idx_meta)} 只",
                  flush=True)
        except Exception as e:
            print(f"    [TOP榜] 指数涨跌批量取数失败: {e}", flush=True)
            _idx_chg_map = {}

    # -- 精算：复用排行表算法（估算溢价） --
    # 方案B冷启动优化：先并发预热所有候选的前十大重仓与持仓股实时快照，
    # 使下方精算循环内 fetch_holdings/快照均命中缓存、零额外请求，避免逐只打行情拖过 onrender 超时。
    _prefetch_top_holdings(cands)
    _lap("持仓预热")
    rows = []
    with ThreadPoolExecutor(max_workers=RANKING_MAX_WORKERS) as exe:
        rk_futs = {exe.submit(compute_one_rank, c, target_date, fx_map, threshold,
                              _idx_chg_map): c for c in cands}
        for f in as_completed(rk_futs):
            c = rk_futs[f]
            try:
                r = f.result()
            except Exception as e:
                print(f"    [TOP榜] {c} 精算失败: {e}")
                continue
            if not r.get("error"):
                rows.append(r)

    # -- 终筛：先把「数据类」条件(规模/申赎/限购/流动性)固化进候选行；
    #    阈值类条件(溢价>=threshold 或 折价<dgate)延后到 _top_finalize，
    #    这样全量快照可服务任意 threshold/dgate 的视图（对齐 haoetf 秒回）。--
    base_rows = []
    for r in rows:
        code = r["code"]
        mk = market.get(code) or {}
        # 申赎状态/限购额：东财场内表为准（比 F10 正文解析更全），F10 兜底
        subscribe = mk.get("subscribe") or r.get("subscribe_status") or ""
        redeem = mk.get("redeem") or r.get("redeem_status") or ""
        limit = mk.get("limit") if mk else r.get("purchase_limit")
        sp = r.get("est_premium") if r.get("est_premium") is not None else r.get("premium")
        if sp is None:
            continue
        scale = float_caps.get(code)
        if scale is None:
            scale = f10_scale.get(code)      # 复用粗筛预取的 F10 规模
        if scale is None:
            scale = fetch_fund_scale(code)   # 单只回落：仍缺失时再取总规模兜底
        r["scale"] = scale
        r["subscribe_status"] = subscribe
        r["redeem_status"] = redeem
        r["purchase_limit"] = limit
        r["purchase_limit_text"] = ("不限购" if (limit is None and subscribe in SUBSCRIBE_OPEN)
                                    else (f"{limit:g}元" if limit is not None else "—"))
        # 成交额(万元)：直接复用已抓取的全市场行情字段[37]，无需额外请求
        r["turnover"] = quotes.get(code, {}).get("amount")
        # 条件2/3：规模>=1亿、可申购状态、限购>1元（阈值类条件留到 _top_finalize）
        if scale is None or scale < 1.0:
            continue
        if subscribe not in SUBSCRIBE_OPEN:
            continue
        if limit is not None and limit <= 1:
            continue
        base_rows.append(r)
    _lap(f"精算+终筛完成：入榜候选 {len(base_rows)} 只")
    # 填充全量快照（阈值前），使 /api/top 对任意 threshold/dgate 秒回；并落盘
    with _TOP_SNAP_LOCK:
        _TOP_SNAPSHOT.update(ts=time.time(), date=target_date, universe=len(lof),
                             tradable=tradable, candidates=len(cands),
                             filter_trace=filter_trace, rows=base_rows)
    # 近5日入选历史：估算溢价≥1.5% 的溢价套利入选名单（供 TOP 页统计表）
    try:
        history_append("top", target_date, _top_history_entries(base_rows, threshold))
    except Exception as _e:
        print(f"    [历史] TOP 记录失败: {_e}")
    _persist_top_snapshot()
    out = _top_finalize(base_rows, threshold, dgate, top_n)
    return {"date": target_date, "threshold": threshold, "dgate": dgate,
            "universe": len(lof), "tradable": tradable, "candidates": len(cands),
            "count": len(out), "rows": out, "filter_trace": filter_trace,
            "tz": "北京时间 (UTC+8)",
            "server_bj": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
            "server_ts": int(time.time()), "snapshot": False}


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
        sig, _ = signal_for_premium(r["est_premium"] if r["est_premium"] is not None else r["premium"],
                                    THRESHOLD, control.get("subscribe_status", ""), control.get("redeem_status", ""))
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

# ---------------------------------------------------------------------------
# 交互网页界面一（由 / 返回，数据通过 /api/data 拉取）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 交互网页界面二（由 /ranking 返回，数据通过 /api/ranking 拉取）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 交互网页界面三（由 /top 返回，数据通过 /api/top 拉取）：全市场 LOF TOP 套利榜
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PWA 资源（manifest / service worker / 图标）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------


# ===== 可转债折价套利引擎（纯标准库，复用 bj_now/_is_trading_day）=====
# -*- coding: utf-8 -*-
# ===== 可转债折价套利引擎（纯标准库，无 numpy/pandas）=====
# 数据源：东方财富 push2delay 可转债全列表（一次分页拉全市场 ~320 只，秒级完成）
# 套利定义：转股溢价率 < 0（折价）即具备"买入转债+融券卖空正股+转股"的无风险套利条件
#   套利收益率(粗略,未扣费) = (转股价值 - 转债现价) / 转债现价 * 100%
# 复用 fund_arb 既有定义：bj_now / _is_trading_day（注入后自动复用，下方 try/except 兜底独立运行）
import json, time, threading, os
from urllib.request import urlopen, Request

try:
    bj_now
except NameError:
    def bj_now():
        return datetime.utcnow() + timedelta(hours=8)

try:
    _is_trading_day
except NameError:
    def _is_trading_day(dt):
        return dt.weekday() < 5  # 简化：仅排除周末，假期由 fund_arb 版本覆盖

CB_CFG = dict(
    top_n=10,                  # 榜单条数
    scan_hour=15,              # 每交易日自动扫描时刻（收盘后，确保东财入库）
    scan_minute=15,            # 15:15 收盘数据已稳定
    min_arb_pct=-100.0,        # 套利收益率下限（仅作保险，正常取 >0 即折价）
    exclude_st=True,           # 排除 ST/*ST 正股（强赎/退市风险）
    fallback_if_empty=True,    # 无严格折价时降级显示"最接近折价"的前 N 只
)
CB_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cb_cache.json")
CB_SNAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cb_snapshot.json")
_CB_LOCK = threading.Lock()
_CB = dict(result=None, scanning=False, error="", progress=dict(done=0, total=0, phase=""))

_UT = "fa5fd1943c7b386f172d6893dbfba10b"
_CB_FIELDS = "f12,f13,f14,f2,f5,f232,f234,f236,f237,f238,f240,f243"  # f5=成交量(手)，已停牌债成交量为0；f240=正股实时价


def _cb_http_get(url, timeout=20):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0",
                                "Referer": "https://quote.eastmoney.com/"})
    return urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def cb_fetch_list():
    """分页拉取东方财富全市场可转债（MK0354），返回原始 diff 列表。"""
    items = []
    for pn in range(1, 6):
        url = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1"
               "&fltt=2&invt=2&fs=b:MK0354&fields=%s&ut=%s" % (pn, _CB_FIELDS, _UT))
        try:
            d = json.loads(_cb_http_get(url))
            diff = (d.get("data") or {}).get("diff") or []
            if not diff:
                break
            items += diff
            if len(diff) < 100:
                break
        except Exception as e:
            print("    [可转债] 第%d页拉取失败: %s" % (pn, e))
            break
    return items


def cb_compute(items, progress=None):
    """计算套利收益率、过滤、排序、取前 N。返回结果 dict。"""
    t0 = time.time()
    today = int(bj_now().strftime("%Y%m%d"))
    # best-effort：未来 2 个交易日内将停牌的可转债代码集合（接口不可用则空集）
    soon = _cb_suspended_soon_set()
    suspended_already = 0
    suspended_soon = 0
    rows = []
    for it in items:
        try:
            code = str(it.get("f12"))
            name = it.get("f14")
            price = float(it.get("f2"))
            cv = float(it.get("f236"))
            prem = float(it.get("f237"))            # 转股溢价率(%)：<0 即折价(套利空间)
            stock_code = str(it.get("f232") or "")
            stock_name = it.get("f234") or ""
            stock_price = it.get("f240")           # 正股实时价（东财字段）
            start = str(it.get("f243") or "")
            dlow = it.get("f238")
            volume = float(it.get("f5") or 0)       # 成交量(手)
        except (TypeError, ValueError):
            continue
        if price <= 0 or cv <= 0:
            continue
        # 可转债已停牌（无成交量）→ 不推送
        if volume <= 0:
            suspended_already += 1
            continue
        # 可转债将于 2 交易日内停牌 → 不推送
        if code in soon:
            suspended_soon += 1
            continue
        arb = (cv - price) / price * 100.0          # 套利收益率(折价率)
        # 转股价反推：转股价值 = 100 / 转股价 × 正股价 → 转股价 = 100 × 正股价 / 转股价值
        convert_price = None
        if stock_price not in (None, "", "-"):
            try:
                convert_price = round(100.0 * float(stock_price) / cv, 3)
            except (TypeError, ValueError, ZeroDivisionError):
                convert_price = None
        in_conv = len(start) >= 8 and int(start) <= today   # 已进入转股期
        is_st = bool(stock_name) and ("ST" in stock_name)
        market = "sh" if str(it.get("f13")) == "1" else "sz"
        rows.append(dict(
            code=code, market=market, name=name,
            price=round(price, 3), convert_value=round(cv, 3),
            premium=round(prem, 3), arb=round(arb, 3),
            stock_code=stock_code, stock_name=stock_name,
            stock_price=(round(float(stock_price), 3) if stock_price not in (None, "", "-") else None),
            convert_price=convert_price,
            double_low=round(price + prem, 2),
            convert_start=start, in_conv=in_conv, is_st=is_st,
        ))
        if progress:
            progress(len(rows), len(items), "计算中")
    # 严格折价：套利收益率>0 且 转股期内 且 非ST
    strict = [r for r in rows if r["arb"] > 0 and r["in_conv"] and not r["is_st"]]
    strict.sort(key=lambda x: x["arb"], reverse=True)
    for r in strict:
        r["is_discount"] = True
    picks = strict[:CB_CFG["top_n"]]
    mode = "strict"
    # 严格折价不足 N 只时，自动补足"最接近折价"的正溢价标的，凑满前 N（标注 is_discount=False）
    if len(picks) < CB_CFG["top_n"] and CB_CFG["fallback_if_empty"]:
        seen = {p["code"] for p in picks}
        cand = [r for r in rows if r["in_conv"] and not r["is_st"]
                and r["arb"] <= 0 and r["code"] not in seen]
        cand.sort(key=lambda x: x["arb"], reverse=True)
        for r in cand:
            if len(picks) >= CB_CFG["top_n"]:
                break
            r["is_discount"] = False
            picks.append(r)
        mode = "mixed" if picks else "fallback"
        if mode == "fallback":
            for r in picks:
                r["is_discount"] = False
    for i, p in enumerate(picks):
        p["rank"] = i + 1
    elapsed = round(time.time() - t0, 1)
    # trade_date 取数据实际对应的交易日：非交易日回溯到最近一个交易日，
    # 避免标签(如周日8/23)与可转债真实涨跌幅(周五8/21收盘)对不上。
    _now_bj = bj_now()
    if _is_trading_day(_now_bj):
        _real_td = _now_bj.strftime("%Y-%m-%d")
    else:
        _d = _now_bj
        while not _is_trading_day(_d):
            _d = _d - timedelta(days=1)
        _real_td = _d.strftime("%Y-%m-%d")
    return dict(
        trade_date=_real_td,
        kline_last_date=_real_td,
        updated=_now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        picks=picks, total_picks=len(picks), mode=mode,
        stats=dict(universe=len(rows), strict=len(strict),
                   discount=len(strict)),
        suspended_stats=dict(already=suspended_already, soon=suspended_soon,
                             soon_source=_cb_soon_source),
        elapsed=elapsed,
    )


def _cb_next_trading_days(n):
    """返回从明天起的第 n 个交易日的 date 对象列表。"""
    out = []
    d = bj_now()
    while len(out) < n:
        d = d + timedelta(days=1)
        if _is_trading_day(d):
            out.append(d.date())
    return out


_cb_soon_source = "unavailable"


def _cb_suspended_soon_set():
    """Best-effort：返回未来 2 个交易日内将停牌的可转债代码集合。

    数据源：东方财富停牌日历(RPT_DMSK_TS_STOCKNEW)。依赖外网，
    若网络/字段不可用则优雅降级返回空集，绝不阻断主流程。
    """
    global _cb_soon_source
    try:
        days = _cb_next_trading_days(2)
        if not days:
            return set()
        last = days[-1]
        cols = "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE"
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName="
               "RPT_DMSK_TS_STOCKNEW&client=PC&source=WEB&pageSize=1000&pageNumber=1&"
               "columns=%s" % cols)
        d = json.loads(_cb_http_get(url, timeout=20))
        rows = (d.get("result") or {}).get("data") or []
        if not rows:
            _cb_soon_source = "eastmoney:empty"
            return set()
        # 容错解析：自动定位"代码列"与"日期列"
        ckey = dkey = None
        for k in rows[0]:
            ku = str(k).upper()
            if ckey is None and ("CODE" in ku or "代码" in str(k)):
                ckey = k
            if dkey is None and ("DATE" in ku or "日期" in str(k) or "停牌" in str(k)):
                dkey = k
        if not ckey or not dkey:
            _cb_soon_source = "eastmoney:no-columns"
            return set()
        out = set()
        for r in rows:
            try:
                dv = str(r.get(dkey) or "").replace("-", "").replace("/", "").strip()
                if len(dv) >= 8 and dv.isdigit():
                    sdate = datetime(int(dv[:4]), int(dv[4:6]), int(dv[6:8])).date()
                    if bj_now().date() <= sdate <= last:
                        out.add(str(r.get(ckey)))
            except Exception:
                continue
        _cb_soon_source = "eastmoney:%d rows,%d matched" % (len(rows), len(out))
        return out
    except Exception as e:
        _cb_soon_source = "unavailable:%s" % e
        print("    [可转债] 停牌日历获取失败，跳过“2日内停牌”过滤: %s" % e)
        return set()


def cb_scan(progress=None):
    items = cb_fetch_list()
    return cb_compute(items, progress=progress)


def _cb_load_disk():
    """启动时回填磁盘缓存；若磁盘缓存缺失（如云平台重新部署后本地文件系统被重置），
    则回退到仓库内置的快照文件 cb_snapshot.json，保证页面打开即有数据，无需等待重扫。"""
    try:
        data = None
        src = ""
        if os.path.exists(CB_CACHE_FILE):
            with open(CB_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            src = "磁盘缓存"
        if not (isinstance(data, dict) and data.get("picks") is not None) and os.path.exists(CB_SNAP_FILE):
            with open(CB_SNAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            src = "内置快照"
        if isinstance(data, dict) and data.get("picks") is not None:
            with _CB_LOCK:
                _CB["result"] = data
            print("    [可转债] 载入%s：%s 命中 %d 只" %
                  (src, data.get("updated"), data.get("total_picks")))
    except Exception as e:
        print("    [可转债] 缓存载入失败: %s" % e)


def _cb_save_disk(res):
    try:
        with open(CB_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        # 同步更新内置快照（仓库随源码提交，云端重部署后首个请求即可秒回数据）
        with open(CB_SNAP_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    except Exception as e:
        print("    [可转债] 磁盘缓存写入失败: %s" % e)
    # 近5日入选历史：严格折价入选名单（供可转债页统计表）
    try:
        history_append("cb", res.get("trade_date", ""), _cb_history_entries(res))
    except Exception as e:
        print("    [历史] 可转债记录失败: %s" % e)


def cb_run_scan_bg():
    with _CB_LOCK:
        if _CB["scanning"]:
            return False
        _CB["scanning"] = True
        _CB["error"] = ""
        _CB["progress"] = {"done": 0, "total": 0, "phase": "启动中"}

    def _prog(done, total, phase):
        with _CB_LOCK:
            _CB["progress"] = {"done": done, "total": total, "phase": phase}

    def _run():
        try:
            res = cb_scan(progress=_prog)
            with _CB_LOCK:
                _CB["result"] = res
            _cb_save_disk(res)
            print("    [可转债] 扫描完成：%d 只 → 命中 %d 只，耗时 %ss，模式 %s"
                  % (res["stats"]["universe"], res["total_picks"], res["elapsed"], res["mode"]))
        except Exception as e:
            with _CB_LOCK:
                _CB["error"] = str(e)
            print("    [可转债] 扫描失败: %s" % e)
        finally:
            with _CB_LOCK:
                _CB["scanning"] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def cb_api_payload(force=False):
    """/api/cb 响应体：立即返回缓存+扫描状态；缓存过期或强制则后台重扫。"""
    with _CB_LOCK:
        res = _CB["result"]
        scanning = _CB["scanning"]
        prog = dict(_CB["progress"])
        err = _CB["error"]
    today = bj_now().strftime("%Y-%m-%d")
    # stale 仅用于前端展示提示（数据是否为最近交易日），不再作为自动重扫触发条件。
    stale = (res is None) or (res.get("trade_date") != today)
    # 智能冻结：非更新窗口（周末/夜间/盘中早段）不自动重扫，直接复用缓存静态展示；
    # 仅在交易日 14:45 后且当日尚未扫描时才自动刷。force=1 任何时候都可手动触发。
    if (force or _auto_refresh_due(res)) and not scanning:
        cb_run_scan_bg()
        scanning = True
    if res is None:
        return dict(scanning=scanning, progress=prog, error=err,
                    picks=[], stats=dict(universe=0, picks=0, strict=0, discount=0),
                    updated="", total_picks=0, mode="")
    out = dict(res)
    out["scanning"] = scanning
    out["progress"] = prog
    out["error"] = err
    out["stale"] = stale
    _ok, _warn = _date_integrity(res.get("trade_date"))
    out["date_ok"] = _ok
    out["date_warning"] = _warn
    return out


class CbScheduler(threading.Thread):
    """常驻线程：每交易日 14:45 自动扫描一次。"""
    def run(self):
        hour = int(os.environ.get("CB_SCAN_HOUR", str(CB_CFG["scan_hour"])))
        minute = int(os.environ.get("CB_SCAN_MINUTE", str(CB_CFG["scan_minute"])))
        while True:
            now = bj_now()
            cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= now:
                cand = cand + timedelta(days=1)
            while not _is_trading_day(cand):
                cand = cand + timedelta(days=1)
            sleep_s = (cand - bj_now()).total_seconds()
            if sleep_s > 0:
                time.sleep(min(sleep_s, 3600))
                continue
            if not _CB["scanning"]:
                cb_run_scan_bg()
            time.sleep(60)


(
    '<!DOCTYPE html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n<meta name="theme-color" content="#0d1117">\n<link rel="manifest" href="/manifest.json">\n<link rel="apple-touch-icon" href="/icon-192.png">\n<title>口袋支点量化选股 V1.0</title>\n<style>'
    + COMMON_CSS
    + '</style></head><body>\n'
    + '<div class="wrap">\n<div class="topbar">\n  <div class="titles">\n    <h1>口袋支点量化选股 <span class="ver">V1.0</span></h1>\n    <div class="sub">基于欧奈尔 CAN SLIM · 米勒维尼趋势模板/VCP · 斯泰恩超级强势股，全市场扫描口袋支点买点。每交易日 14:50（收盘前 10 分钟）自动更新。</div>\n  </div>\n  <div class="top-actions">\n    <a class="theme-btn" href="/" title="LOF/ETF 套利数据看板">套利看板</a>\n    <a class="theme-btn" href="/ranking" title="基金溢价排行表">排行表</a>\n    <a class="theme-btn" href="/top" title="全市场 LOF TOP 套利机会">TOP套利</a>\n    <span id="staleBadge" class="stale-badge" style="display:none"><span class="dot"></span>扫描中</span>\n    <button id="themeBtn" class="theme-btn" onclick="toggleTheme()" title="切换日间 / 夜间模式"><span id="themeIcon">🌙</span><span id="themeLbl">夜间</span></button>\n  </div>\n</div>\n\n<div class="tzline">数据更新时间（北京时间）<b id="updated">—</b><span id="elapsedInfo"></span></div>\n\n<div class="panel">\n  <div class="field"><label>最低评分</label><input id="minScore" value="0" type="number" min="0" max="100" step="5"></div>\n  <div class="field"><label>最低 RS 评级</label><input id="minRs" value="0" type="number" min="0" max="99" step="5"></div>\n  <div class="field"><label>趋势模板下限</label><select id="minTt">\n    <option value="0">不限</option>\n    <option value="6">≥ 6 条</option>\n    <option value="7">≥ 7 条</option>\n    <option value="8">8 条全过</option>\n  </select></div>\n  <div class="field"><label>信号分级</label><select id="fGrade">\n    <option value="">全部</option>\n    <option value="S">S 级（全优）</option>\n    <option value="A">A 级（模板全过）</option>\n    <option value="B">B 级</option>\n    <option value="C">C 级（观察）</option>\n  </select></div>\n  <button id="btn" onclick="applyFilter()">筛选</button>\n  <button id="rescanBtn" onclick="rescan()" style="background:var(--panel);color:var(--title);border:1px solid var(--border)">立即重扫</button>\n  <div id="pick-count" class="fund-title"></div>\n</div>\n\n<div id="statusbar" class="statusbar" style="display:none"></div>\n<div id="summary" class="summary"></div>\n<div id="loading">加载中…</div>\n<div id="err"></div>\n<div class="tablebox" id="tablebox" style="display:none"><table <div class="tablebox" id="pivotHistBox">\n  <div class="chart-head"><b>近 5 个交易日 A 级及以上入选</b></div>\n  <div class="chart" id="pivotHist"><div class="empty">加载中…</div></div>\n</div>\n\n<div class="note">\n<b>方法论与用法</b>\n<ul>\n  <li><b>口袋支点</b>（Morales &amp; Kacher）：当日成交量 &gt; 过去 10 日所有<b>下跌日</b>的最大成交量，且收阳、实体阳线、收在振幅上半部、站上 50 日线、贴近 10 日线、未过度延伸、未跳空追高、非涨停 —— 共 13 条硬条件全过才算命中。</li>\n  <li><b>趋势模板 8 条</b>（Minervini 第二阶段）：现价 &gt; 150/200 日线、150 &gt; 200 日线、200 日线上行 1 个月、50 &gt; 150 &gt; 200 多头排列、现价 &gt; 50 日线、高于 52 周低点 30%、距 52 周高点 25% 内、RS ≥ 70。</li>\n  <li><b>评分权重</b>（2024-11~2026-07 全市场 32326 个信号回测标定）：趋势模板 40 + RS 22 + 支点质量 15 + VCP 10 + 距高点 8 + 行业 5。实证：趋势模板 8/8 超额 +2.22%，RS 80-90 超额 +2.05%，<b>大盘空头环境超额 -2.95%（择时优先级最高）</b>。</li>\n  <li><b>离场规则</b>：8% 硬止损（Minervini 铁律）+ 收盘跌破 50 日线离场，<b>不设固定止盈</b> —— 回测证明 25% 止盈会把最优组收益从 6.0% 砍到 4.5%。仓位按单笔 1% 风险预算反推。</li>\n  <li>大盘为<b>空仓/防御</b>时信号天然稀少，属纪律性表现，不是程序故障。本页为量化信号提示，不构成投资建议。</li>\n</ul>\n</div>\n</div>'
    + '<script>'
    + 'let RAW=null, POLL=null;\nconst GRADE_COLORS={"S":"#e6394a","A":"#fa8c16","B":"#1f6feb","C":"#8c8c8c"};\n\nfunction applyTheme(t){\n  document.documentElement.setAttribute(\'data-theme\', t);\n  const icon=document.getElementById(\'themeIcon\'), lbl=document.getElementById(\'themeLbl\');\n  if(icon) icon.textContent=(t===\'light\')?\'☀️\':\'🌙\';\n  if(lbl) lbl.textContent=(t===\'light\')?\'日间\':\'夜间\';\n  try{ localStorage.setItem(\'arb_theme\',t); }catch(e){}\n}\nfunction toggleTheme(){\n  applyTheme(document.documentElement.getAttribute(\'data-theme\')===\'light\'?\'dark\':\'light\');\n}\n(function(){ let t=\'dark\'; try{ t=localStorage.getItem(\'arb_theme\')||\'dark\'; }catch(e){} applyTheme(t); })();\n\nfunction esc(s){ return String(s==null?"":s).replace(/[&<>"\']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;"}[c])); }\nfunction fmtPct(v,plus){ if(v==null)return "—"; const s=(plus&&v>0)?"+":""; return s+Number(v).toFixed(2)+"%"; }\nfunction cls(v){ return v==null?"":(v>0?"pos":(v<0?"neg":"")); }\nfunction fmtAmt(w){ if(w==null)return "—"; return w>=10000?(w/10000).toFixed(2)+"亿":Math.round(w)+"万"; }\n\nasync function load(){\n  try{\n    const r=await fetch(\'/api/pivot?t=\'+Date.now());\n    const d=await r.json();\n    if(d.error) throw new Error(d.error);\n    RAW=d;\n    render(d);\n    // 扫描进行中 → 轮询进度\n    if(d.scanning){\n      document.getElementById(\'staleBadge\').style.display=\'inline-flex\';\n      if(!POLL) POLL=setInterval(load,4000);\n    }else{\n      document.getElementById(\'staleBadge\').style.display=\'none\';\n      if(POLL){ clearInterval(POLL); POLL=null; }\n    }\n  }catch(e){\n    document.getElementById(\'loading\').style.display=\'none\';\n    document.getElementById(\'err\').textContent=\'加载失败：\'+e.message;\n  }\n}\n\nfunction render(d){\n  document.getElementById(\'loading\').style.display=\'none\';\n  document.getElementById(\'err\').textContent=\'\';\n  document.getElementById(\'updated\').textContent=d.updated||\'—\';\n  const ei=document.getElementById(\'elapsedInfo\');\n  if(d.scanning){\n    const p=d.progress||{};\n    ei.textContent=\'\u3000｜\u3000正在扫描：\'+(p.phase||\'\')+\' \'+(p.done||0)+\'/\'+(p.total||0);\n  }else if(d.elapsed!=null){\n    ei.textContent=\'\u3000｜\u3000本次扫描耗时 \'+d.elapsed+\' 秒，覆盖 \'+((d.stats&&d.stats.universe)||0)+\' 只个股\';\n  }else{ ei.textContent=\'\'; }\n\n  // ---- 大盘状态条 ----\n  const m=d.market||{};\n  const bar=document.getElementById(\'statusbar\');\n  if(m.state){\n    const good=(m.state===\'进攻\'), bad=(m.state===\'空仓\'||m.state===\'防御\');\n    bar.className=\'statusbar \'+(good?\'ok\':(bad?\'warn\':\'info\'));\n    bar.style.display=\'flex\';\n    const col=good?\'#52c41a\':(bad?\'#ff4d4f\':\'#fa8c16\');\n    bar.innerHTML=\'<div class="status-item"><span class="status-label">大盘状态</span>\'\n      +\'<span class="badge" style="background:\'+col+\'22;color:\'+col+\';border:1px solid \'+col+\'55">\'+esc(m.state)+\'</span></div>\'\n      +\'<div class="status-item"><span class="status-label">市场健康度</span><span>\'+(m.score!=null?m.score:\'—\')+\' / 100</span></div>\'\n      +\'<div class="status-item"><span class="status-label">建议仓位上限</span><span>\'+(m.max_position!=null?m.max_position+\'%\':\'—\')+\'</span></div>\'\n      +\'<div class="status-item"><span class="status-label">25日分销日</span><span>\'+(m.dd_count!=null?m.dd_count+\' 个\':\'—\')+\'</span></div>\'\n      +\'<div class="status-item" style="margin-left:auto;color:var(--muted)">\'+esc(m.detail||\'\')+\'</div>\';\n  }else{ bar.style.display=\'none\'; }\n\n  // ---- 统计卡片（可点击筛选分级）----\n  const st=d.stats||{}, g=st.grade||{};\n  const cur=document.getElementById(\'fGrade\').value;\n  const cards=[[\'\',\'命中总数\',st.picks!=null?st.picks:0],\n               [\'S\',\'S 级（全优）\',g.S||0],[\'A\',\'A 级（模板全过）\',g.A||0],\n               [\'B\',\'B 级\',g.B||0],[\'C\',\'C 级（观察）\',g.C||0]];\n  document.getElementById(\'summary\').innerHTML=cards.map(function(x){\n    const on=(cur===x[0])?\' active\':\'\';\n    const c=GRADE_COLORS[x[0]];\n    return \'<div class="sitem clickable\'+on+\'" onclick="pickGrade(\\\'\'+x[0]+\'\\\')">\'\n      +\'<div class="l">\'+x[1]+\'</div><div class="v"\'+(c?\' style="color:\'+c+\'"\':\'\')+\'>\'+x[2]+\'</div></div>\';\n  }).join(\'\');\n\n  applyFilter();\n}\n\nfunction pickGrade(g){\n  document.getElementById(\'fGrade\').value=g;\n  render(RAW);\n}\n\nfunction applyFilter(){\n  if(!RAW) return;\n  const minScore=parseFloat(document.getElementById(\'minScore\').value)||0;\n  const minRs=parseFloat(document.getElementById(\'minRs\').value)||0;\n  const minTt=parseInt(document.getElementById(\'minTt\').value)||0;\n  const fg=document.getElementById(\'fGrade\').value;\n  const rows=(RAW.picks||[]).filter(function(p){\n    return p.score>=minScore && p.rs>=minRs && p.trend_pass>=minTt && (!fg||p.grade===fg);\n  });\n  document.getElementById(\'pick-count\').innerHTML=rows.length+\' 只 <small>符合当前条件</small>\';\n\n  if(!rows.length){\n    document.getElementById(\'tablebox\').style.display=\'none\';\n    document.getElementById(\'err\').textContent=(RAW.scanning\n      ? \'首次扫描进行中，请稍候（全市场约需 3-6 分钟）…\'\n      : \'当前条件下无命中。大盘走弱时信号稀少属正常，可放宽筛选条件。\');\n    return;\n  }\n  document.getElementById(\'err\').textContent=\'\';\n\n  let html=\'<thead><tr><th>名称/代码</th><th>级别</th><th>评分</th><th>RS</th><th>模板</th>\'\n    +\'<th>现价</th><th>涨跌</th><th>量能倍数</th><th>距52周高</th><th>止损</th><th>仓位</th><th>详情</th></tr></thead><tbody>\';\n  rows.forEach(function(p,i){\n    const gc=GRADE_COLORS[p.grade]||\'#8c8c8c\';\n    html+=\'<tr>\'\n      +\'<td class="name"><b>\'+esc(p.name)+\'</b> <a class="codelink" href="https://gu.qq.com/\'+esc(p.symbol)+\'" target="_blank" rel="noopener">\'+esc(p.code)+\'</a></td>\'\n      +\'<td><span class="badge" style="background:\'+gc+\'22;color:\'+gc+\';border:1px solid \'+gc+\'55">\'+esc(p.grade||\'—\')+\'</span></td>\'\n      +\'<td><b>\'+p.score+\'</b></td>\'\n      +\'<td>\'+p.rs+\'</td>\'\n      +\'<td>\'+p.trend_pass+\'/8</td>\'\n      +\'<td>\'+p.close+\'</td>\'\n      +\'<td class="\'+cls(p.chg_pct)+\'">\'+fmtPct(p.chg_pct,true)+\'</td>\'\n      +\'<td>\'+p.vol_x+\'×</td>\'\n      +\'<td class="\'+cls(p.off_high_pct)+\'">\'+fmtPct(p.off_high_pct,false)+\'</td>\'\n      +\'<td>\'+p.plan.stop+\'</td>\'\n      +\'<td>\'+p.plan.pos_pct+\'%</td>\'\n      +\'<td class="op-cell"><button style="padding:4px 10px;font-size:12px" onclick="toggleDetail(\'+i+\')">展开</button></td>\'\n      +\'</tr>\'\n      +\'<tr id="dt\'+i+\'" style="display:none"><td colspan="12" style="text-align:left;white-space:normal;padding:12px 14px;background:var(--row-hover)">\'\n      +detailHtml(p)+\'</td></tr>\';\n  });\n  document.getElementById(\'tbl\').innerHTML=html+\'</tbody>\';\n  document.getElementById(\'tablebox\').style.display=\'block\';\n  window.__rows=rows;\n}\n\nfunction detailHtml(p){\n  const tt=p.tt||{}, stine=p.stine||{}, pl=p.plan||{};\n  const mark=function(v){ return v?\'<span style="color:var(--neg)">✓</span>\':\'<span style="color:var(--muted)">✗</span>\'; };\n  let s=\'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">\';\n  // 趋势模板\n  s+=\'<div><b>Minervini 趋势模板 \'+p.trend_pass+\'/8</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\';\n  Object.keys(tt).forEach(function(k){ s+=mark(tt[k])+\' \'+esc(k)+\'<br>\'; });\n  s+=mark(p.rs>=70)+\' ⑧RS评级≥70（当前 \'+p.rs+\'）\';\n  s+=\'</div></div>\';\n  // 交易计划\n  s+=\'<div><b>交易计划（1% 风险预算）</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\'\n    +\'买入区间：<b>\'+pl.buy_low+\' ~ \'+pl.buy_high+\'</b><br>\'\n    +\'止损价：<b style="color:var(--pos)">\'+pl.stop+\'</b>（风险 \'+pl.risk_pct+\'%）<br>\'\n    +\'2R 目标：\'+pl.target2+\'\u30003R 目标：\'+pl.target3+\'<br>\'\n    +\'建议仓位：<b>\'+pl.pos_pct+\'%</b><br>\'\n    +\'离场：\'+esc(pl.exit_rule||\'\')\n    +\'</div></div>\';\n  // Stine + 关键指标\n  s+=\'<div><b>超级强势股（Stine）</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\';\n  Object.keys(stine).forEach(function(k){ s+=mark(stine[k])+\' \'+esc(k)+\'<br>\'; });\n  s+=\'</div></div>\';\n  s+=\'<div><b>关键指标</b><div style="margin-top:6px;line-height:1.9;font-size:12px">\'\n    +\'支点质量：\'+p.pocket_quality+\' / 100<br>\'\n    +\'VCP：\'+(p.vcp?\'成立\':\'不成立\')+\'（\'+p.vcp_score+\' 分）<br>\'\n    +\'量能 / 50日均量：\'+p.vol_vs_ma50+\'×<br>\'\n    +\'距 52 周低点：+\'+p.up_from_low_pct+\'%<br>\'\n    +\'成交额：\'+fmtAmt(p.amount_wan)+\'\u3000换手：\'+p.turn_rate+\'%<br>\'\n    +\'流通市值：\'+p.float_mcap+\' 亿\'\n    +\'</div></div>\';\n  s+=\'</div>\';\n  if(p.reasons&&p.reasons.length){\n    s+=\'<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border);font-size:12px">\'\n      +\'<b>入选理由</b>：\'+p.reasons.map(esc).join(\' ｜ \')+\'</div>\';\n  }\n  return s;\n}\n\nfunction toggleDetail(i){\n  const el=document.getElementById(\'dt\'+i);\n  if(el) el.style.display=(el.style.display===\'none\')?\'table-row\':\'none\';\n}\n\nasync function rescan(){\n  const b=document.getElementById(\'rescanBtn\');\n  b.disabled=true; b.textContent=\'已触发…\';\n  try{\n    await fetch(\'/api/pivot?force=1&t=\'+Date.now());\n    document.getElementById(\'staleBadge\').style.display=\'inline-flex\';\n    if(!POLL) POLL=setInterval(load,4000);\n  }catch(e){}\n  setTimeout(function(){ b.disabled=false; b.textContent=\'立即重扫\'; },3000);\n}\n\n[\'minScore\',\'minRs\'].forEach(function(id){\n  document.getElementById(id).addEventListener(\'keydown\',function(e){ if(e.key===\'Enter\') applyFilter(); });\n});\n[\'minTt\',\'fGrade\'].forEach(function(id){\n  document.getElementById(id).addEventListener(\'change\',applyFilter);\n});\n\nload();\nfunction renderPivotHist(){\n  var box=document.getElementById("pivotHist"); if(!box) return;\n  function esc2(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }\n  fetch("/api/history?type=pivot").then(function(r){return r.json();}).then(function(rows){\n    if(!rows||!rows.length){ box.innerHTML="<div class=\"empty\">近 5 个交易日暂无 A 级及以上入选记录</div>"; return; }\n    var html="<table class=\"histtbl\"><thead><tr><th>代码</th><th class=\"l\">名称</th><th>级别</th><th>入选日期</th><th>入选日价格</th></tr></thead><tbody>";\n    rows.forEach(function(r){\n      var plain=String(r.code||"").replace(/^(sh|sz|bj)/i,"");\n      var gcol=r.grade==="S"?"#ef4444":(r.grade==="A"?"#f59e0b":"#64748b");\n      html+="<tr><td><a class=\"codelink\" href=\""+(location.protocol==="file:"?"fund_arb.html":"/arb")+"?code="+plain+"\" target=\"_blank\">"+esc2(r.code)+"</a></td><td class=\"l\">"+esc2(r.name)+"</td><td style=\"color:"+gcol+";font-weight:700\">"+esc2(r.grade)+"</td><td>"+esc2(r.date)+"</td><td>"+(r.price==null?"—":Number(r.price).toFixed(2))+"</td></tr>";\n    });\n    html+="</tbody></table>";\n    box.innerHTML=html;\n  }).catch(function(e){ box.innerHTML="<div class=\"empty\">历史加载失败："+((e&&e.message)||String(e))+"</div>"; });\n}\nrenderPivotHist();\n\nsetInterval(function(){ if(!POLL) load(); }, 60000);\n\nif(\'serviceWorker\' in navigator){\n  window.addEventListener(\'load\',function(){\n    navigator.serviceWorker.register(\'/sw.js\').catch(function(err){ console.log(\'SW 注册失败：\',err); });\n  });\n}'
    + '</script>\n</body></html>'
)

class Handler(BaseHTTPRequestHandler):
    _DIR = os.path.dirname(os.path.abspath(__file__))

    def _serve_file(self, fname, fallback, ctype):
        # 若 fallback 本身就是二进制内容（如内嵌 PNG），直接 serve，不依赖磁盘文件
        if isinstance(fallback, (bytes, bytearray)):
            self._send(200, bytes(fallback), ctype)
            return
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
        # CORS：允许任意来源跨域读取（file:// 本地页 / 手机页 fetch 线上 JSON 快照时必需，
        # 否则浏览器拦截导致行业轮动等页面回退到内嵌旧兜底数据）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        # HTML 页面禁用缓存：改完代码重启服务后，浏览器普通刷新即可拿到新版，
        # 避免“本地 8000 端还是老版、需要硬刷新”的困扰（API 仍可被浏览器/中间层按需缓存）
        if "text/html" in ctype:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        # 安全响应头：防 MIME 嗅探 / 点击劫持 / referrer 泄露 / 非法嵌入
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; manifest-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
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
    _API_CACHE_TTL_TOP = 600   # 秒（TOP 套利榜全市场扫描重，缓存 10 分钟）

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

    def _refresh_async(self, key, ttl, producer):
        """后台异步重算并写回缓存（去重：同一 key 仅一个刷新线程在跑）。"""
        with _REFRESH_LOCK:
            if key in _REFRESHING:
                return
            _REFRESHING.add(key)
        def _run():
            try:
                val = producer()
                now = time.time()
                with self._API_CACHE_LOCK:
                    self._API_CACHE[key] = (now + ttl, val)
                _persist_api()
            except Exception as e:
                print(f"    [缓存] 后台刷新失败 {key}: {e}")
            finally:
                with _REFRESH_LOCK:
                    _REFRESHING.discard(key)
        _threading.Thread(target=_run, daemon=True).start()

    def _cached_or_stale(self, key, ttl, producer):
        """同 _cached，但内存未命中（或已过期）时：若内存/磁盘尚有旧值，立即返回该旧值并
        后台静默刷新（返回 (value, stale=True)）；完全无任何缓存时才同步计算（唯一慢路径，
        此时不再后台刷新，避免重复计算）。配合磁盘持久化(#2)，休眠/重启后首个请求也能秒回历史数据。"""
        now = time.time()
        with self._API_CACHE_LOCK:
            hit = self._API_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1], False
        stale_val = hit[1] if hit else None
        if stale_val is not None:
            self._refresh_async(key, ttl, producer)   # 有旧值→后台静默刷新（去重）
            return stale_val, True                    # 先返回旧数据，前端可据此提示“刷新中”
        val = producer()                              # 真正冷启动：同步计算（不再后台刷新）
        with self._API_CACHE_LOCK:
            self._API_CACHE[key] = (now + ttl, val)
        _persist_api()
        return val, False

    # ---- 行业轮动：申万一级行业 BK 代码映射（与 sector_dashboard.html 的 D.bk 一致） ----
    SECTOR_BK = {
        "电子": "BK1201", "通信": "BK1215", "计算机": "BK1207", "传媒": "BK0486", "电力设备": "BK1200",
        "机械设备": "BK1205", "国防军工": "BK1204", "汽车": "BK1211", "家用电器": "BK0456", "食品饮料": "BK0438",
        "纺织服饰": "BK0436", "轻工制造": "BK1212", "医药生物": "BK1216", "公用事业": "BK0427", "交通运输": "BK1210",
        "房地产": "BK1202", "商贸零售": "BK1213", "社会服务": "BK1214", "综合": "BK1217", "建筑材料": "BK1208",
        "建筑装饰": "BK1209", "农林牧渔": "BK0433", "基础化工": "BK1206", "钢铁": "BK0479", "有色金属": "BK0478",
        "石油石化": "BK0464", "煤炭": "BK0437", "环保": "BK0728", "美容护理": "BK1035", "银行": "BK1283",
        "非银金融": "BK1203",
    }

    def _sector_live_payload(self):
        """服务端代理东方财富行情；多镜像域名轮询+重试，失败优雅回退。
        返回 {"live":true,"industries":{name:{chg,main}}} 或 {"live":false,"industries":null,"error":...}"""
        import random
        secids = ",".join("90." + b for b in self.SECTOR_BK.values())
        fields = "f3,f12,f14,f62"
        # 多 host 轮询：随机镜像节点 + 主域名 + delay 域名，规避单点 502/限流
        hosts = ["%d.push2.eastmoney.com" % random.randint(1, 99) for _ in range(8)]
        hosts += ["push2.eastmoney.com", "push2delay.eastmoney.com"]
        UA_B = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        last_err = None
        for host in hosts:
            try:
                url = ("https://%s/api/qt/ulist.np/get?fields=%s&secids=%s"
                       "&ut=fa5fd1943c7b386f172d6893dbfba10b&_=%d" % (
                           host, fields, secids, int(time.time() * 1000)))
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA_B,
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
                    # 非交易日（周末/节假日）东方财富仍返回上一交易日收盘，
                    # 不能把日期误标为今天，否则前端会把非交易日插进 days 污染近5日统计
                    now_bj = datetime.now()
                    live_date = now_bj.strftime("%Y-%m-%d") if _is_trading_day(now_bj) else None
                    return {"live": True, "date": live_date,
                            "count": len(ind), "industries": ind,
                            "non_trading": live_date is None}
                last_err = "empty diff from " + host
            except Exception as e:
                last_err = str(e)
                continue
        return {"live": False, "industries": None, "error": last_err or "all hosts failed"}

    def do_OPTIONS(self):
        # CORS 预检：跨域页面（file:// 本地/手机）fetch 快照 JSON 前的 OPTIONS 请求
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        # 接口限流（静态资源与页面不限）
        if parsed.path.startswith("/api/") and not self._rate_ok():
            self._send(429, json.dumps({"error": "请求过于频繁，请稍后再试"}))
            return
        if parsed.path == "/manifest.json":
            self._send(200, MANIFEST_JSON, "application/manifest+json; charset=utf-8")
            return
        if parsed.path == "/sw.js":
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sw.js")
                with open(_sp, encoding="utf-8") as _sf:
                    self._send(200, _sf.read(), "application/javascript; charset=utf-8")
            except Exception:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
            return
        if parsed.path == "/api/sector_live":
            self._send(200, json.dumps(self._sector_live_payload(), ensure_ascii=False), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/history":
            qs = parse_qs(parsed.query)
            k = qs.get("type", [""])[0]
            try:
                days = max(1, min(10, int(qs.get("days", ["5"])[0])))
            except ValueError:
                days = 5
            if k not in ("pivot", "top", "cb"):
                self._send(400, json.dumps({"error": "type 应为 pivot/top/cb"}))
                return
            try:
                rows = history_payload(k, days)
                self._send(200, json.dumps({"type": k, "days": days, "rows": rows}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
            return
        if parsed.path == "/sector_data.json":
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_data.json")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "application/json; charset=utf-8")
            except Exception:
                self._send(404, "{}", "application/json; charset=utf-8")
            return
        if parsed.path == "/fish_snapshot.json":
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_snapshot.json")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "application/json; charset=utf-8")
            except Exception:
                self._send(404, "{}", "application/json; charset=utf-8")
            return
        if parsed.path == "/fish_model.json":
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_model.json")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "application/json; charset=utf-8")
            except Exception:
                self._send(404, "{}", "application/json; charset=utf-8")
            return
        if parsed.path == "/icon.svg":
            self._send(200, ICON_SVG, "image/svg+xml")
            return
        if parsed.path == "/icon-192.png":
            self._send(200, ICON_PNG_192, "image/png")
            return
        if parsed.path == "/icon-512.png":
            self._send(200, ICON_PNG_512, "image/png")
            return
        if parsed.path in ("/pivot_snapshot.json", "/cb_snapshot.json"):
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), parsed.path.lstrip("/"))
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "application/json; charset=utf-8")
            except Exception:
                self._send(404, "{}", "application/json; charset=utf-8")
            return
        if parsed.path in ("/yupen", "/yupen.html", "/fish_basin.html"):
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_basin.html")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "text/html; charset=utf-8")
            except Exception:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
            return
        if parsed.path in ("/watch", "/watch.html", "/watchlist.html"):
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.html")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    _html = _f.read().replace("</body>", EXPORT_BAR_HTML + "</body>")
                    self._send(200, _html, "text/html; charset=utf-8")
            except Exception:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
            return
        if parsed.path == "/watchlist.js":
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.js")
            try:
                with open(_fp, encoding="utf-8") as _f:
                    self._send(200, _f.read(), "application/javascript; charset=utf-8")
            except Exception:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
            return
        if parsed.path in ("/arb", "/arb.html"):
            self._send(200, PAGE_HTML.replace("</body>", EXPORT_BAR_HTML + "</body>"), "text/html; charset=utf-8")
            return
        if parsed.path in ("/ranking", "/ranking.html"):
            self._send(200, PAGE2_HTML.replace("</body>", EXPORT_BAR_HTML + "</body>"), "text/html; charset=utf-8")
            return
        if parsed.path in ("/top", "/top.html"):
            self._send(200, PAGE3_HTML.replace("</body>", EXPORT_BAR_HTML + "</body>"), "text/html; charset=utf-8")
            return
        if parsed.path in ("/pivot", "/pivot.html"):
            self._send(200, PAGE4_HTML.replace("</body>", EXPORT_BAR_HTML + "</body>"), "text/html; charset=utf-8")
            return
        elif parsed.path in ("/cb", "/cb.html"):
            self._send(200, PAGE5_HTML.replace("</body>", EXPORT_BAR_HTML + "</body>"), "text/html; charset=utf-8")
            return
        if parsed.path in ("/", "/index.html", "/sector_dashboard.html", "/sector"):
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_dashboard.html")
                with open(_sp, encoding="utf-8") as _sf:
                    self._send(200, _sf.read(), "text/html; charset=utf-8")
            except Exception:
                self._send(404, "Not Found", "text/plain; charset=utf-8")
            return
        if parsed.path == "/api/pivot":
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] in ("1", "true", "True")
            try:
                self._send(200, json.dumps(pivot_api_payload(force=force), ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "scanning": False, "picks": []}, ensure_ascii=False))
            return
        elif parsed.path == "/api/cb":
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] in ("1", "true", "True")
            try:
                self._send(200, json.dumps(cb_api_payload(force=force), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "scanning": False, "picks": []}, ensure_ascii=False))
            return
        if parsed.path == "/api/top":
            qs = parse_qs(parsed.query)
            date = qs.get("date", [""])[0]
            if date and not _valid_date(date):
                self._send(400, json.dumps({"error": "日期格式非法，应为 YYYY-MM-DD"}))
                return
            if not date:
                # 默认展示「最近 1 个已收盘交易日」的结果（静态），避免周末/非交易时段
                # 每次打开都触发实时抓取。用 _last_closed_trading_day 而非
                # _last_trading_day：后者在交易日开盘前会返回当天，导致标签与数值错位。
                date = _last_closed_trading_day()
            try:
                threshold = float(qs.get("threshold", ["1.5"])[0])
            except ValueError:
                threshold = 1.5
            threshold = max(0.1, min(10.0, threshold))
            try:
                dgate = float(qs.get("dgate", [str(TOP_DISCOUNT_GATE)])[0])
            except ValueError:
                dgate = TOP_DISCOUNT_GATE
            dgate = max(-10.0, min(-0.1, dgate))
            force = qs.get("force", ["0"])[0] in ("1", "true", "True")
            cache_key = f"top|{date}|{threshold}|{dgate}"
            bj = bj_now()
            today_str = bj.strftime("%Y-%m-%d")
            if force:
                # 手动刷新：若在交易日更新窗口内则刷新「今天」，否则刷新最近交易日快照。
                _date = today_str if (_is_trading_day(bj) and _in_update_window(bj)) else date
                try:
                    out = compute_top_arbitrage(_date, threshold, dgate, 20)
                    out = dict(out); out["stale"] = False; out["forced"] = True
                    with self._API_CACHE_LOCK:
                        self._API_CACHE[f"top|{_date}|{threshold}|{dgate}"] = (
                            time.time() + Handler._API_CACHE_TTL_TOP, out)
                    self._send(200, json.dumps(out, ensure_ascii=False))
                except Exception as e:
                    self._send(200, json.dumps({"error": str(e), "date": _date}, ensure_ascii=False))
                return
            # 非手动：仅当 date==今天 且处于更新窗口时才允许后台静默刷新；
            # 其余（周末/夜间/盘中早段/历史日期）直接复用快照，不触发抓取，秒回静态结果。
            if date == today_str and _in_update_window(bj):
                try:
                    data, stale = self._cached_or_stale(cache_key, Handler._API_CACHE_TTL_TOP,
                                                        lambda: serve_top_from_snapshot(date, threshold, dgate))
                    out = dict(data); out["stale"] = stale
                    self._send(200, json.dumps(out, ensure_ascii=False))
                except Exception as e:
                    self._send(200, json.dumps({"error": str(e), "date": date}, ensure_ascii=False))
            else:
                try:
                    data = serve_top_from_snapshot(date, threshold, dgate)
                    out = dict(data); out["stale"] = False
                    self._send(200, json.dumps(out, ensure_ascii=False))
                except Exception as e:
                    self._send(200, json.dumps({"error": str(e), "date": date}, ensure_ascii=False))
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
            force = qs.get("force", ["0"])[0] in ("1", "true", "True")
            cache_key = f"data|{code}|{days}|{threshold}|{start}|{end}|{underlying}|{mode}"
            try:
                if force:
                    # 手动强制刷新：绕过缓存直接重算（自选池"刷新"按钮需要拿到最新价）
                    data = compute(code, display_days=days, start=start, end=end, underlying=underlying, threshold=threshold, mode=mode)
                    data = dict(data); data["error"] = None; data["stale"] = False; data["forced"] = True
                    with self._API_CACHE_LOCK:
                        self._API_CACHE[cache_key] = (time.time() + Handler._API_CACHE_TTL, data)
                else:
                    data, stale = self._cached_or_stale(cache_key, Handler._API_CACHE_TTL,
                                        lambda: compute(code, display_days=days, start=start, end=end, underlying=underlying, threshold=threshold, mode=mode))
                    data = dict(data)
                    data["error"] = None
                    data["stale"] = stale
                self._send(200, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e), "code": code}, ensure_ascii=False))
            return
        if parsed.path == "/api/kline":
            qs = parse_qs(parsed.query)
            code = qs.get("code", ["sh000001"])[0]
            try:
                days = int(qs.get("days", ["30"])[0])
            except ValueError:
                days = 30
            days = max(2, min(500, days))
            sym = code
            if re.fullmatch(r"\d{6}", code):
                sym = ("sh" if code[0] in "569" else "sz") + code
            rows = []
            try:
                rows = fetch_kline_tencent(sym, days)
            except Exception:
                rows = []
            if not rows:
                try:
                    rows = fetch_kline_sina(sym, days)
                except Exception:
                    rows = []
            out = [{"date": d, "close": c} for d, c in rows]
            self._send(200, json.dumps({"code": code, "symbol": sym, "rows": out}, ensure_ascii=False),
                       "application/json; charset=utf-8")
            return
        if parsed.path == "/api/ranking":
            qs = parse_qs(parsed.query)
            date = qs.get("date", [""])[0]
            if date and not _valid_date(date):
                self._send(400, json.dumps({"error": "日期格式非法，应为 YYYY-MM-DD"}))
                return
            if not date:
                # 同 /api/top：默认取「最近已收盘交易日」。旧实现用 datetime.now()——
                # 既取了服务器本地时区（线上为 UTC）偏 8 小时，又会在开盘前把标签写成
                # 今天而数值回退到上一交易日（实测周一凌晨返回 date=08-31、价格却是 08-28 收盘价）。
                date = _last_closed_trading_day()
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
                data, stale = self._cached_or_stale(cache_key, Handler._API_CACHE_TTL_RANK,
                                    lambda: compute_ranking(codes, date, threshold))
                out = dict(data); out["stale"] = stale
                self._send(200, json.dumps(out, ensure_ascii=False))
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
            data = compute(code, display_days=days)
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
        if parsed.path == "/api/push/text":
            qs = parse_qs(parsed.query)
            date = qs.get("date", [""])[0]
            if date and not _valid_date(date):
                self._send(400, json.dumps({"error": "日期格式非法，应为 YYYY-MM-DD"}))
                return
            if not date:
                date = datetime.now().strftime("%Y-%m-%d")
            tok = os.environ.get("PUSH_LOCK_TOKEN")
            if tok and qs.get("token", [""])[0] != tok:
                self._send(403, json.dumps({"error": "token 校验失败"}))
                return
            text = build_arb_push_text(date)
            self._send(200, json.dumps({"date": date, "text": text}, ensure_ascii=False))
            return
        if parsed.path == "/api/push/lock":
            qs = parse_qs(parsed.query)
            date = qs.get("date", [""])[0]
            if not _valid_date(date):
                self._send(400, json.dumps({"error": "缺少或日期格式非法，应为 YYYY-MM-DD"}))
                return
            tok = os.environ.get("PUSH_LOCK_TOKEN")
            if tok and qs.get("token", [""])[0] != tok:
                self._send(403, json.dumps({"error": "token 校验失败"}))
                return
            cur = _push_lock_read()
            now = time.time()
            claimed = bool(cur and cur.get("date") == date and (now - float(cur.get("ts", 0))) < _PUSH_LOCK_WINDOW)
            self._send(200, json.dumps({"date": date, "claimed": claimed,
                                         "by": cur.get("by") if claimed else None}, ensure_ascii=False))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self._rate_ok():
            self._send(429, json.dumps({"error": "请求过于频繁，请稍后再试"}))
            return
        qs = parse_qs(parsed.query)
        tok = os.environ.get("PUSH_LOCK_TOKEN")
        if tok and qs.get("token", [""])[0] != tok:
            self._send(403, json.dumps({"error": "token 校验失败"}))
            return
        if parsed.path == "/api/push/lock":
            date = qs.get("date", [""])[0]
            if not _valid_date(date):
                self._send(400, json.dumps({"error": "缺少或日期格式非法，应为 YYYY-MM-DD"}))
                return
            who = qs.get("by", ["workbuddy"])[0]
            claimed = _push_lock_claim(date, who)
            self._send(200, json.dumps({"date": date, "claimed": claimed, "by": who}, ensure_ascii=False))
            return
        if parsed.path == "/api/push/unlock":
            date = qs.get("date", [""])[0]
            if not _valid_date(date):
                self._send(400, json.dumps({"error": "缺少或日期格式非法，应为 YYYY-MM-DD"}))
                return
            _push_lock_release(date)
            self._send(200, json.dumps({"ok": True, "date": date}, ensure_ascii=False))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass


# ---------------------------------------------------------------------------
# 飞书推送：交易日下午 2:45 自动扫描网页2(监控清单)与网页3(TOP榜)中
# |估算溢价| > 阈值的套利机会，按优先级排序取前 N 只推送到飞书机器人。
# 需在环境变量配置：FEISHU_WEBHOOK_URL（必填）；可选 FEISHU_WEBHOOK_SECRET（签名）、
# FEISHU_PUSH_THRESHOLD(默认2.0)、FEISHU_PUSH_MAX(默认5)、FEISHU_PUSH_HOUR/MINUTE。
# ---------------------------------------------------------------------------
def _is_trading_day(d):
    """简易交易日判断：周一至周五（节假日未穷举，可按需扩展 HOLIDAYS 集合）。"""
    return d.weekday() < 5


def _last_trading_day(now=None):
    """回溯到最近一个交易日（含当天）。周末/假日返回上一周五。

    注意：本函数会把「今天」也算作已产生的交易日，因此只适合做『数据是否过期』的
    比较基准。若要给榜单/快照选一个「数值真实存在」的日期标签，请用
    _last_closed_trading_day()——否则周一 09:00 会把标签写成当天，而数值仍是上周五的。
    """
    if now is None:
        now = bj_now()
    d = now
    while not _is_trading_day(d):
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _last_closed_trading_day(now=None):
    """最近一个【已收盘】的交易日：当天行情数据确实已经产生才返回当天。

    判定：今天必须是交易日且已过 15:15（_in_update_window，东财入库延迟已过）。
    否则回溯到上一交易日。用于 TOP 榜/快照的默认日期标签，杜绝「标签写今天、
    数值是上一交易日」的错位（用户最在意的日期口径问题）。
    """
    if now is None:
        now = bj_now()
    d = now
    if not (_is_trading_day(d) and _in_update_window(d)):
        d = d - timedelta(days=1)
    while not _is_trading_day(d):
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _in_update_window(now=None):
    """是否在『当日行情更新窗口』：交易日且北京时间 >= 15:15。

    选 15:15 而非 14:45：A股 15:00 收盘，东财行情/K线入库有约 10-15 分钟延迟，
    15:15 后抓到的才是当日真实收盘（trade_date 与涨跌幅严格同源=当日），
    避免盘中 14:45 扫到的 K 线末根仍是上一交易日而导致『上上个交易日』错位。
    此窗口之外（盘中早段、盘后 15:15 前、夜间、周末、假日）数据视为已收盘冻结。"""
    if now is None:
        now = bj_now()
    if not _is_trading_day(now):
        return False
    return now.hour > 15 or (now.hour == 15 and now.minute >= 15)


def _auto_refresh_due(res, trade_date_field="trade_date"):
    """判定是否应自动后台重扫（非手动 force）：

    触发条件（满足任一即允许自动刷）：
    1) 缓存为空（首次）；或
    2) 当前处于每日更新窗口(>=15:15) 且缓存 trade_date 不是「今天」→ 当日收盘未扫，需补；或
    3) 缓存 trade_date 落后「最近交易日」超过 1 天（说明上次扫描因故漏掉/数据陈旧）→ 允许补刷，
       避免一直显示上上个交易日的旧数据。

    其余情况（非交易日/周末/假日、交易日 15:15 前、当日快照已存在且未过期）→ 冻结，
    直接复用缓存静态展示最近 1 个交易日的结果，不浪费扫描资源。

    force=1（手动刷新）不受此限，任何时候都可触发，让用户能主动获取最新。"""
    now = bj_now()
    if res is None:
        return True
    cached_td = res.get(trade_date_field)
    # 条件2：更新窗口内且当日尚未扫描
    if _in_update_window(now):
        td = now.strftime("%Y-%m-%d")
        if cached_td != td:
            return True
    # 条件3：缓存落后最近交易日超过 1 天（漏扫保护）
    try:
        if cached_td:
            from datetime import datetime as _dt
            cached_d = _dt.strptime(cached_td, "%Y-%m-%d").date()
            last_d = _dt.strptime(_last_trading_day(now), "%Y-%m-%d").date()
            if (last_d - cached_d).days > 1:
                return True
    except Exception:
        pass
    return False


def _date_integrity(trade_date):
    """校验快照 trade_date 的可信度，返回 (ok, warn_msg)。
    - 必须为交易日（周一~周五），周末数据必是上一交易日收盘被误标，属异常；
    - 距今天数超过 7 天（>1 周无更新）提示数据过旧。
    线上/离线兜底场景：返回 ok=False 时前端应明确标注，绝不可伪装成「实时/今日」。"""
    if not trade_date:
        return False, "无数据日期"
    try:
        td = datetime.strptime(trade_date[:10], "%Y-%m-%d")
    except Exception:
        return False, "日期格式异常:" + str(trade_date)
    warn = ""
    if not _is_trading_day(td):
        warn = "数据日期 %s 非交易日（周末），疑似误标，请核查数据源" % trade_date[:10]
        return False, warn
    days_old = (bj_now().date() - td.date()).days
    if days_old < 0:
        warn = "数据日期 %s 晚于当前日期，疑似时区/抓取异常" % trade_date[:10]
        return False, warn
    if days_old > 7:
        warn = "数据已 %d 天未更新（最新交易日 %s）" % (days_old, trade_date[:10])
    return (len(warn) == 0), warn

# ===========================================================================
# 口袋支点量化选股引擎（纯标准库，无 numpy/pandas；源自 pivot_engine.py，内联复用
# fund_arb 的 bj_now / http_get_text / _is_trading_day / _threading 等定义）
# 理论：欧奈尔 CAN SLIM · 米勒维尼趋势模板/VCP · 斯泰恩超级强势股 · 莫拉尔斯口袋支点
# 评分权重经 2024-11~2026-07 全市场 32326 信号回测标定；离场：8% 止损 + 破 MA50。
# ===========================================================================
# ---------------------------------------------------------------------------
# 口袋支点量化选股引擎（纯标准库实现，无 numpy/pandas 依赖）
#
# 理论来源：
#   [1] William J. O'Neil《笑傲股市》—— CAN SLIM / RS 相对强度评级
#   [2] Gil Morales & Chris Kacher《像欧奈尔信徒一样交易 I/II》—— Pocket Pivot 口袋支点
#   [3] Mark Minervini《股票魔法师 I/II》—— Trend Template 趋势模板 8 条 / VCP 波动收缩
#   [4] Jesse C. Stine《100倍超级强势股》—— Superstock 超级强势股
#
# 评分权重按 2024-11~2026-07 全市场回测标定（32326 个信号，日期匹配基准）：
#   趋势模板 8/8 → 超额 +2.22%（最强因子）| RS 80-90 → +2.05% | 大盘空头 → -2.95%
# 离场规则：8% 硬止损 + 跌破 50 日线，不设固定止盈（过早止盈是最大收益杀手）
# ---------------------------------------------------------------------------

PIVOT_VERSION = "1.0"

# 依赖（注入 fund_arb 后这些均已在文件顶部导入，此处仅为独立运行兜底）
try:
    json, time, threading, ThreadPoolExecutor, as_completed, bj_now   # noqa: F821
except NameError:
    import json, time, threading                                      # noqa: E401
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime as _pv_dt, timedelta as _pv_td, timezone as _pv_tz

    def bj_now():
        return _pv_dt.now(_pv_tz(_pv_td(hours=8))).replace(tzinfo=None)

# 全市场代码枚举区间（沪市主板 / 科创板 / 深市主板 / 创业板）
PIVOT_CODE_RANGES = [
    ("sh", 600000, 604000), ("sh", 605000, 605600), ("sh", 688000, 689000),
    ("sz", 1, 4000), ("sz", 300000, 301900), ("sz", 302000, 302100),
]

PIVOT_CFG = dict(
    kline_len=280,          # 每只股票拉取的日线根数（>252 用于 52 周计算）
    max_workers=24,         # 抓取并发
    min_price=3.0, max_price=400.0,
    min_amount_wan=5000.0,  # 当日成交额下限（万元）
    top_n=30,               # 网页展示条数上限（用户要求最多前30只）
    scan_hour=15, scan_minute=15,   # 收盘后 15:15 自动扫描（东财入库后，数据准确）
)
# 抓取并发可用环境变量覆盖（避免盲目调大导致上游 429/超时）
PIVOT_CFG["max_workers"] = int(os.environ.get("FUND_ARB_PIVOT_WORKERS", PIVOT_CFG["max_workers"]))

# 口袋支点参数（Morales & Kacher 严格版）
PIVOT_P = dict(
    lookback=10, vol_ratio_min=1.00, vol_vs_ma50_min=1.10,
    close_in_upper_pct=0.50, ma10_tolerance=-0.02, max_ext_above_ma10=0.075,
    max_gap_up=0.05, max_daily_gain=0.095, base_window=50, base_max_depth=0.35,
)
# Minervini 趋势模板
PIVOT_T = dict(rs_min=70, above_low_pct=0.30, below_high_pct=0.25, ma200_rising_days=22)
# VCP 波动收缩
PIVOT_V = dict(window=60, segments=3, contraction_ratio=0.75,
               last_pullback_max=0.12, vol_dryup_ratio=0.80, atr_contraction=0.85)
# 综合评分权重（回测标定）
PIVOT_W = dict(trend_template=40, rs_rating=22, pocket_quality=15,
               vcp_shape=10, near_high=8, sector=5)
# 离场规则（回测标定：破 MA50 盈亏比 2.40 最优）
PIVOT_E = dict(stop_loss_pct=0.08, trail_ma=50, risk_budget_pct=1.0)


# ------------------------------------------------------------------ 基础工具
def _pv_sma(xs, n):
    """简单移动平均（O(len) 滑动窗口）。不足 n 根的位置返回 None。"""
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def _pv_atr(h, l, c, n):
    """平均真实波幅。"""
    tr = []
    for i in range(len(c)):
        pc = c[i - 1] if i > 0 else c[0]
        tr.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    return _pv_sma(tr, n)


def _pv_slope_up(a, days):
    """序列末端在 days 个交易日内是否上行（末值 > 起值 且 线性回归斜率 > 0）。"""
    if len(a) < days + 1:
        return False
    seg = a[-days - 1:]
    if any(x is None for x in seg):
        return False
    m = len(seg)
    xm = (m - 1) / 2.0
    ym = sum(seg) / m
    num = sum((i - xm) * (seg[i] - ym) for i in range(m))
    den = sum((i - xm) ** 2 for i in range(m))
    k = num / den if den > 0 else 0.0
    return bool(seg[-1] > seg[0] and k > 0)


def _pv_clip(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _pv_f(v, d=0.0):
    """None / 非法值 → 默认值。"""
    return d if v is None else v


# ------------------------------------------------------------------ 指标计算
def pivot_compute(o, h, l, c, v):
    """输入某只股票的 OHLCV（时间升序），输出全部指标与信号。需 >=150 根 K 线。"""
    n = len(c)
    if n < 150:
        return None

    P, T, V = PIVOT_P, PIVOT_T, PIVOT_V
    ma5, ma10 = _pv_sma(c, 5), _pv_sma(c, 10)
    ma50 = _pv_sma(c, 50)
    ma150 = _pv_sma(c, min(150, n))
    ma200 = _pv_sma(c, 200) if n >= 200 else _pv_sma(c, n - 1)
    vma5, vma50 = _pv_sma(v, 5), _pv_sma(v, 50)
    atr10, atr50 = _pv_atr(h, l, c, 10), _pv_atr(h, l, c, 50)

    t = n - 1
    px, prev = c[t], c[t - 1]
    m50, m150, m200 = _pv_f(ma50[t]), _pv_f(ma150[t]), _pv_f(ma200[t])
    m10 = _pv_f(ma10[t])
    v50 = _pv_f(vma50[t])

    win52 = min(250, n)
    hi52, lo52 = max(h[-win52:]), min(l[-win52:])
    off_high = (px - hi52) / hi52 if hi52 > 0 else -1.0
    up_from_low = (px / lo52 - 1.0) if lo52 > 0 else 0.0

    # ---------- 1. 口袋支点 ----------
    lb = P["lookback"]
    seg_c, seg_pc, seg_v = c[t - lb:t], c[t - lb - 1:t - 1], v[t - lb:t]
    dn = [seg_v[i] for i in range(len(seg_c)) if seg_c[i] < seg_pc[i]]
    if dn:
        max_down_vol, n_down = max(dn), len(dn)
    else:
        # 10 日内无下跌日 → 极强势，用区间最小量作基准（原著：此时放量即可）
        max_down_vol, n_down = (min(seg_v) if seg_v else 0.0), 0

    vol_x = v[t] / max_down_vol if max_down_vol > 0 else 0.0
    rng = h[t] - l[t]
    close_pos = (c[t] - l[t]) / rng if rng > 1e-9 else 1.0
    day_gain = px / prev - 1.0 if prev > 0 else 0.0
    gap = (o[t] - prev) / prev if prev > 0 else 0.0
    ext_ma10 = (px - m10) / m10 if m10 > 0 else 0.0
    vol_vs_ma50 = v[t] / v50 if v50 > 0 else 0.0

    bw = min(P["base_window"], n - 1)
    base_hi, base_lo = max(h[t - bw:t + 1]), min(l[t - bw:t + 1])
    base_depth = (base_hi - base_lo) / base_hi if base_hi > 0 else 1.0

    checks = {
        "量能超越10日最大下跌量": vol_x >= P["vol_ratio_min"],
        "收阳线": px > prev,
        "实体阳线": px > o[t],
        "收在振幅上半部": close_pos >= P["close_in_upper_pct"],
        "量能≥50日均量×1.1": vol_vs_ma50 >= P["vol_vs_ma50_min"],
        "贴近或站上10日线": ext_ma10 >= P["ma10_tolerance"],
        "未过度延伸": ext_ma10 <= P["max_ext_above_ma10"],
        "未高开追高": gap <= P["max_gap_up"],
        "站上50日线": px > m50 if m50 > 0 else False,
        "50日线上行": _pv_slope_up(ma50, 10),
        "10日线>50日线": m10 > m50 if (m10 > 0 and m50 > 0) else False,
        "非涨停不可买": day_gain < P["max_daily_gain"],
        "基底未破坏": base_depth <= P["base_max_depth"],
    }
    is_pocket = all(checks.values())
    pp_fail = [k for k, ok in checks.items() if not ok]

    q = (_pv_clip((vol_x - 1.0) / 2.0, 0, 1) * 40
         + _pv_clip((close_pos - 0.5) / 0.5, 0, 1) * 20
         + (1 - _pv_clip(abs(ext_ma10) / 0.06, 0, 1)) * 20
         + _pv_clip((vol_vs_ma50 - 1.0) / 1.5, 0, 1) * 20)

    # ---------- 2. Minervini 趋势模板（第 8 条 RS 需全市场排名后回填）----------
    tt = {
        "①现价>150日&200日线": px > m150 > 0 and px > m200 > 0,
        "②150日线>200日线": m150 > m200 > 0,
        "③200日线上行1个月": _pv_slope_up(ma200, T["ma200_rising_days"]),
        "④50日>150日>200日": m50 > m150 > m200 > 0,
        "⑤现价>50日线": px > m50 > 0,
        "⑥高于52周低点30%": up_from_low >= T["above_low_pct"],
        "⑦距52周高点25%内": off_high >= -T["below_high_pct"],
    }
    tt_partial = sum(1 for x in tt.values() if x)

    # ---------- 3. VCP 波动收缩 ----------
    w = min(V["window"], n - 1)
    seg = w // V["segments"]
    contractions = []
    for i in range(V["segments"]):
        s0 = t - w + i * seg
        hh, ll = max(h[s0:s0 + seg + 1]), min(l[s0:s0 + seg + 1])
        contractions.append((hh - ll) / hh if hh > 0 else 1.0)
    shrink_ok = all(contractions[i + 1] <= contractions[i] * V["contraction_ratio"]
                    for i in range(len(contractions) - 1))
    last_pb = contractions[-1]
    vol_dry = (_pv_f(vma5[t]) / v50) if v50 > 0 else 9.9
    atr_ratio = (_pv_f(atr10[t]) / _pv_f(atr50[t], 1)) if _pv_f(atr50[t]) > 0 else 9.9
    is_vcp = bool(shrink_ok and last_pb <= V["last_pullback_max"]
                  and vol_dry <= V["vol_dryup_ratio"] and atr_ratio <= V["atr_contraction"])
    vcp_score = ((40 if shrink_ok else 0)
                 + (1 - _pv_clip(last_pb / 0.20, 0, 1)) * 25
                 + (1 - _pv_clip(vol_dry / 1.2, 0, 1)) * 20
                 + (1 - _pv_clip(atr_ratio / 1.2, 0, 1)) * 15)

    # ---------- 4. 超级强势股（Stine）----------
    bw2 = min(250, n - 1)
    hi_bw = max(h[t - bw2:t])
    wk_vol_x = (sum(v[t - 4:t + 1]) / 5.0) / v50 if v50 > 0 else 0.0
    stine = {
        "突破年线级平台": px >= hi_bw * 0.92,
        "距52周低点涨幅达标": 0.30 <= up_from_low <= 3.00,
        "30周(150日)线上行": _pv_slope_up(ma150, 20),
        "周线放量": wk_vol_x >= 1.0,
    }

    # ---------- 5. RS 原始值（IBD 加权，供全市场排名）----------
    tot, wsum = 0.0, 0.0
    for lag, wt in ((63, 0.40), (126, 0.20), (189, 0.20), (252, 0.20)):
        if n > lag and c[-lag - 1] > 0:
            tot += wt * (c[-1] / c[-lag - 1])
            wsum += wt
    rs_raw = (tot / wsum) if wsum > 0 else None

    return dict(
        close=round(px, 2), open=round(o[t], 2), high=round(h[t], 2), low=round(l[t], 2),
        volume=v[t], prev_close=round(prev, 2), chg_pct=round(day_gain * 100, 2),
        ma10=round(m10, 2), ma50=round(m50, 2), ma150=round(m150, 2), ma200=round(m200, 2),
        hi52=round(hi52, 2), lo52=round(lo52, 2),
        off_high_pct=round(off_high * 100, 2), up_from_low_pct=round(up_from_low * 100, 2),
        pocket=is_pocket, pocket_quality=round(q, 1), pocket_fail=pp_fail,
        vol_x=round(vol_x, 2), vol_vs_ma50=round(vol_vs_ma50, 2), n_down_days=n_down,
        close_pos=round(close_pos, 2), ext_ma10_pct=round(ext_ma10 * 100, 2),
        gap_pct=round(gap * 100, 2), base_depth_pct=round(base_depth * 100, 1),
        tt=tt, tt_partial=tt_partial,
        vcp=is_vcp, vcp_score=round(vcp_score, 1),
        contractions=[round(x * 100, 1) for x in contractions],
        vol_dry=round(vol_dry, 2), atr_ratio=round(atr_ratio, 2),
        stine=stine, wk_vol_x=round(wk_vol_x, 2),
        rs_raw=rs_raw,
    )


def pivot_trade_plan(m):
    """交易计划：8% 硬止损 + 跌破 50 日线离场，仓位按 1% 风险预算反推。"""
    E = PIVOT_E
    px = m["close"]
    stop = max(m["low"] * 0.99, px * (1 - E["stop_loss_pct"]))
    if stop >= px:
        stop = px * (1 - E["stop_loss_pct"])
    risk_pct = (px - stop) / px * 100
    pos_pct = min(25.0, E["risk_budget_pct"] / max(risk_pct, 0.5) * 100)
    return dict(
        buy_low=round(px * 0.995, 2), buy_high=round(px * 1.02, 2),
        stop=round(stop, 2), risk_pct=round(risk_pct, 2),
        target2=round(px + (px - stop) * 2, 2),
        target3=round(px + (px - stop) * 3, 2),
        trail_ma50=m.get("ma50", 0), pos_pct=round(pos_pct, 1),
        exit_rule="跌破50日线(%s)离场，不设固定止盈" % m.get("ma50", 0),
    )


def pivot_grade(tt_pass, pocket, vcp, rs):
    """信号分级 S/A/B/C。"""
    if not pocket:
        return ""
    if tt_pass >= 8 and vcp and rs >= 90:
        return "S"
    if tt_pass >= 8 and rs >= 80:
        return "A"
    if tt_pass >= 6 and rs >= 70:
        return "B"
    return "C"


def pivot_score(m, rs, sector_str=50.0):
    """综合评分 0-100（权重经回测标定）。"""
    W = PIVOT_W
    tt_pass = m["tt_partial"] + (1 if rs >= PIVOT_T["rs_min"] else 0)
    near_high = _pv_clip(1.0 + m["off_high_pct"] / 25.0, 0, 1)
    s = (W["trend_template"] * (tt_pass / 8.0)
         + W["rs_rating"] * (rs / 99.0)
         + W["pocket_quality"] * (m["pocket_quality"] / 100.0)
         + W["vcp_shape"] * (m["vcp_score"] / 100.0)
         + W["near_high"] * near_high
         + W["sector"] * (sector_str / 100.0))
    return round(s, 1), tt_pass


# ------------------------------------------------------------------ 数据层
# 说明：复用 fund_arb 已有的 http_get_text / http_get_json；独立测试时用下面的兜底实现。
try:
    http_get_text  # noqa: F821  —— 注入 fund_arb 后使用其实现
except NameError:
    import urllib.request as _pv_ur

    _PV_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

    def http_get_text(url, referer=None, timeout=10, retries=2, encoding="utf-8"):
        headers = {"User-Agent": _PV_UA}
        if referer:
            headers["Referer"] = referer
        last = None
        for _ in range(retries + 1):
            try:
                req = _pv_ur.Request(url, headers=headers)
                with _pv_ur.urlopen(req, timeout=timeout) as r:
                    return r.read().decode(encoding, "ignore")
            except Exception as e:
                last = e
        raise last


def pivot_snap_batch(symbols):
    """腾讯批量实时快照（一次最多 60 只）。返回 {symbol: {...}}。"""
    txt = http_get_text("https://qt.gtimg.cn/q=" + ",".join(symbols),
                        timeout=12, retries=1, encoding="gbk")
    out = {}
    for line in txt.split(";"):
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=")[0].replace("v_", "").strip()
            f = line.split('"')[1].split("~")
            if len(f) < 46 or not f[3] or float(f[3]) <= 0:
                continue
            out[key] = dict(
                name=f[1].strip(), price=float(f[3]), prev=float(f[4]), open=float(f[5]),
                chg_pct=float(f[32] or 0), high=float(f[33] or 0), low=float(f[34] or 0),
                volume=float(f[36] or 0),          # 成交量(手)
                amount_wan=float(f[37] or 0),      # 成交额(万元)
                turn_rate=float(f[38] or 0),       # 换手率(%)
                float_mcap=float(f[44] or 0),      # 流通市值(亿)
                total_mcap=float(f[45] or 0),      # 总市值(亿)
                ts=f[30] if len(f) > 30 else "",
            )
        except (ValueError, IndexError):
            pass
    return out


def pivot_fetch_ohlcv(symbol, n=None):
    """腾讯前复权日线 OHLCV（时间升序）。"""
    n = n or PIVOT_CFG["kline_len"]
    txt = http_get_text(
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{n},qfq",
        timeout=12, retries=1)
    data = json.loads(txt)
    node = (data.get("data") or {}).get(symbol) or {}
    arr = node.get("qfqday") or node.get("day") or []
    o, h, l, c, v, d = [], [], [], [], [], []
    for row in arr:
        try:
            d.append(row[0]); o.append(float(row[1])); c.append(float(row[2]))
            h.append(float(row[3])); l.append(float(row[4])); v.append(float(row[5]))
        except (IndexError, ValueError, TypeError):
            pass
    return dict(date=d, open=o, high=h, low=l, close=c, volume=v)


def pivot_universe():
    """全市场股票池：代码枚举 + 批量快照探活（一次拿到快照，省一轮请求）。"""
    cands = []
    for mkt, lo, hi in PIVOT_CODE_RANGES:
        cands += [f"{mkt}{i:06d}" for i in range(lo, hi)]
    chunks = [cands[i:i + 60] for i in range(0, len(cands), 60)]
    alive = {}
    with ThreadPoolExecutor(max_workers=PIVOT_CFG["max_workers"]) as ex:
        for fut in as_completed([ex.submit(pivot_snap_batch, ch) for ch in chunks]):
            try:
                alive.update(fut.result())
            except Exception:
                pass
    # 基础过滤：价格区间、成交额、剔除 ST/退市
    C_ = PIVOT_CFG
    out = {}
    for sym, d in alive.items():
        nm = d["name"]
        if "ST" in nm or "退" in nm or nm.startswith("N"):
            continue
        if not (C_["min_price"] <= d["price"] <= C_["max_price"]):
            continue
        if d["amount_wan"] < C_["min_amount_wan"]:
            continue
        out[sym] = d
    return out


def pivot_market_state():
    """大盘择时 M：沪深300 的 50/200 日线 + 25 日分销日计数 → 状态与建议仓位上限。"""
    try:
        k = pivot_fetch_ohlcv("sh000300", 260)
    except Exception:
        return dict(state="未知", score=50.0, max_position=50, detail="指数数据获取失败", bull=False)
    c, v = k["close"], k["volume"]
    if len(c) < 200:
        return dict(state="未知", score=50.0, max_position=50, detail="指数历史不足", bull=False)
    ma50, ma200 = _pv_sma(c, 50), _pv_sma(c, 200)
    px = c[-1]
    above50 = px > _pv_f(ma50[-1])
    above200 = px > _pv_f(ma200[-1])
    ma50_up = _pv_slope_up(ma50, 10)
    ma200_up = _pv_slope_up(ma200, 22)
    # 分销日：指数跌幅 >0.2% 且成交量大于前一日
    dd = 0
    for i in range(len(c) - 25, len(c)):
        if i < 1:
            continue
        if c[i] / c[i - 1] - 1 < -0.002 and v[i] > v[i - 1]:
            dd += 1
    score = (30 if above50 else 0) + (30 if above200 else 0) + \
            (15 if ma50_up else 0) + (15 if ma200_up else 0) + max(0, 10 - dd * 2)
    if score >= 75 and dd < 4:
        state, pos = "进攻", 100
    elif score >= 55:
        state, pos = "谨慎", 60
    elif score >= 35:
        state, pos = "防御", 30
    else:
        state, pos = "空仓", 10
    return dict(state=state, score=round(score, 1), max_position=pos,
                bull=bool(above50 and above200),
                dd_count=dd, above_ma50=above50, above_ma200=above200,
                index_close=round(px, 2), ma50=round(_pv_f(ma50[-1]), 2),
                ma200=round(_pv_f(ma200[-1]), 2),
                detail=f"沪深300 {'站上' if above50 else '跌破'}50日线、"
                       f"{'站上' if above200 else '跌破'}200日线，25日分销日 {dd} 个")


def pivot_scan(progress=None):
    """全市场扫描主流程。progress(done, total, phase) 用于回报进度。"""
    t0 = time.time()

    def _p(done, total, phase):
        if progress:
            try:
                progress(done, total, phase)
            except Exception:
                pass

    _p(0, 1, "拉取全市场快照")
    market = pivot_market_state()
    uni = pivot_universe()
    syms = sorted(uni.keys())
    total = len(syms)
    _p(0, total, "计算指标")

    metrics, done = {}, 0
    lock = threading.Lock()

    kdates = []  # 收集全市场 K 线末根日期，trade_date 取最晚一根，避免"标签≠数值"错位

    def _one(sym):
        try:
            k = pivot_fetch_ohlcv(sym)
            if len(k["close"]) < 150:
                return sym, None
            m = pivot_compute(k["open"], k["high"], k["low"], k["close"], k["volume"])
            if m and k.get("date"):
                m["_kdate"] = k["date"][-1]  # K 线最后一根的真实交易日
            return sym, m
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=PIVOT_CFG["max_workers"]) as ex:
        for fut in as_completed([ex.submit(_one, s) for s in syms]):
            try:
                sym, m = fut.result()
                if m:
                    metrics[sym] = m
                    if m.get("_kdate"):
                        kdates.append(m["_kdate"])
            except Exception:
                pass
            with lock:
                done += 1
                if done % 100 == 0 or done == total:
                    _p(done, total, "计算指标")

    # ---- RS 全市场百分位排名（1-99）----
    _p(total, total, "计算RS评级")
    pairs = [(s, m["rs_raw"]) for s, m in metrics.items() if m.get("rs_raw") is not None]
    pairs.sort(key=lambda x: x[1])
    nn = len(pairs)
    rs_map = {s: round(i / max(nn - 1, 1) * 98 + 1) for i, (s, _) in enumerate(pairs)}

    # ---- 组装选股结果 ----
    picks = []
    for sym, m in metrics.items():
        if not m["pocket"]:
            continue
        rs = rs_map.get(sym, 1)
        sc, tt_pass = pivot_score(m, rs)
        g = pivot_grade(tt_pass, m["pocket"], m["vcp"], rs)
        snap = uni.get(sym, {})
        reasons = []
        if tt_pass >= 8:
            reasons.append("趋势模板 8/8 全过（Minervini 第二阶段）")
        elif tt_pass >= 6:
            reasons.append(f"趋势模板 {tt_pass}/8")
        if rs >= 90:
            reasons.append(f"RS {rs} 全市场前 {100-rs}%")
        elif rs >= 80:
            reasons.append(f"RS {rs} 强于八成个股")
        if m["vol_x"] >= 1.5:
            reasons.append(f"量能达 10 日最大跌量的 {m['vol_x']}倍")
        if m["vcp"]:
            reasons.append("VCP 波动收缩成立")
        if m["off_high_pct"] >= -10:
            reasons.append(f"距 52 周高点仅 {abs(m['off_high_pct']):.1f}%")
        if all(m["stine"].values()):
            reasons.append("符合 Stine 超级强势股全部条件")
        picks.append(dict(
            symbol=sym, code=sym[2:], name=snap.get("name", sym),
            grade=g, score=sc, rs=rs, trend_pass=tt_pass,
            close=m["close"], chg_pct=m["chg_pct"], vol_x=m["vol_x"],
            vol_vs_ma50=m["vol_vs_ma50"], pocket_quality=m["pocket_quality"],
            vcp=m["vcp"], vcp_score=m["vcp_score"],
            off_high_pct=m["off_high_pct"], up_from_low_pct=m["up_from_low_pct"],
            ma50=m["ma50"], ma150=m["ma150"], ma200=m["ma200"],
            amount_wan=round(snap.get("amount_wan", 0), 0),
            float_mcap=round(snap.get("float_mcap", 0), 1),
            turn_rate=snap.get("turn_rate", 0),
            tt=m["tt"], stine=m["stine"], reasons=reasons,
            plan=pivot_trade_plan(m),
        ))

    picks.sort(key=lambda x: (-x["score"], -x["rs"]))
    grade_cnt = {g: sum(1 for p in picks if p["grade"] == g) for g in ("S", "A", "B", "C")}
    # trade_date 取全市场 K 线末根的最晚交易日（而非运行时刻），防止标签与数值错位
    real_td = max(kdates) if kdates else bj_now().strftime("%Y-%m-%d")
    return dict(
        version=PIVOT_VERSION,
        updated=bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        trade_date=real_td,
        kline_last_date=real_td,
        elapsed=round(time.time() - t0, 1),
        market=market,
        stats=dict(universe=total, computed=len(metrics),
                   picks=len(picks), grade=grade_cnt),
        picks=picks[:PIVOT_CFG["top_n"]],
        total_picks=len(picks),
    )


# ------------------------------------------------------------------ 缓存与调度
PIVOT_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pivot_cache.json")
PIVOT_SNAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pivot_snapshot.json")

_PIVOT = {
    "result": None,      # 最近一次完整扫描结果
    "scanning": False,   # 是否正在扫描
    "progress": {"done": 0, "total": 0, "phase": ""},
    "error": "",
}
_PIVOT_LOCK = threading.Lock()


def _pivot_load_disk():
    """启动时回填磁盘缓存；若磁盘缓存缺失（云平台重新部署后本地文件系统被重置），
    则回退到仓库内置的快照文件 pivot_snapshot.json，保证页面打开即有数据。"""
    try:
        data = None
        src = ""
        if os.path.exists(PIVOT_CACHE_FILE):
            with open(PIVOT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            src = "磁盘缓存"
        if not (isinstance(data, dict) and data.get("picks") is not None) and os.path.exists(PIVOT_SNAP_FILE):
            with open(PIVOT_SNAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            src = "内置快照"
        if isinstance(data, dict) and data.get("picks") is not None:
            with _PIVOT_LOCK:
                _PIVOT["result"] = data
            print(f"    [口袋支点] 载入{src}：{data.get('updated')} 命中 {data.get('total_picks')} 只")
    except Exception as e:
        print(f"    [口袋支点] 缓存载入失败: {e}")


def _pivot_save_disk(res):
    try:
        with open(PIVOT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        # 同步更新内置快照（仓库随源码提交，云端重部署后首个请求即可秒回数据）
        with open(PIVOT_SNAP_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    except Exception as e:
        print(f"    [口袋支点] 磁盘缓存写入失败: {e}")
    # 近5日入选历史：A级及以上入选名单（供口袋支点页统计表）
    try:
        history_append("pivot", res.get("trade_date", ""), _pivot_history_entries(res))
    except Exception as e:
        print(f"    [历史] 口袋支点记录失败: {e}")


def pivot_run_scan_bg():
    """后台扫描（单飞：同一时刻只允许一个扫描线程）。"""
    with _PIVOT_LOCK:
        if _PIVOT["scanning"]:
            return False
        _PIVOT["scanning"] = True
        _PIVOT["error"] = ""
        _PIVOT["progress"] = {"done": 0, "total": 0, "phase": "启动中"}

    def _prog(done, total, phase):
        with _PIVOT_LOCK:
            _PIVOT["progress"] = {"done": done, "total": total, "phase": phase}

    def _run():
        try:
            res = pivot_scan(progress=_prog)
            with _PIVOT_LOCK:
                _PIVOT["result"] = res
            _pivot_save_disk(res)
            print(f"    [口袋支点] 扫描完成：{res['stats']['universe']} 只 → "
                  f"命中 {res['total_picks']} 只，耗时 {res['elapsed']}s")
        except Exception as e:
            with _PIVOT_LOCK:
                _PIVOT["error"] = str(e)
            print(f"    [口袋支点] 扫描失败: {e}")
        finally:
            with _PIVOT_LOCK:
                _PIVOT["scanning"] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def pivot_api_payload(force=False):
    """/api/pivot 的响应体：立即返回缓存 + 扫描状态；缓存过期或强制则后台重扫。"""
    with _PIVOT_LOCK:
        res = _PIVOT["result"]
        scanning = _PIVOT["scanning"]
        prog = dict(_PIVOT["progress"])
        err = _PIVOT["error"]

    today = bj_now().strftime("%Y-%m-%d")
    # stale 仅用于前端展示提示（数据是否为最近交易日），不再作为自动重扫触发条件。
    stale = (res is None) or (res.get("trade_date") != today)

    # 智能冻结：非更新窗口（周末/夜间/盘中早段）不自动重扫，直接复用缓存静态展示
    # 最近 1 个交易日的结果；仅在交易日 14:45 后且当日尚未扫描时才自动刷。
    # force=1 任何时候都可手动触发，让用户能主动获取最新。
    if (force or _auto_refresh_due(res)) and not scanning:
        pivot_run_scan_bg()
        scanning = True

    if res is None:
        return dict(scanning=scanning, progress=prog, error=err,
                    picks=[], stats=dict(universe=0, picks=0, grade={}),
                    market={}, updated="", total_picks=0)
    out = dict(res)
    out["scanning"] = scanning
    out["progress"] = prog
    out["error"] = err
    out["stale"] = stale
    _ok, _warn = _date_integrity(res.get("trade_date"))
    out["date_ok"] = _ok
    out["date_warning"] = _warn
    return out


class PivotScheduler(_threading.Thread):
    """常驻线程：每交易日 14:50（收盘前 10 分钟）自动全市场扫描一次。"""
    def run(self):
        hour = int(os.environ.get("PIVOT_SCAN_HOUR", str(PIVOT_CFG["scan_hour"])))
        minute = int(os.environ.get("PIVOT_SCAN_MINUTE", str(PIVOT_CFG["scan_minute"])))
        while True:
            now = bj_now()
            cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= now:
                cand = cand + timedelta(days=1)
            while not _is_trading_day(cand):
                cand = cand + timedelta(days=1)
            secs = (cand - bj_now()).total_seconds()
            if secs > 0:
                time.sleep(secs)
            if _is_trading_day(bj_now()):
                print(f"    [口袋支点] {bj_now():%H:%M} 定时扫描触发")
                pivot_run_scan_bg()
            time.sleep(70)   # 防止同一分钟重复触发

def _is_limited_fund(r):
    """是否「完全买不到」：暂停申购，或可买金额=0（purchase_limit==0）。
    限大额申购（仍有每日额度可买）仍可套利，照常推送，不在此列。"""
    if r.get("subscribe_status") == "暂停申购":
        return True
    limit = r.get("purchase_limit")
    if limit is not None and limit == 0:
        return True
    return False

def _push_est(r):
    e = r.get("est_premium")
    return e if e is not None else (r.get("premium") or 0)

def push_feishu(text):
    """推送文本到飞书自定义机器人。需 FEISHU_WEBHOOK_URL；设 FEISHU_WEBHOOK_SECRET 则自动签名。"""
    import os, json, time as _t, hmac, hashlib, base64, urllib.request, urllib.parse
    url = os.environ.get("FEISHU_WEBHOOK_URL")
    if not url:
        print("[Feishu] 未配置 FEISHU_WEBHOOK_URL，跳过推送")
        return False
    secret = os.environ.get("FEISHU_WEBHOOK_SECRET")
    if secret:
        ts = str(int(_t.time()))
        s = (ts + "\n" + secret).encode("utf-8")
        sign = base64.b64encode(hmac.new(secret.encode("utf-8"), s, hashlib.sha256).digest()).decode()
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}timestamp={ts}&sign={urllib.parse.quote(sign)}"
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("code") != 0:
            print(f"[Feishu] 推送返回错误: {body}")
            return False
        print("[Feishu] 推送成功")
        return True
    except Exception as e:
        print(f"[Feishu] 推送失败: {e}")
        return False

def build_arb_push_text(target_date=None):
    """汇总网页2与网页3中 |估算溢价|>阈值的机会，按优先级取前 N，返回飞书推送文本。
    无机会时返回 None。云服务器与 WorkBuddy 自动化共用此函数，保证两边文案一致。"""
    if not target_date:
        target_date = bj_now().strftime("%Y-%m-%d")
    try:
        threshold = float(os.environ.get("FEISHU_PUSH_THRESHOLD", "2.0"))
    except ValueError:
        threshold = 2.0
    try:
        max_n = int(os.environ.get("FEISHU_PUSH_MAX", "5"))
    except ValueError:
        max_n = 5
    # 完全限申购（暂停申购 / 可买金额=0）无法买入，默认从播报中剔除；
    # 限大额申购（仍有每日额度）仍可套利，照常推送。
    # 设 FEISHU_PUSH_EXCLUDE_LIMITED=0 可恢复「包含完全限购」
    exclude_limited = os.environ.get("FEISHU_PUSH_EXCLUDE_LIMITED", "1") not in ("0", "false", "False")
    items = []   # (row, src)
    # 网页2：后台默认监控清单
    try:
        for r in compute_ranking(RANKING_WATCHLIST, target_date)["rows"]:
            if r.get("error"):
                continue
            est = _push_est(r)
            if abs(est) > threshold and not (exclude_limited and _is_limited_fund(r)):
                items.append((r, "ranking"))
    except Exception as e:
        print(f"[Feishu] 网页2扫描失败: {e}")
    # 网页3：复用预热缓存 top|date|1.5|-2.0（阈值 1.5 已含 2% 目标，过滤即可），避免冷算全市场导致 >60s 超时、推送文案为空
    scale_map = {}
    r3_rows = []
    top_key = f"top|{target_date}|1.5|-2.0"
    try:
        _entry = Handler._API_CACHE.get(top_key)
        if _entry and time.time() < _entry[0]:
            r3_rows = _entry[1].get("rows", []) or []
        else:
            r3_rows = compute_top_arbitrage(target_date, 1.5, -2.0, top_n=500)["rows"]
        scale_map = {r["code"]: r.get("scale") for r in r3_rows if r.get("scale") is not None}
        for r in r3_rows:
            est = _push_est(r)
            if abs(est) > threshold and not (exclude_limited and _is_limited_fund(r)):
                items.append((r, "top"))
    except Exception as e:
        print(f"[Feishu] 网页3扫描失败: {e}")
    # 网页2 行默认无规模字段，复用网页3 同代码已抓取的规模，使推送信息更完整
    for r, src in items:
        if src == "ranking" and r.get("scale") is None and r["code"] in scale_map:
            r["scale"] = scale_map[r["code"]]
    if not items:
        # 每日心跳：即便无显著套利机会，也播报一句，确保交易日 14:45 必有推送（FEISHU_PUSH_HEARTBEAT=0 可关闭）
        if os.environ.get("FEISHU_PUSH_HEARTBEAT", "1") not in ("0", "false", "False"):
            n_rank = 0
            try:
                n_rank = len([r for r in compute_ranking(RANKING_WATCHLIST, target_date)["rows"] if not r.get("error")])
            except Exception:
                pass
            max_row = None; max_abs = -1.0
            for r in (r3_rows or []):
                if exclude_limited and _is_limited_fund(r):
                    continue
                e2 = _push_est(r)
                if e2 is not None and abs(e2) > max_abs:
                    max_abs = abs(e2); max_row = r
            ref = (f"最大估算溢价 {max_abs:.2f}%（{max_row['code']} {max_row['name']}）"
                   if max_row else "无扫描数据")
            return (f"🔔 LOF 套利播报（{target_date} 14:45）\n"
                    f"今日无 |估算溢价|>{threshold}% 的显著套利机会。\n"
                    f"监控清单 {n_rank} 只 · 全市场 TOP 扫描 {len(r3_rows)} 只 · {ref}。")
        print(f"[Feishu] {target_date} 无 |溢价|>{threshold}% 的套利机会")
        return None
    # 去重（同一基金以网页2为准）
    seen = {}
    for r, src in items:
        c = r["code"]
        if c in seen:
            if src == "ranking":
                seen[c] = (r, src)
        else:
            seen[c] = (r, src)
    uniq = list(seen.values())
    # 优先级：①网页2>网页3 ②溢价>折价 ③估算溢价高>低（限购已在上面剔除）
    uniq.sort(key=lambda it: (
        0 if it[1] == "ranking" else 1,
        0 if _push_est(it[0]) >= 0 else 1,
        -abs(_push_est(it[0])),
    ))
    pick = uniq[:max_n]
    exclude_note = "（已剔除暂停申购）" if exclude_limited else ""
    lines = [f"🔔 LOF 套利机会播报（{target_date} 14:45）",
             f"阈值 |估算溢价|>{threshold}%{exclude_note} · 命中 {len(uniq)} 只，推送前 {len(pick)} 只：", ""]
    for i, (r, src) in enumerate(pick, 1):
        est = _push_est(r)
        typ = "溢价" if est >= 0 else "折价"
        st = r.get("subscribe_status") or "开放申购"
        lim = "限大额" if st == "限大额申购" else ("暂停申" if st == "暂停申购" else "开放")
        scale = f"{r.get('scale'):.2f}亿" if isinstance(r.get('scale'), (int, float)) else "—"
        turn = f"{r.get('turnover'):.0f}万" if isinstance(r.get('turnover'), (int, float)) else "—"
        srcname = "网页2监控" if src == "ranking" else "网页3TOP"
        lines.append(f"{i}. {r.get('code')} {r.get('name')}｜{typ}{est:+.2f}%｜{lim}｜场内{scale}｜成交{turn}｜{srcname}")
    return "\n".join(lines)

def build_arb_push(target_date=None):
    """扫描并推送到飞书；成功返回 True，无机会或失败返回 False。"""
    text = build_arb_push_text(target_date)
    if not text:
        return False
    return push_feishu(text)


# ---- 推送锁：云服务器(常驻) 与 WorkBuddy(本机) 共用一把每日锁，确保 14:45 只推一次 ----
_PUSH_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".push_lock.json")
_PUSH_LOCK_WINDOW = 3600  # 秒：当天推送锁的有效期，避免同日内重复触发

def _push_lock_read():
    try:
        with open(_PUSH_LOCK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _push_lock_claim(date, who):
    """原子抢占当天推送锁。成功返回 True；若当天已被抢占(窗口内)返回 False。
    用临时文件 + os.replace 原子替换，保证云端与 WorkBuddy 同时抢锁时仅一个胜出。"""
    now = time.time()
    cur = _push_lock_read()
    if cur and cur.get("date") == date and (now - float(cur.get("ts", 0))) < _PUSH_LOCK_WINDOW:
        return False
    new = {"date": date, "ts": now, "by": who}
    tmp = _PUSH_LOCK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new, f)
    os.replace(tmp, _PUSH_LOCK_FILE)
    return True

def _push_lock_release(date):
    """释放当天推送锁（推送失败回滚，或 WorkBuddy 推送失败后让云端补推）。"""
    cur = _push_lock_read()
    if cur and cur.get("date") == date:
        try:
            os.remove(_PUSH_LOCK_FILE)
        except Exception:
            pass

class FeishuScheduler(_threading.Thread):
    """常驻线程：每日交易日下午 FEISHU_PUSH_HOUR:FEISHU_PUSH_MINUTE 触发一次扫描推送。"""
    def run(self):
        import os, time as _t
        hour = int(os.environ.get("FEISHU_PUSH_HOUR", "14"))
        minute = int(os.environ.get("FEISHU_PUSH_MINUTE", "45"))
        while True:
            now = bj_now()
            cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= now:
                cand = cand + timedelta(days=1)
            while not _is_trading_day(cand):
                cand = cand + timedelta(days=1)
            sleep_secs = (cand - bj_now()).total_seconds()
            if sleep_secs > 0:
                _t.sleep(sleep_secs)
            # 宽限：优先让本机 WorkBuddy 自动化(14:45 触发)先抢锁推送；
            # 超时仍未抢占则云端补推，确保「WorkBuddy 关 → 云端照推」「WorkBuddy 开 → 不双推」
            grace = int(os.environ.get("FEISHU_CLOUD_GRACE", "90"))
            _t.sleep(grace)
            if _is_trading_day(bj_now()):
                date = bj_now().strftime("%Y-%m-%d")
                if _push_lock_claim(date, "cloud"):
                    try:
                        ok = build_arb_push(date)
                    except Exception as e:
                        print(f"[Feishu] 定时推送异常: {e}")
                        ok = False
                    if not ok:
                        _push_lock_release(date)  # 推送失败回滚，留给 WorkBuddy / 重试
                else:
                    print("[Feishu] 当天推送锁已被 WorkBuddy 抢占，云端跳过")
            _t.sleep(70)   # 防止同一分钟重复触发


def prewarm_holdings():
    """后台预构建持仓指数与复合标的，使用户首访 160216/160644 等重仓基金即命中缓存、秒回。
    单飞锁保证启动期即便已有用户并发请求同一基金，也只算一次。"""
    # 持仓模式相关基金（auto/holdings）：网页1 走持仓估算分支最重
    for code in list(HOLDINGS_MODE.keys()):
        try:
            build_holdings_index(code, 35)
            print(f"    [预暖] 持仓指数 {code} 完成")
        except Exception as e:
            print(f"    [预暖] 持仓指数 {code} 失败: {e}")
    # 复合标的相关基金：每次网页1 查询都会重建合成序列，预暖即可秒回
    for code in list(COMPOSITE_UNDERLYING.keys()):
        try:
            _build_composite_xop(code, 35)
            print(f"    [预暖] 复合标的 {code} 完成")
        except Exception as e:
            print(f"    [预暖] 复合标的 {code} 失败: {e}")


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
    # 持仓/复合标的预暖：使 160216/160644 等重仓基金首访即命中缓存、秒回（网页1 单只冷算代价最高）
    _threading.Thread(target=prewarm_holdings, daemon=True).start()
    # 加载持仓择优缓存（24h 持久化，避免每次重复抓取 10 只重仓行情）
    load_holdings_choice_cache()
    # 磁盘持久化缓存(#2)：启动时回填内存，使休眠/重启后首个请求即可秒回历史数据
    _hydrate_from_disk()
    # 口袋支点量化选股：回填磁盘缓存（重启秒回上次结果），启动常驻定时扫描线程
    # （每交易日 14:50 收盘前 10 分钟自动全市场扫描；访问 /pivot 可查看并手动重扫）
    _pivot_load_disk()
    PivotScheduler(daemon=True).start()
    # 可转债套利：回填磁盘缓存 + 每交易日 14:45 自动扫描
    _cb_load_disk()
    CbScheduler(daemon=True).start()
    print("  可转债套利引擎已启用（每交易日 14:45 自动扫描，访问 /cb 查看）")
    print("  口袋支点选股引擎已启用（每交易日 14:50 自动扫描，访问 /pivot 查看）")
    # 预热 + 周期刷新：网页3(TOP套利，全市场扫描最重)与排行页在实例常驻期间始终命中缓存、秒出。
    # 默认基金 162411 不再主动预热（按需计算即可，结果同样会落盘）；
    # _prewarm_running 防止上一次重算未结束时又重叠启动（避免并发猛刷上游被限流）。
    _prewarm_running = {"rank": False, "top": False}
    _prewarm_iter = {"n": 0}
    def _prewarm_loop():
        while True:
            # 排行（重，带重叠保护）— 每 300s
            if not _prewarm_running["rank"]:
                _prewarm_running["rank"] = True
                try:
                    _d = datetime.now().strftime("%Y-%m-%d")
                    Handler._API_CACHE[f"rank|{_d}|1.5|{','.join(RANKING_WATCHLIST)}"] = (
                        time.time() + Handler._API_CACHE_TTL_RANK, compute_ranking(RANKING_WATCHLIST))
                    _persist_api()
                except Exception:
                    pass
                finally:
                    _prewarm_running["rank"] = False
            # TOP 套利榜（最重：全市场扫描）— 每 600s（隔次），带重叠保护；
            # 磁盘持久化(#2)保证即便本次扫描被上游限频/超时，历史结果仍可秒回。
            if _prewarm_iter["n"] % 2 == 0 and not _prewarm_running["top"]:
                _prewarm_running["top"] = True
                try:
                    # 必须用 bj_now 口径的「最近已收盘交易日」：
                    # ① datetime.now() 取的是服务器本地时区（线上为 UTC），会整体偏 8 小时；
                    # ② 用「今天」会在开盘前/盘中把标签写成当天而数值仍是上一交易日
                    #    （实测周一 00:35 生成了 date=08-31、数值却是 08-28 的快照）。
                    _d = _last_closed_trading_day()
                    Handler._API_CACHE[f"top|{_d}|1.5|-2.0"] = (
                        time.time() + Handler._API_CACHE_TTL_TOP,
                        compute_top_arbitrage(_d, 1.5, -2.0))
                    _persist_api()
                except Exception:
                    pass
                finally:
                    _prewarm_running["top"] = False
            _prewarm_iter["n"] += 1
            # 本地每 60s 刷新（UI 追求实时）；云平台放宽到 300s，避免从单一出口 IP 高频打外部行情源被限流
            time.sleep(60 if host == '127.0.0.1' else 300)
    _threading.Thread(target=_prewarm_loop, daemon=True).start()
    # 飞书定时推送（仅当配置了 FEISHU_WEBHOOK_URL 才启用，避免无谓的每日全量扫描）
    # 云端自推：WorkBuddy 关闭时也能推；与 WorkBuddy 自动化通过 /api/push/lock 共用每日锁，避免双推。
    if os.environ.get("FEISHU_WEBHOOK_URL"):
        ph = os.environ.get("FEISHU_PUSH_HOUR", "14")
        pm = os.environ.get("FEISHU_PUSH_MINUTE", "45")
        FeishuScheduler(daemon=True).start()
        print(f"  飞书定时推送已启用（云端自推·交易日下午 {ph}:{pm:0>2s}；与 WorkBuddy 共用每日锁防双推）")
    else:
        print("  飞书推送未启用（未配置 FEISHU_WEBHOOK_URL；仅 WorkBuddy 自动化可推）")
    if host == '127.0.0.1':
        url = f"http://localhost:{port}"
        print("=" * 60)
        print("  LOF/ETF 套利看板已启动（本地模式）")
        print(f"  在浏览器打开：{url}")
        print("  按 Ctrl+C 停止")
        print("=" * 60)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    else:
        print("=" * 60)
        print("  LOF/ETF 套利看板已启动（云平台模式）")
        print(f"  监听 {host}:{port}，请通过平台分配的 HTTPS 地址访问")
        print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
