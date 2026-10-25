#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_pdf_coverage.py —— PDF 源文覆盖率核查（PDF 源的提取完整性卡口）

对应 EPUB 侧的 check_epub_coverage.py：逐页取词级 6-gram，与全部 source_en/*.txt 的合集求交，
覆盖率 = |页 ∩ 源文| / |页|，低于阈值即该页文本未进入源文（或只进了一部分）。

为什么需要：按「目录页码 / 章节标题」切分的提取脚本会静默丢掉没被归入任何章节的页
（扉页、插页、跨章续页、表格页），成品看起来完整，只有覆盖率核查能发现。

已知误报：**表格页**——PDF 里表格单元格按列读取，源 txt 里可能写成按行的 Markdown 表，
顺序不同会让该页得分偏低。报出低分页后先看「首 100 字符」和缺失词条再判断。

用法：
    python check_pdf_coverage.py --pdf <书.pdf> --source-dir <书>/source_en [--threshold 0.9] [--show 5]
退出码：全部通过 0，存在低分页 1。
"""
import argparse, os, re, sys

NGRAM = 6
TRANS = str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '—': '-', '–': '-',
                       '…': '.', '\u00a0': ' '})


def grams(text):
    t = text.translate(TRANS).lower()
    w = re.findall(r"[a-z0-9$%.']+", t)
    return [' '.join(w[i:i + NGRAM]) for i in range(max(0, len(w) - NGRAM + 1))]


def nums(text):
    """抽出数字型 token（含 $ 金额与百分比），去掉千位逗号；用于发现表格行的整行丢失。"""
    out = set()
    for m in re.findall(r'\$?\d[\d,]*(?:\.\d+)?%?', text):
        v = m.replace(',', '')
        out.add(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--source-dir', required=True)
    ap.add_argument('--threshold', type=float, default=0.9)
    ap.add_argument('--show', type=int, default=8, help='每个低分页最多列几条缺失词条')
    ap.add_argument('--min-number', type=int, default=100,
                    help='数字缺失检查的下限（过滤页码等噪声）')
    args = ap.parse_args()

    try:
        import fitz
    except ImportError:
        sys.exit('需要 PyMuPDF：pip install pymupdf')

    src, src_nums = set(), set()
    for fn in sorted(os.listdir(args.source_dir)):
        if fn.endswith('.txt'):
            txt = open(os.path.join(args.source_dir, fn), encoding='utf-8').read()
            src |= set(grams(txt))
            src_nums |= nums(txt)
    if not src:
        sys.exit('source 目录没有 txt：%s' % args.source_dir)

    doc = fitz.open(args.pdf)
    low, numbad = [], []
    for i in range(doc.page_count):
        raw = doc[i].get_text()
        g = grams(raw)
        if len(g) >= 5:
            hit = sum(1 for x in g if x in src)
            r = hit / len(g)
            if r < args.threshold:
                low.append((i + 1, len(g), r, [x for x in g if x not in src][:args.show], raw))
        # 数字核查：页面上「≥ --min-number 且不在源文」的数字（排除页码邻域噪声）
        pno = i + 1
        miss_nums = []
        for v in nums(raw):
            plain = v.lstrip('$').rstrip('%')
            try:
                f = float(plain)
            except ValueError:
                continue
            if f < args.min_number or v in src_nums:
                continue
            if abs(f - pno) <= 2:      # 页码噪声
                continue
            miss_nums.append(v)
        if miss_nums:
            numbad.append((pno, sorted(set(miss_nums)), raw))

    print('源文词条合计 %d；总页数 %d；覆盖率低于 %.0f%% 的页 %d 页'
          % (len(src), doc.page_count, args.threshold * 100, len(low)))
    for p, n, r, miss, head in low:
        print('\n  PDF 第 %d 页  词条 %d  覆盖率 %.1f%%' % (p, n, r * 100))
        print('    首 100 字符: %s' % head.replace('\n', ' ')[:100])
        for x in miss:
            print('    缺失词条: %s' % x)

    print('\n数字缺失核查（≥%d 的数字不在任何 source txt 中）：%d 页' % (args.min_number, len(numbad)))
    for p, ms, head in numbad:
        print('  PDF 第 %d 页  缺失数字: %s' % (p, ', '.join(ms[:12])))
        print('    首 100 字符: %s' % head.replace('\n', ' ')[:100])

    if low or numbad:
        print('\n结论：%d 页覆盖率不达标、%d 页有数字缺失。先判表格误报（单元格顺序不同）与页码噪声，'
              '再判真丢失（补提取后重跑）。' % (len(low), len(numbad)))
        return 1
    print('\n结论：全部页面均已被 source 目录覆盖，且无数字缺失。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
