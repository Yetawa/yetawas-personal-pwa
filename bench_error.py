import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fund_arb as fa

print("current epoch:", int(time.time()))
# 校准新鲜度检查
for code in ("160719", "161116", "164701", "161226", "162411", "160644"):
    w = fa.weight_for(None, code=code)
    fresh = fa._weight_is_fresh(code)
    print(f"  {code}: effective w={w} fresh={fresh}")

FUNDS = ["160719", "161116", "164701", "161226", "162411", "160644",
         "161128", "161130", "160723", "161125"]

print("\n=== 当前代码(改动后) MAE 对比：近30交易日 vs 近60交易日 ===")
results = {}
for code in FUNDS:
    row = {}
    for W in (30, 60):
        t0 = time.time()
        try:
            r = fa.backtest_nav_estimate(code, days=W, mode="index")
        except Exception as e:
            r = {"error": str(e)}
        dt = time.time() - t0
        if "error" in r:
            print(f"  {code} days={W}: ERROR {r['error']} ({dt:.1f}s)")
            row[W] = {"error": r["error"]}
        else:
            print(f"  {code} days={W}: MAE={r['mae']}% median={r.get('median')}% "
                  f"count={r['count']} w={r['weight']} lag={r['lag']} ({dt:.1f}s)")
            row[W] = {"mae": r["mae"], "median": r.get("median"), "count": r["count"],
                      "weight": r["weight"], "lag": r["lag"]}
    results[code] = row

print("\n=== w 影响(仅黄金类): 当前校准w vs 文章口径0.9637 ===")
for code in ("160719", "161116", "164701"):
    # 备份并强制用 0.9637
    bak_w = fa.WEIGHT_CACHE.get(code)
    bak_ts = fa.WEIGHT_CACHE_TS.get(code)
    fa.WEIGHT_CACHE[code] = 0.9637
    fa.WEIGHT_CACHE_TS[code] = time.time()  # 标为新鲜
    fa.FUND_WEIGHT[code] = 0.9637
    try:
        r = fa.backtest_nav_estimate(code, days=30, mode="index")
        if "error" not in r:
            print(f"  {code} w=0.9637: MAE={r['mae']}% (当前校准 w={bak_w})")
        else:
            print(f"  {code} w=0.9637: ERROR {r['error']}")
    except Exception as e:
        print(f"  {code} w=0.9637: EXC {e}")
    # 还原
    if bak_w is not None:
        fa.WEIGHT_CACHE[code] = bak_w
        fa.WEIGHT_CACHE_TS[code] = bak_ts
    else:
        fa.WEIGHT_CACHE.pop(code, None)

print("\nDONE")
json.dump(results, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_result.json"), "w"), ensure_ascii=False, indent=2)
