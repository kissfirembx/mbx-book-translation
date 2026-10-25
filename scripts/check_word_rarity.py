#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_word_rarity.py —— 生僻/不地道**用词**候选清单（词级，零 token 出候选）

为什么需要：字级检查（`check_rare_chars.py`）抓不到「用词偏生」——把 spellbound 译成
「被摄住」时，「摄」「住」都是常用字，只有**词**是生造的。这一类是点缺陷，段落密度
指标（`check_fluency.py`）同样看不见。

**重要：本脚本只出候选，不做判定。** 实测（2026-10-07）：
  - 用 jieba 词典（34.9 万词）做未登录词检测，「摄住」**能抓到**；
  - 但同一批候选里绝大多数是**分词伪影**（「举个」「更高」「我担」「地凑」——jieba 把
    虚词与实词粘成的假词）与**合理新造术语**。
  - 根因：「摄住」（不地道的生造搭配）与「举个」（分词伪影）在词典意义上**不可区分**——
    两者都是「两个常用单字被粘成的未登录词」。纯词典手段无法分开。
所以本脚本的定位是**给一次廉价 LLM 判定（或人工扫）喂候选**，不是自动报警、不进任何门禁。
实测一个 25 章的书出 ~300 条候选，交 LLM 判定约 3k token。

已做的降噪：
  1. 豁免 `<术语体系>/` 里出现过的词（本书合法术语不该报警，如「触达」「获客」）；
  2. 剔除「全部由高频单字组成」的伪影（`--top-chars` 控制，默认 400）；
  3. 只保留**全书出现次数 ≤ `--max-count`**（默认 1）的词——伪影多由高频虚词反复生成而重复，
     真异常用词通常只出现一两次。

依赖：`pip install jieba`（其自带 `dict.txt` 提供词与词频，装完即可离线用）。

用法：
    python check_word_rarity.py --book-dir <书目录>
    python check_word_rarity.py --dir <书目录>/zh --suffix _重译版
    python check_word_rarity.py --book-dir <书目录> --out 候选.md --max-count 2
选项：--terms-dir、--max-count、--top-chars、--limit、--out、--json
退出码：恒 0（候选清单不是判定）。
"""
import argparse

from mbx_config import terms_dir
import collections
import glob
import json
import os
import re
import sys

HAN = re.compile(r'[一-鿿]')
SKIP_PREFIX = ('#', '![', '|', '~', '<')
SPLIT = re.compile(r'[|\s、，,（）()「」『』:：/／\[\]【】]')


def jieba_dict():
    try:
        import jieba
    except ImportError:
        sys.exit('需要 jieba：pip install jieba')
    jieba.initialize()
    path = os.path.join(os.path.dirname(jieba.__file__), 'dict.txt')
    words = {}
    with open(path, encoding='utf-8') as f:
        for ln in f:
            w = ln.split()
            if len(w) >= 2:
                words[w[0]] = int(w[1])
    return jieba, words


def load_terms(terms_dir):
    """术语库里出现过的中文词一律豁免——它们是本书的合法术语，不是生僻用词。"""
    out = set()
    for fp in glob.glob(os.path.join(terms_dir, '*.md')):
        for ln in open(fp, encoding='utf-8'):
            for seg in SPLIT.split(ln):
                seg = seg.strip()
                if len(seg) >= 2 and len(HAN.findall(seg)) == len(seg):
                    out.add(seg)
    return out


def target_files(args):
    if args.dir:
        d, suf = args.dir, args.suffix
    else:
        d, suf = os.path.join(args.book_dir, 'zh'), args.suffix
        if not os.path.isdir(d):
            d = args.book_dir
    files = [f for f in sorted(glob.glob(os.path.join(d, '*.md')))
             if (suf or '') in os.path.basename(f)]
    if not files:
        sys.exit('未找到 .md：%s' % d)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--dir')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--terms-dir', default=terms_dir())
    ap.add_argument('--max-count', type=int, default=1, help='只报全书出现次数 ≤ 此值（默认 1）')
    ap.add_argument('--top-chars', type=int, default=400, help='高频单字表大小（用于剔伪影）')
    ap.add_argument('--limit', type=int, default=300, help='候选上限')
    ap.add_argument('--out')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    if not (args.book_dir or args.dir):
        sys.exit('需要 --book-dir 或 --dir')

    jieba, D = jieba_dict()
    singles = sorted([(w, c) for w, c in D.items() if len(w) == 1], key=lambda x: -x[1])
    topch = {w for w, _c in singles[:args.top_chars]}
    terms = load_terms(args.terms_dir)

    cnt = collections.Counter()
    ctx = {}
    for fp in target_files(args):
        for ln in open(fp, encoding='utf-8'):
            if ln.lstrip().startswith(SKIP_PREFIX) or '`' in ln:
                continue
            for tok in jieba.cut(ln):
                t = tok.strip()
                if len(t) < 2 or len(HAN.findall(t)) != len(t):
                    continue
                if t in D or t in terms:
                    continue
                if all(ch in topch for ch in t):        # 全由高频单字组成 → 伪影嫌疑
                    continue
                cnt[t] += 1
                ctx.setdefault(t, ln.strip()[:60])

    cands = [(t, c) for t, c in cnt.items() if c <= args.max_count]
    cands.sort(key=lambda x: (x[1], -len(x[0])))        # 越少见、越长 → 越靠前
    cands = cands[:args.limit]

    print('生僻用词候选（词级，**不是判定**）')
    print('语料：%d 个文件 | 未登录词 %d 种 | 命中「≤%d 次」%d 种 → 输出前 %d'
          % (len(target_files(args)), len(cnt), args.max_count, len(cands), len(cands)))
    print('提示：候选里混杂分词伪影（「举个」「我担」一类）与合理术语，须交 LLM 或人工判定。')
    print()
    for t, c in cands:
        print('  %-12s x%-2d %s' % (t, c, ctx[t]))

    if args.out:
        rep = ['# 生僻/不地道用词候选（交 LLM 判定，非自动报警）', '',
               '- 语料 %d 文件；未登录词 %d 种；本清单 %d 条（≤%d 次）'
               % (len(target_files(args)), len(cnt), len(cands), args.max_count),
               '- 判定方法：逐条问「这个词在中文里是自然说法吗？有没有更常见的同义说法？」',
               '- 已知假阳性：分词伪影（虚词+实词粘连）、音译专名、行业术语', '',
               '| 候选 | 次数 | 上下文 |', '|---|---|---|']
        for t, c in cands:
            rep.append('| %s | %d | %s |' % (t, c, ctx[t]))
        open(args.out, 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
        print('\n候选清单已写出：%s' % args.out)

    if args.json:
        print(json.dumps([{'word': t, 'count': c, 'context': ctx[t]} for t, c in cands],
                         ensure_ascii=False, indent=1))
    return 0        # 只出候选，不做门禁


if __name__ == '__main__':
    sys.exit(main())
