#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan_batches.py —— 按模型上下文窗口给子 Agent 分批

输入一本书的 `source_en/` 章节，按「源文 token + 译文 token + 固定开销」算每批
能装多少章，而不是固定「一章一个 agent」或「全书硬塞」。

用法：
    python plan_batches.py --book-dir <书> --context-window 200000
    python plan_batches.py --book-dir <书> --context-window 1000000 --json
选项：--fixed-overhead（默认 25000）、--safety（默认 0.8）、
      --output-ratio（默认 1.6，中文字/英文词）、--max-output-chars（默认 30000）
"""
import argparse
import glob
import json
import os
import re
import sys

WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def chapter_files(book_dir):
    d = os.path.join(book_dir, 'source_en')
    files = []
    for ext in ('*.txt', '*.md'):
        files.extend(glob.glob(os.path.join(d, ext)))
    return sorted(files)


def measure(fp, output_ratio):
    text = open(fp, encoding='utf-8', errors='replace').read()
    words = len(WORD.findall(text))
    chars = len(re.sub(r'\s', '', text))
    return {
        'file': os.path.basename(fp),
        'words': words,
        'source_tokens': chars / 4.0,
        'output_chars': words * output_ratio,
        'output_tokens': words * output_ratio,
    }


def main():
    ap = argparse.ArgumentParser(description='按模型上下文窗口给子 Agent 分批')
    ap.add_argument('--book-dir', required=True)
    ap.add_argument('--context-window', type=int, required=True,
                    help='模型最大上下文 token（如 200000 / 1000000）')
    ap.add_argument('--fixed-overhead', type=int, default=25000,
                    help='每个 agent 的固定开销 token（默认 25000）')
    ap.add_argument('--safety', type=float, default=0.8,
                    help='安全系数，只用到窗口的 80%%（默认 0.8）')
    ap.add_argument('--output-ratio', type=float, default=1.6,
                    help='中文字/英文词（默认 1.6）')
    ap.add_argument('--max-output-chars', type=int, default=30000,
                    help='单 agent 最多中文字数（默认 30000）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    files = chapter_files(a.book_dir)
    if not files:
        sys.exit('没有 source_en/*.txt 或 *.md：%s' % a.book_dir)
    if a.context_window <= a.fixed_overhead:
        sys.exit('上下文窗口必须大于固定开销')

    budget = int(a.context_window * a.safety) - a.fixed_overhead
    if budget <= 0:
        sys.exit('窗口太小：安全系数后的预算减去固定开销 <= 0')
    rows = [measure(f, a.output_ratio) for f in files]

    batches, cur = [], []
    cur_tokens = cur_zh = 0
    for r in rows:
        need = r['source_tokens'] + r['output_tokens']
        too_big = need > budget or r['output_chars'] > a.max_output_chars
        if cur and (cur_tokens + need > budget or cur_zh + r['output_chars'] > a.max_output_chars):
            batches.append((cur, cur_tokens, cur_zh))
            cur, cur_tokens, cur_zh = [], 0, 0
        cur.append(r)
        cur_tokens += need
        cur_zh += r['output_chars']
        if too_big and len(cur) == 1:
            batches.append((cur, cur_tokens, cur_zh))
            cur, cur_tokens, cur_zh = [], 0, 0
    if cur:
        batches.append((cur, cur_tokens, cur_zh))

    if a.json:
        print(json.dumps({
            'context_window': a.context_window,
            'safety': a.safety,
            'fixed_overhead': a.fixed_overhead,
            'budget_tokens': budget,
            'max_output_chars': a.max_output_chars,
            'total_chapters': len(rows),
            'total_batches': len(batches),
            'batches': [{
                'chapters': [r['file'] for r in b],
                'words': sum(r['words'] for r in b),
                'output_chars': round(zh),
                'tokens': round(tok),
                'utilization': round(tok / budget, 3) if budget else 0,
                'over_budget': tok > budget or zh > a.max_output_chars,
            } for b, tok, zh in batches],
        }, ensure_ascii=False, indent=2))
        return 0

    print('模型窗口：%s ｜ 安全系数 %.0f%% ｜ 固定开销 %s ｜ 可用预算 %s token'
          % ('{:,}'.format(a.context_window), a.safety * 100,
             '{:,}'.format(a.fixed_overhead), '{:,}'.format(budget)))
    print('单 agent 上限：%s 中文字' % '{:,}'.format(a.max_output_chars))
    print('─' * 72)
    for i, (b, tok, zh) in enumerate(batches, 1):
        print('批次 %d：%d 章 ｜ %s 词 ｜ %s 中文字 ｜ %s token ｜ 占用 %.0f%%%s'
              % (i, len(b), '{:,}'.format(sum(r['words'] for r in b)),
                 '{:,.0f}'.format(zh), '{:,}'.format(round(tok)),
                 tok / budget * 100 if budget else 0,
                 '  ⚠ 超预算/超产出上限' if (tok > budget or zh > a.max_output_chars) else ''))
        print('   ' + ' / '.join(r['file'] for r in b))
    print('─' * 72)
    print('共 %d 章 → %d 个 agent' % (len(rows), len(batches)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
