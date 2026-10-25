#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_rare_chars.py —— 生僻字扫描（字表比对，零 token）

为什么需要：译文里偶有生僻用字，读者会卡住。这类问题同样是**点缺陷**——
整段通顺，就一个字不认识，段落级密度指标（`check_fluency.py`）看不见。

字表：`references/data/常用字表.json`（随 skill 分发）。
  - `senior` = 《通用规范汉字表》一级 3500 ∪ 二级 2989 = 6489，高中及以上常用字。
    **不在其中的字按生僻处理**（默认口径）。
  - `course` = 义务教育课标九年字表（3000 字）。加 `--strict` 时用它，命中更多。

已知边界：这是**字级**检查。用词偏生（如把 spellbound 译成「被摄住」）是**词级**问题，
摄、住都是常用字，本脚本抓不到——词级需要《现代汉语常用词表》，本机无电子版，暂缺。

用法：
    python check_rare_chars.py --book-dir <书目录>
    python check_rare_chars.py --dir <书目录> --suffix _重译版
    python check_rare_chars.py --target <译.md> [--strict]
选项：--strict（用课标 3000 字口径）、--allow 碁,镕（允许保留的专名字符）、--show N（每字给 N 个示例，默认 1）、--json
退出码：有生僻字 1，干净 0。
"""
import argparse
import json
import os
import re
import sys

HAN = re.compile(r'[一-鿿]')
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', 'references', 'data', '常用字表.json')


def load_chars():
    with open(DATA, encoding='utf-8') as f:
        d = json.load(f)
    return set(d['senior']), set(d['course'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--dir')
    ap.add_argument('--target')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--strict', action='store_true', help='用课标九年字表口径')
    ap.add_argument('--allow', default='', help='允许保留的专名字符，逗号分隔（如 碁,镕）')
    ap.add_argument('--show', type=int, default=1)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    senior, course = load_chars()
    allow = course if args.strict else senior
    allowed = {c for c in args.allow if c.strip() and c not in ',，'}
    label = '课标九年字表' if args.strict else '通用规范常用字表（6489）'

    files = []
    if args.target:
        files = [args.target]
    else:
        d = args.dir or args.book_dir
        if not d:
            sys.exit('需要 --book-dir / --dir / --target 之一')
        tgt = os.path.join(d, 'zh')
        if not os.path.isdir(tgt):
            tgt = d
        files = [os.path.join(tgt, f) for f in sorted(os.listdir(tgt))
                 if f.endswith('.md') and (args.suffix or '') in f]
    if not files:
        sys.exit('未找到 .md')

    report, bad = {}, 0
    for fp in files:
        lines = open(fp, encoding='utf-8').read().splitlines()
        found = {}
        for i, ln in enumerate(lines, 1):
            if ln.lstrip().startswith(('```', '![', '~~~')):
                continue
            for ch in HAN.findall(ln):
                if ch not in allow and ch not in allowed:
                    found.setdefault(ch, []).append((i, ln.strip()[:60]))
        if found:
            bad += 1
            print('✗ %s（生僻字 %d 种，共 %d 次）'
                  % (os.path.basename(fp), len(found), sum(len(v) for v in found.values())))
            for ch, occ in sorted(found.items(), key=lambda kv: -len(kv[1])):
                print('   「%s」×%d  例：行 %d %s' % (ch, len(occ), occ[0][0], occ[0][1]))
                for ln, sn in occ[1:1 + args.show]:
                    print('              行 %d %s' % (ln, sn))
        else:
            print('✓ %s 无生僻字' % os.path.basename(fp))
        report[os.path.basename(fp)] = {c: [o[0] for o in v] for c, v in found.items()}
    print('\n口径：%s；文件 %d 个，有生僻字 %d 个' % (label, len(files), bad))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
