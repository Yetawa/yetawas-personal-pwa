"""数据源可达性诊断：在『运行 fund_arb 的同一台机器』上运行，定位 501 根因。
用法：python _probe_sources.py
报告每个数据源的真实 HTTP 状态码 + 能否解析。若腾讯 501 但新浪 200 → 新浪兜底已能救；
若所有国内源都 501 → 是出口网络/代理/Render 海外问题，需换运行环境。
"""
import sys, urllib.request, ssl

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

PROBES = [
    ("腾讯-实时行情 qt.gtimg.cn", "https://qt.gtimg.cn/q=sz161226", {}),
    ("腾讯-历史K线 web.ifzq.gtimg.cn",
     "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz161226,day,,,5,qfq", {}),
    ("新浪-实时行情 hq.sinajs.cn", "https://hq.sinajs.cn/list=sz161226",
     {"Referer": "https://finance.sina.com.cn/"}),
    ("新浪-历史K线 money.finance.sina.com.cn",
     "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz161226&scale=240&ma=no&datalen=5",
     {"Referer": "https://finance.sina.com.cn/"}),
    ("东财-场内基金表 Fund_JJJZ_Data",
     "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx?t=8&lx=1&letter=&gsid=&text=&sort=zdf,desc&page=1,20000",
     {"Referer": "https://fund.eastmoney.com/fund.html"}),
    ("东财-申购状态 fundf10 jjfl", "https://fundf10.eastmoney.com/jjfl_161226.html",
     {"Referer": "https://fundf10.eastmoney.com/"}),
    ("东财-历史K线 push2his LOF",
     "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.161226&fields1=f1&fields2=f51,f52,f53&klt=101&fqt=0&end=20500101&lmt=5",
     {"ut": "fa5e3e957c050414eae63cf14d62471d"}),
    ("天天基金-估值 fundgz", "https://fundgz.1234567.com.cn/js/161226.js?rt=1",
     {"Referer": "http://fundf10.eastmoney.com/"}),
    ("雪球-行情 stock.xueqiu.com", "https://stock.xueqiu.com/v5/stock/quote.json?symbol=LOF161226", {}),
    ("stockanalysis-美股历史", "https://stockanalysis.com/api/symbol/e/KWEB/history?range=6M&period=Daily", {}),
]


def probe(name, url, headers):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read(2000)
            return resp.status, len(data)
    except urllib.error.HTTPError as e:
        return e.code, f"HTTPError {e.code}: {e.reason}"
    except Exception as e:
        return "ERR", f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    print("=== fund_arb 数据源可达性诊断（运行于:", sys.platform, "）===\n")
    for name, url, headers in PROBES:
        code, info = probe(name, url, headers)
        ok = (code == 200 and isinstance(info, int) and info > 50)
        print(f"[{'OK' if ok else 'XX'}] {name:42s} -> {code}  {info}")
    print("\n说明：501=Not Implemented（多为出口代理/海外Render不支持该请求）；"
          "403/404=接口须带正确头部或已变更；正常应为 200 且返回有内容。")
