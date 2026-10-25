#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild_table_from_ocr.py —— 从 OCR 行级 bbox **重建表格**（扫描书专用）

为什么需要（2026-10-07，《某扫描书》实测）：
    扫描书的整页表格（日程表、对照表）交给 `rebuild_source_from_ocr.py` 只能按 (y, x)
    排序成一行行文字，表格的**列结构丢失**——左右两块会交替出现，读起来像乱码：
        `6:00AM REVIEW PREP + NEW NOTES 6:00AM REVIEW PREP + NEW NOTES`
        `CLOSE CALLS 7:30AM PRIORITY LIST 7:30AM`
    但 **OCR 的 bbox 里列结构是完整的**：只要按 x 聚簇就能还原列，按 y 聚簇就能还原行。
    **不需要重跑 OCR，也不需要把表格降级成图片。**

做法（确定性，无模型）：
    1. 收集该页所有行的 x-中心，按**间隔 > --gap 处切分**得到列簇
    2. 行按 y-中心聚类（间隔 > --row-gap 视为换行）
    3. 每个 (行, 列) 单元格取该簇内文本，按 x 排序拼接
    4. 输出 Markdown 表；**表头单独给出**（表格上方、跨列的标题行按各自列归位）

零改写：只做**重排与空白**，不改单元格内任何字符。

用法：
    python rebuild_table_from_ocr.py --ocr-dir <书>/ocr --pages 23,33,35            # 打印预览
    python rebuild_table_from_ocr.py --ocr-dir <书>/ocr --pages 23,33,35 --out <dir>  # 写 <dir>/pXXX.md
选项：--gap 90（列间隔阈值 px）、--row-gap 24（行间隔阈值 px）
"""
import argparse
import io
import json
import os
import re
import sys


def load(p):
    d = json.load(io.open(p, encoding='utf-8'))
    rows = []
    for l in d.get('lines', []):
        t = re.sub(r'\s+', ' ', l.get('text', '')).strip()
        if not t:
            continue
        b = l['box']
        x0, x1 = min(x for x, _ in b), max(x for x, _ in b)
        y0, y1 = min(y for _, y in b), max(y for _, y in b)
        rows.append({'t': t, 'x0': x0, 'x1': x1, 'y': (y0 + y1) / 2, 'xc': (x0 + x1) / 2})
    return rows


def cluster(vals, gap):
    """一维聚簇：相邻值间隔 > gap 就断开。返回 [(lo, hi), ...]。"""
    vals = sorted(vals)
    out = [[vals[0], vals[0]]]
    for v in vals[1:]:
        if v - out[-1][1] > gap:
            out.append([v, v])
        else:
            out[-1][1] = v
    return [(a, b) for a, b in out]


def rebuild(rows, gap, row_gap):
    # 列：先按 x0 聚簇，得到每列的覆盖区间
    cols = cluster([r['x0'] for r in rows], gap)
    # 行：按 y 聚簇
    bands = cluster([r['y'] for r in rows], row_gap)

    def col_of(r):
        best, bi = 1e9, 0
        for i, (lo, hi) in enumerate(cols):
            d = 0 if lo <= r['x0'] <= hi else min(abs(r['x0'] - lo), abs(r['x0'] - hi))
            if d < best:
                best, bi = d, i
        return bi

    def row_of(r):
        for i, (lo, hi) in enumerate(bands):
            if lo <= r['y'] <= hi:
                return i
        return len(bands) - 1

    grid = {}
    for r in rows:
        grid.setdefault(row_of(r), {}).setdefault(col_of(r), []).append(r)
    table = []
    for ri in sorted(grid):
        cells = []
        for ci in range(len(cols)):
            items = sorted(grid[ri].get(ci, []), key=lambda r: r['x0'])
            cells.append(' '.join(r['t'] for r in items))
        table.append(cells)

    # **表外正文**：表格上方的说明段落只有 1 个非空单元格 → 从「首个 ≥2 列非空的行」起算
    start = 0
    for i, row in enumerate(table):
        if sum(1 for c in row if c) >= 2:
            start = i
            break
    table = table[start:]
    # **全空列**：从表头往下，整列为空的丢掉
    keep = [ci for ci in range(len(cols))
            if any(row[ci] for row in table)]
    table = [[row[ci] for ci in keep] for row in table]
    cols = [cols[ci] for ci in keep]
    return cols, table


def to_md(cols, table):
    n = len(cols)
    out = ['| ' + ' | '.join(c if c else ' ' for c in table[0]) + ' |',
           '|' + '---|' * n]
    for row in table[1:]:
        out.append('| ' + ' | '.join(c if c else ' ' for c in row) + ' |')
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(
        description='从 OCR 行级 bbox 重建 Markdown 表格（扫描书专用；默认只打印预览）。',
        epilog='示例：python rebuild_table_from_ocr.py --ocr-dir 书目录/ocr '
               '--pages 23,33,35 --out 书目录/_过程/tables')
    ap.add_argument('--ocr-dir', required=True, help='按页存放的 OCR JSON 目录（p0001.json…）')
    ap.add_argument('--pages', required=True, help='逗号分隔的页码（印刷页/OCR 页，按文件 pXXXX.json）')
    ap.add_argument('--gap', type=int, default=90, help='列间隔阈值(px)；换书时按版面调')
    ap.add_argument('--row-gap', type=int, default=24, help='行间隔阈值(px)')
    ap.add_argument('--out', default=None, help='写到该目录的 pXXX.md（默认只打印预览）')
    a = ap.parse_args()

    for ps in a.pages.split(','):
        p = int(ps.strip())
        f = os.path.join(a.ocr_dir, 'p%04d.json' % p)
        if not os.path.exists(f):
            print('  缺 %s' % f)
            continue
        rows = load(f)
        cols, table = rebuild(rows, a.gap, a.row_gap)
        print('===== p%d ｜ %d 行 → %d 列 × %d 行 =====' % (p, len(rows), len(cols), len(table)))
        md = to_md(cols, table)
        print(md)
        print()
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            io.open(os.path.join(a.out, 'p%03d.md' % p), 'w', encoding='utf-8').write(md + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
