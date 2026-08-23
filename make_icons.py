#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 fund_arb PWA 图标：icon-192.png / icon-512.png

品牌样式（用户定义）：深岩蓝底 + 蓝色圆环 + 上方红色弧 + 下方绿色弧。

关键约束：
1. iOS Safari / Android Chrome 的 apple-touch-icon、manifest 图标必须是
   "不透明 RGB PNG"（color_type=2），不能带 alpha 通道，否则系统会强制加
   灰色圆圈背景，显示成"小圆圈"。
2. MIUI / Android maskable 图标会被圆形/圆角遮罩裁切到"安全区"（约中心 80%
   直径）。如果品牌图形贴边，裁切后只剩一圈 ring 露出来 -> 用户看到"圈圈"。
   所以主体必须缩进中心 60% 区域，四周用背景色铺满，确保裁切后仍是完整图形。
"""
import struct
import zlib
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 品牌色
BG = (0x0d, 0x11, 0x17)
RING = (0x1f, 0x6f, 0xeb)        # 蓝色圆环
UP = (0xef, 0x44, 0x44)          # 上方红色
DOWN = (0x22, 0xc5, 0x5e)         # 下方绿色


def _png_chunk(typ, data):
    return struct.pack('>I', len(data)) + typ + data + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff)


def make_png(size, path):
    """生成不透明 RGB PNG，color_type=2，背景 BG 填满，主体缩进安全区。"""
    cx = cy = size / 2.0

    # 安全区：主体整体限制在中心 60% 直径内（maskable 要求四周留白 >=20%）
    # 比例基于 size 的一半（半径）来定义
    ring_r = size * 0.165          # 圆环半径（相对整图）
    ring_w = size * 0.058         # 圆环线宽
    arc_r = size * 0.118          # 红/绿弧半径
    arc_w = size * 0.052

    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter=none
        for x in range(size):
            px = x + 0.5
            py = y + 0.5
            # 默认背景（铺满整张，保证不透明且 maskable 边缘是品牌底色）
            r, g, b = BG

            # 蓝色圆环（中心圆）
            d_center = math.hypot(px - cx, py - cy)
            if abs(d_center - ring_r) <= ring_w / 2:
                r, g, b = RING

            # 上方红色弧：位于圆环上半部分外侧
            d_arc_up = math.hypot(px - cx, py - (cy - ring_r - arc_r))
            if abs(d_arc_up - arc_r) <= arc_w / 2 and py < cy - ring_r * 0.4:
                r, g, b = UP

            # 下方绿色弧：位于圆环下半部分外侧
            d_arc_down = math.hypot(px - cx, py - (cy + ring_r + arc_r))
            if abs(d_arc_down - arc_r) <= arc_w / 2 and py > cy + ring_r * 0.4:
                r, g, b = DOWN

            raw.extend([r, g, b])

    compressed = zlib.compress(bytes(raw), level=9)

    # PNG 头
    out = bytearray(b'\x89PNG\r\n\x1a\n')
    # IHDR
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    out += _png_chunk(b'IHDR', ihdr)
    # IDAT
    out += _png_chunk(b'IDAT', compressed)
    # IEND
    out += _png_chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(out)
    print(f"wrote {path}: {size}x{size} RGB PNG, color_type=2 (maskable-safe)")


if __name__ == '__main__':
    make_png(192, os.path.join(HERE, 'icon-192.png'))
    make_png(512, os.path.join(HERE, 'icon-512.png'))
