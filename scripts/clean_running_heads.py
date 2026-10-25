#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_running_heads.py —— 扫描件／OCR 源文的**重复页眉**清理（零 token）

为什么需要（2026-10-07，《某扫描书》实测）：
    扫描书每一页顶部都印着页眉（章名或节名的全大写版），OCR 会把它们读成独立一行。
    源文里因此夹着几十个 `KILL MODE`／`LOOPING`／`ONBOARDING: SCHEDULE & TRAINING`；
    **译者会把这些独立成行的全大写短行当成标题**，译成 `## 杀手模式` 之类，于是一章里
    冒出 3–8 个重复标题（实测 4 章样本里 10/26/22 个标题，多数是页眉变的）。

判据（确定性；形态必过，频次与同名**二者其一**）：
    · **形态**：整块全大写（去掉非字母后 `isupper()`），字母 8–60 个，整行 ≤70 字符
    · **频次**：归一化（去空格与标点、转小写）后，**同一文件内出现 ≥2 次**
    · **同名**：该行是 `#` 级标题，且归一化后与同文件某个 **Title Case 的 `#` 标题**同名

频次为什么用「≥2」：页眉的 OCR 形态不稳定（`KILLMODE`／`KILL MODE`／
    `SOMEOUTBOUNDSETPHONESCRIPT` 三种写法），归一化能统一；而**章标题本身是 Title Case
    （`Kill Mode`）**，不满足「全大写」这道判据，所以形态+频次不会误删章标题。

零改写：**只删整块，不改任何行内字符**。落盘前打印将删的块，人工可核对。

用法：
    python clean_running_heads.py --source-dir <书>/source_en            # dry-run（.txt 源）
    python clean_running_heads.py --source-dir <书>/source_en --apply    # 落盘
    python clean_running_heads.py --source-dir <书>/source_en --ext .md  # Markdown 源文
        # 默认只扫 .txt；Anna's Archive 等 Markdown 转换产物必须显式给 --ext .md。
选项：--min-count 2（同文件内最少出现次数）；--max-len 70（整块字符上限）
      --footers 同时清页脚；页脚正则来自 references/data/footers.json。
"""
import argparse
import collections
import glob
import io
import json
import os
import re
import sys

# 页脚/版权行规则表（与脚本同 skill）：patterns 通用 + book_specific 单本实测。
DEFAULT_FOOTERS_DATA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'data', 'footers.json')

# 数据文件缺失时的最小基线；正常路径读 footers.json，不把书专属正则写回代码。
FALLBACK_FOOTERS = [
    r'copyrigh\w*\s*[©@O0]?\s*20\d\d\s*by\s*[\w\s,\.]{0,26}',
    r'NOT\s*FOR\s*DISTRIBUTION\s*\d{0,4}',
    r'SCAN\s*ME\s*\d{0,4}',
    r'版权\s*[©@]?\s*20\d\d[^。\n]{0,44}',
    r'版权所有', r'禁止分发', r'不得分发', r'INTERNAL DOCUMENT',
]


def load_footer_patterns(path):
    """读 footers.json；缺失或为空时退回最小通用基线。"""
    if path and os.path.exists(path):
        cfg = json.load(open(path, encoding='utf-8'))
        patterns = list(cfg.get('patterns', [])) + list(cfg.get('book_specific', []))
        if patterns:
            return patterns
        print('提示：%s 里没有 patterns，改用脚本内建基线' % path)
    elif path:
        print('提示：页脚规则表 %s 不存在，改用脚本内建基线' % path)
    return FALLBACK_FOOTERS


def footer_re(patterns):
    return re.compile('|'.join('(?:%s)' % p for p in patterns), re.I)


def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', required=True)
    ap.add_argument('--min-count', type=int, default=2)
    ap.add_argument('--max-len', type=int, default=70)
    ap.add_argument('--ext', default='.txt',
                    help='扫哪些扩展名：源文默认 .txt；Markdown 源文（如 Anna\'s Archive 转换产物）'
                         '必须显式传 --ext .md，否则会报「没找到 .txt」')
    ap.add_argument('--footers', action='store_true',
                    help='同时清「页脚」：短块且含版权/禁分发字样（版权行是混合大小写，'
                         '原来的「全大写」判据抓不到，实测某书每页一行、全源文 154 处）。'
                         '正则来自 references/data/footers.json')
    ap.add_argument('--keep-dir', default='', help='该前缀的文件不清页脚（如 00_front，那里是真版权页）')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()

    FOOT = footer_re(load_footer_patterns(DEFAULT_FOOTERS_DATA))

    files = sorted(glob.glob(os.path.join(a.source_dir, '*' + a.ext)))
    if not files:
        sys.exit('没找到 %s 文件：%s（Markdown 源文请加 --ext .md）' % (a.ext, a.source_dir))

    grand = 0
    for f in files:
        text = io.open(f, encoding='utf-8').read()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
        cand = collections.Counter()
        # 真章节名（`#` 级、且**不是**全大写）——用来抓「只出现一次」的页眉：
        # 页眉是章名的全大写版，而章名是 Title Case；同文件一旦存在这个 Title Case 名，
        # 全大写同名行就必是页眉，与它出现几次无关（2026-10-07 《某商业书》实测，
        # 这半条判据抓出 3 个频次判据漏掉的单次页眉，且**无假阳性**）。
        title_keys = set()
        for b in blocks:
            if not b.startswith('#'):
                continue
            L = re.sub(r'[^A-Za-z]', '', b)
            if not (L and L.isupper()):
                title_keys.add(norm(re.sub(r'^#+\s*', '', b)))
        for b in blocks:
            if b.startswith('[') or len(b) > a.max_len:
                continue
            L = re.sub(r'[^A-Za-z]', '', b)
            if L and L.isupper() and 8 <= len(L) <= 60:
                cand[norm(b)] += 1
        def _headform(b):
            if b.startswith('[') or len(b) > a.max_len:
                return False
            L = re.sub(r'[^A-Za-z]', '', b)
            return bool(L) and L.isupper() and 8 <= len(L) <= 60

        # ⚠️ heads 存**原始块文本**，不能存归一化键——归一化抹掉大小写，按键删会把同名的
        #    Title Case 真标题一起带走（2026-10-07 实测：`# START HERE` 的键把 `# Start Here`
        #    也删了，整章正文被并进上一章）。
        heads = {b for b in blocks if _headform(b) and cand[norm(b)] >= a.min_count}
        # 同名页眉：**全大写**的 `#` 块与某个 Title Case `#` 标题同名 → 一并删。
        # ⚠️ 还要试「按冒号切开的首段」：Playbook 系列的页眉形如 `# GOATED ADS : <当前节名>`，
        #    冒号后每节不同 → 频次永远是 1，且整体带书名前缀 → 与任何真标题都不同名；
        #    只有取冒号前的 `GOATED ADS` 才能与真标题 `GOATed Ads` 对上（2026-10-07 实测漏删 1 处）。
        for b in blocks:
            if not (b.startswith('#') and _headform(b)):
                continue
            body = re.sub(r'^#+\s*', '', b)
            keys = {norm(body), norm(re.split(r'[:：]', body)[0])}
            if keys & title_keys:
                heads.add(b)
        if not heads and not a.footers:
            continue          # ⚠️ 不能写成 `if not heads: continue`——那样「没有页眉命中」时会连页脚一起跳过（实测踩过）
        out, dropped, stripped = [], [], []
        keep_foot = a.keep_dir and os.path.basename(f).startswith(a.keep_dir)
        for b in blocks:
            if b in heads:                 # heads 存原始块文本（见上）
                dropped.append(b)
                continue
            if (a.footers and not keep_foot and not b.startswith('[') and FOOT.search(b)):
                # ⚠️ **只抠掉页脚那截，不删整块**——OCR 常把页脚与下句粘在同一块里，
                #    删整块会连带删掉正文（实测踩过：`And do you see yourself taking…` 被整块删掉）。
                #    仅当页脚**占整块 ≥60%** 时才认定「这块就是页脚」并整块删。
                cover = sum(m.end() - m.start() for m in FOOT.finditer(b))
                if cover < 0.6 * len(b):
                    rest = re.sub(r'\s{2,}', ' ', FOOT.sub(' ', b)).strip(' \t\n|-—·')
                    if rest:
                        out.append(rest)
                    stripped.append(b)
                    continue
                dropped.append(b)
                continue
            out.append(b)
        if not dropped and not stripped:      # ⚠️ 只抠不删时也要落盘（踩过：只做替换的文件没被写回）
            continue
        grand += len(dropped)
        print('  %-40s 删 %2d ／ 抠 %2d：%s' % (os.path.basename(f), len(dropped), len(stripped),
                                          ' / '.join(b[:26] for b in (dropped + stripped)[:3])))
        if a.apply:
            io.open(f, 'w', encoding='utf-8').write('\n\n'.join(out) + '\n')

    print('\n共删 %d 个页眉块%s' % (grand, '（已落盘）' if a.apply else '（dry-run，未落盘）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
