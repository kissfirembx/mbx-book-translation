#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_quality_checks.py —— 译文质量回归检查（**判定零 token**）

为什么这么设计（2026-10-07 定，来自三次翻车的教训）：

- 之前用「同一批文本跑一遍 + 人工/LLM 盲评」来验证 skill 好不好——**样本少、成本高、判定还靠人**，
  12 段得出「约束有害」、换成整章又翻成「约束有益」，两次结论相反。
- 根因：**n=1 时，代理之间的随机差异比要测的效应还大**。
- 正解：**n = 样本数**，而不是运行次数。把要验证的**具体行为**写成正则断言，
  拿**很多条短样本**去覆盖它，逐条机检算出**命中率**。这样既扩大覆盖面，又几乎不花 token。

用法：
    python run_quality_checks.py --expect <expectations.json> --dir <含译稿的目录>
选项：--json
退出码：有未通过 1，全通过 0。

`expectations.json` 格式：
    {
      "suite": "skill_ab",
      "cases": [
        {"id": "...", "why": "这条在验什么",
         "min": {"正则": 最少出现次数},        # 可选
         "max": {"正则": 最多出现次数}}        # 可选
      ]
    }
判定：目录下每个 .md 都套用全部用例；`min` 不足或 `max` 超出即该用例不通过。
"""
import argparse
import glob
import json
import os
import re
import sys


def count(text, pat):
    return len(re.findall(pat, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--expect', required=True, help='expectations.json 路径')
    ap.add_argument('--dir', required=True, help='含译稿 .md 的目录')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    spec = json.load(open(args.expect, encoding='utf-8'))
    cases = spec.get('cases', [])
    files = sorted(glob.glob(os.path.join(args.dir, '*.md')))
    if not files:
        sys.exit('目录里没有 .md：%s' % args.dir)

    print('质量回归检查 ｜ 套件：%s ｜ 用例 %d 条 ｜ 译稿 %d 份'
          % (spec.get('suite', '?'), len(cases), len(files)))
    print('=' * 66)

    table = {}
    for fp in files:
        text = open(fp, encoding='utf-8').read()
        name = os.path.basename(fp)
        row = []
        for c in cases:
            # 用例可只作用于某一份译稿：`"file": "01_gamechanger"`（前缀匹配文件名）
            only = c.get('file')
            if only and only not in name:
                row.append((c['id'], True, [], c.get('why', '')))
                continue
            ok = True
            detail = []
            for pat, n in (c.get('min') or {}).items():
                got = count(text, pat)
                if got < n:
                    ok = False
                detail.append('min %s %d/%d' % (pat, got, n))
            for pat, n in (c.get('max') or {}).items():
                got = count(text, pat)
                if got > n:
                    ok = False
                detail.append('max %s %d/%d' % (pat, got, n))
            row.append((c['id'], ok, detail, c.get('why', '')))
        table[name] = row

    # 逐份打印：分母只算「适用于这份译稿」的用例，不把 file-specific 跳过项算成通过
    for fname, row in table.items():
        applicable = [i for i, c in enumerate(cases)
                      if not c.get('file') or c['file'] in fname]
        passed = sum(1 for i in applicable if row[i][1])
        print('\n【%s】%d/%d 通过' % (fname, passed, len(applicable)))
        for i in applicable:
            cid, ok, detail, why = row[i]
            mark = '✓' if ok else '✗'
            print('   %s %-22s %s' % (mark, cid, '' if ok else '  ← ' + why))
            if not ok:
                for d in detail:
                    print('        %s' % d)

    # 汇总：每个用例跨译稿的命中率（这才是「n=样本数」的用法）
    print('\n' + '=' * 66)
    print('用例通过率（跨 %d 份译稿）' % len(files))
    for i, c in enumerate(cases):
        if c.get('file'):
            hit = [f for f in table if c['file'] in f]
            if not hit:
                continue
            n, tot = sum(1 for f in hit if table[f][i][1]), len(hit)
            print('   %-22s %s %d/%d  (仅 %s)' % (c['id'], '█' * n + '·' * (tot - n), n, tot, c['file']))
            continue
        n = sum(1 for f in table if table[f][i][1])
        bar = '█' * n + '·' * (len(files) - n)
        print('   %-22s %s %d/%d' % (c['id'], bar, n, len(files)))

    if args.json:
        print(json.dumps({f: {cid: ok for cid, ok, _d, _w in row}
                          for f, row in table.items()}, ensure_ascii=False, indent=1))

    bad = any(not ok for row in table.values() for _i, ok, _d, _w in row)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
