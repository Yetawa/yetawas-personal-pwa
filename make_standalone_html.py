# -*- coding: utf-8 -*-
"""从 fund_arb.py 导出可独立打开的 fund_arb.html / fund_arb_ranking.html / fund_arb_top.html
（数据仍由本地服务 http://localhost:8000 提供，避免 CORS/跨域问题）
"""
import os
import fund_arb


# 全站统一导航：6 个入口映射到同目录下的独立 HTML
# （口袋支点无本地独立文件，指向线上 onrender 页面）
NAV_MAP = [
    ('href="/sector"', 'href="sector_dashboard.html"'),
    ('href="/yupen"', 'href="fish_basin.html"'),
    ('href="/arb"', 'href="fund_arb.html"'),
    ('href="/ranking"', 'href="fund_arb_ranking.html"'),
    ('href="/top"', 'href="fund_arb_top.html"'),
    ('href="/pivot"', 'href="https://fund-arb.onrender.com/pivot"'),
    ('href="/cb"', 'href="cb.html"'),
]


def make_page(html, out_name, fetch_replacements, nav_replacements):
    # 在脚本开头注入 BASE；STATUS_COLORS 在两个页面都存在
    html = html.replace(
        "const STATUS_COLORS=",
        "const BASE = (location.protocol==='file:') ? 'http://localhost:8000' : '';\nconst STATUS_COLORS=",
        1,
    )
    for old, new in fetch_replacements:
        html = html.replace(old, new, 1)
    for old, new in nav_replacements:
        html = html.replace(old, new, 1)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), out_name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成:", out, "大小:", len(html), "字节")


# 界面一：单基金套利看板
make_page(
    fund_arb.PAGE_HTML,
    "fund_arb.html",
    [
        ("let url='/api/data?code='", "let url=BASE+'/api/data?code='"),
        ("fetch('/api/validate?code='", "fetch(BASE+'/api/validate?code='"),
    ],
    NAV_MAP,
)

# 界面二：基金溢价排行表
make_page(
    fund_arb.PAGE2_HTML,
    "fund_arb_ranking.html",
    [("const url='/api/ranking?date='", "const url=BASE+'/api/ranking?date='")],
    NAV_MAP,
)

# 界面三：全市场 LOF TOP20 套利榜
make_page(
    fund_arb.PAGE3_HTML,
    "fund_arb_top.html",
    [("const url='/api/top?date='", "const url=BASE+'/api/top?date='")],
    NAV_MAP,
)
