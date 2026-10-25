#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_glossary_readability.py —— 术语库「规定译法」可读性**排序器**（零 token）

⚠️ **这是排序器，不是判定器。退出码恒 0。**
    第一版写成「名词堆叠检测器」，实测假阳性高得没法用——`认知行为疗法`、`价值观与承诺`、
    `精神科医生`、`每日待办清单` 全被报出来，而这些都是再正常不过的中文术语。
    **「读起来别扭」是语境属性，不是词形属性**：同一个词放进某句别扭、放进另一句就正常。
    所以本脚本只做一件事：**把术语库里有「名词硬拼风险」的条目按长度排出来，交人扫一眼**，
    不判对错、不当门禁。

为什么要看这份清单（2026-10-07，A/B 对照实验暴露）：
    术语库把某条译法定死之后，**译者会照用**——哪怕那条译法本身就是翻译腔。
    实测 `Perceived Likelihood of Achievement → 感知达成可能性` 是四个名词连缀，
    有 skill 的译文组「双重修饰」指标因此**高于**无 skill 组。
    **规定译法不天然优于自然表达。术语库需要定期回看。**

两层设计（本脚本服务这条分层）：
    · **锚词**：短、可统一、进正文。判据是「单看能懂、放句子里不别扭」。
    · **正文表达**：语境里允许展开成释义——`感知达成可能性` 在正文里可以写
      「你觉得这事成的可能性有多大」，锚词只在需要强调处出现。
      **用锚词的长度去套所有句子，正是翻译腔的来路。**

用法：
    python check_glossary_readability.py --terms-dir <术语体系目录>
    python check_glossary_readability.py --term "感知达成可能性"
选项：--min-han（默认 5，只列长度 ≥ 该值的条目）、--top（默认 40）、--json
退出码：恒 0。
"""
import argparse
import glob
import io
import json

from mbx_config import terms_dir
import os
import re
import sys

HAN = re.compile(r'[一-鿿]')
ROW = re.compile(r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|')
PAREN = re.compile(r'[（(][^）)]*[）)]')
# 「留意」标记：3 个以上 2 字名词块连缀，且带名词化尾巴（性/化/度/率）
NOMINAL_TAIL = re.compile(r'[性化度率]$')


def han_of(s):
    return len(HAN.findall(PAREN.sub('', s).strip()))


def note(zh):
    """按 `/／、` 拆开多义项，只判最长的那一项——一行里并列三个词不是「一个长术语」。"""
    parts = [re.sub(r'\s+', '', x) for x in re.split(r'[/／、]', PAREN.sub('', zh))]
    s = max(parts, key=han_of) if parts else ''
    n = han_of(s)
    if re.match(r'^([一-鿿]{2}){3,}$', s) and NOMINAL_TAIL.search(s):
        return '名词块连缀 + 名词化尾巴，正文里可考虑改释义写法'
    if n >= 8 and not re.search(r'[的地得与和或以等由]', s):
        return '偏长且无功能词，建议回看'
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--terms-dir', default=None)
    ap.add_argument('--term', default=None)
    ap.add_argument('--min-han', type=int, default=5)
    ap.add_argument('--top', type=int, default=40)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.term:
        n = han_of(a.term)
        print('  %s —— %d 个汉字%s' % (a.term, n, ('  ⚠ ' + note(a.term)) if note(a.term) else ''))
        return 0

    d = a.terms_dir or terms_dir()
    if not os.path.isdir(d):
        sys.exit('术语体系目录不存在：%s（用 --terms-dir 指定）' % d)

    rows, flagged = [], 0
    for fp in sorted(glob.glob(os.path.join(d, '*.md'))):
        for ln in io.open(fp, encoding='utf-8'):
            s = ln.strip()
            if not s.startswith('|'):
                continue
            m = ROW.match(s)
            if not m or set(m.group(1)) <= set('-: '):
                continue
            zh = m.group(2).strip()
            n = han_of(zh)
            if n < a.min_han:
                continue
            nt = note(zh)
            if nt:
                flagged += 1
            rows.append((n, nt, m.group(1).strip(), zh, os.path.basename(fp)))

    rows.sort(key=lambda r: -r[0])
    print('术语库「规定译法」可读性清单（排序器，供回看；不是错）')
    print('说明：只列汉字数 ≥%d 的条目，按长度从长到短。带 ⚠ 的优先看。' % a.min_han)
    print('=' * 74)
    for n, nt, en, zh, fn in rows[:a.top]:
        print('  %s [%2d] %-30s → %-22s %s' % ('⚠' if nt else ' ', n, en[:30], zh[:22], nt))
    print('=' * 74)
    print('共 %d 条（其中标 ⚠ 的 %d 条）；文件 %d 个'
          % (len(rows), flagged, len(glob.glob(os.path.join(d, '*.md')))))
    print('提醒：规定译法不天然优于自然表达。长词条在正文里可展开成释义，锚词只在需要强调处出现。')
    if a.json:
        print(json.dumps([{'en': r[2], 'zh': r[3], 'han': r[0], 'note': r[1]} for r in rows],
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
