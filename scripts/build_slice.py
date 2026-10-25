#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_slice.py —— 从术语库自动生成**本章内联切片**（译者 prompt 用）

为什么必须自动化（2026-10-07，同一天栽了两次同一个坑）：
    · 译者只读源文一个文件，**看不到术语库**。规则在库里、没内联 = 没写。
    · 第一次栽在「译名没内联」——译者自己音译了人名；
    · 第二次栽在「作者档案的强调方式没内联」——档案写着「斜体表示强调→译文用加粗」，
      译者照抄了 `*斜体*`，整章 219 处符号错。
    **两次都是「我记得要内联」的失败。所以改成脚本生成，不靠记。**

做什么：拿一章源文，去术语库里**按英文词命中**筛出本章要用的条目，拼成可直接粘进 prompt 的三块：
    · `{TERMS_BLOCK}`   本章命中的术语 + 专名译名
    · `{IDIOM_BLOCK}`   本章命中的习语
    · `{STYLE_BLOCK}`   作者档案里「影响逐句落笔」的条目（强调方式/口语程度/修辞习惯）

用法：
    python build_slice.py --chapter <书>/source_en/07_ch5_charge.txt \\
                          --author alex-hormozi --type business
    # 输出到文件（直接贴进 prompt）：--out slice.md
    # 看命中了哪些：默认就会打印统计
选项：--terms-dir（默认从 book 目录上溯找 `_术语体系`）、--out、--json
退出码：恒 0。
"""
import argparse
import glob
import io
import json
import os
import re
import sys

from mbx_config import terms_dir

ROW = re.compile(r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|(.*)$')
HEAD = re.compile(r'^#{1,6}\s')
SECTION_TERMS = re.compile(r'^#{2,4}\s*(?:类型)?术语')
# 2026-10-24 修：类型库标题是 `## 类型术语表`，旧正则只认「术语」开头 → **类型库术语从未进过切片**。
# 作者库标题是 `## 术语表（作者统一译法）`，两个都要认。
SECTION_IDIOM = re.compile(r'^#{2,4}\s*习语')
SECTION_STYLE = re.compile(r'^#{2,4}\s*写作风格')
# `## 语义不变量` 不参与切片（由阶段 2.6 并入书级 FORMAT_BLOCK）；显式跳过，
# 防止它下面的表格被前一个 section 的状态误当术语／习语。
# `## 术语例外清单` 同理：它的列是「书名 | 术语 | 本书译法 | …」，按术语表解析会得到
# 「书名→术语」这种错映射（2026-10-24 修）。
SECTION_SKIP = re.compile(r'^#{2,4}\s*(?:语义不变量|术语例外)')
# 作者档案里「影响逐句落笔」的条目（内联时必须带上的那几条）
STYLE_KEYS = ('强调方式', '口语化程度', '修辞习惯', '叙事结构', '对话处理', '数字使用', '页首格言', '作者注')


def parse_tables(path):
    """把一个 .md 里的表格按章节归到 'terms' / 'idioms' / 'style'。"""
    terms, idioms, style, sec = [], [], [], None
    for ln in io.open(path, encoding='utf-8'):
        s = ln.rstrip()
        if HEAD.match(s):
            if SECTION_SKIP.match(s):
                sec = None
            elif SECTION_IDIOM.match(s):
                sec = 'idioms'
            elif SECTION_TERMS.match(s):
                sec = 'terms'
            elif SECTION_STYLE.match(s):
                sec = 'style'
            elif sec == 'style' and not SECTION_STYLE.match(s):
                sec = None
            continue
        if sec == 'style':
            if s.startswith('- '):
                style.append(s[2:].strip())
            continue
        if not s.startswith('|'):
            # 表格之外的段落：术语库里某些档案把风格写成列表，已由上面处理
            continue
        m = ROW.match(s)
        if not m:
            continue
        en, zh, rest = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if set(en) <= set('-: ') or en in ('英文', '英文习语／句式'):
            continue
        if sec == 'idioms':
            idioms.append((en, zh, rest))
        elif sec == 'terms':
            terms.append((en, zh, rest))
    return terms, idioms, style


def hit(en, text_lower):
    """英文词是否在本章出现：整词优先，长词条退化为子串。

    候选词按 `/` 拆（`LTV / CLV` 这类同义写法）；但**先去掉括号内的说明**——
    `Objections（Time / Money / Decision Maker / …）` 拆出来会得到 `Money` 这种通用词，
    几乎每章都假命中（2026-10-24 实测：整类商业书每章都多出「异议（时间/金钱…）」）。
    """
    en = re.sub(r'[（(][^）)]*[）)]', ' ', en)
    for cand in re.split(r'\s*/\s*', en):
        c = cand.strip().lower()
        if not c or len(c) < 2:
            continue
        if re.search(r'[a-z]', c):
            if re.search(r'(?<![a-z])' + re.escape(c) + r'(?![a-z])', text_lower):
                return True
        elif c in text_lower:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chapter', required=True)
    ap.add_argument('--author', default=None, help='作者 slug，如 alex-hormozi')
    ap.add_argument('--type', dest='type_slug', default=None, help='类型 slug，如 business')
    ap.add_argument('--terms-dir', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    d = a.terms_dir
    if not d:
        # 章节在 `<书>/source_en/` 下；术语体系在 `<书>` 的**上一级**、`$MBX_TERMS_DIR` 或 `./_术语体系`
        book = os.path.dirname(os.path.dirname(os.path.abspath(a.chapter)))
        cand = [os.path.join(os.path.dirname(book), '_术语体系'),
                terms_dir(), os.path.join('.', '_术语体系')]
        d = next((c for c in cand if os.path.isdir(c)), cand[-1])
    if not os.path.isdir(d):
        sys.exit('术语体系目录不存在：%s' % d)

    text = io.open(a.chapter, encoding='utf-8', errors='replace').read()
    low = text.lower()

    files = []
    if a.author:
        files.append(os.path.join(d, a.author + '.md'))
    if a.type_slug:
        files.append(os.path.join(d, a.type_slug + '.md'))
    terms, idioms, style = [], [], []
    for fp in files:
        if os.path.exists(fp):
            t, i, s = parse_tables(fp)
            terms += t
            idioms += i
            style += s

    seen, hit_terms = set(), []
    for en, zh, rest in terms:
        if en in seen:
            continue
        if hit(en, low):
            seen.add(en)
            hit_terms.append((en, zh, rest))
    seen_i, hit_idi = set(), []
    for en, zh, rest in idioms:
        if en in seen_i:
            continue
        if hit(en, low):
            seen_i.add(en)
            hit_idi = [(en, zh, rest)] and hit_idi + [(en, zh, rest)]

    style_keep = [s for s in style if any(k in s for k in STYLE_KEYS)] or style[:6]

    L = []
    L.append('【术语（本章切片，必须遵守；括号内为备注／语境条件，语境不符按字面义译）】')
    parts = []
    for e, z, rest in hit_terms:
        note = rest.strip().strip('|').strip()
        parts.append('%s→%s%s' % (e, z, ('（%s）' % note) if note else ''))
    L.append('；'.join(parts) or '（本章未命中已登记术语）')
    L.append('')
    L.append('【习语（命中即用规定说法，禁止字面直译）】')
    idl = []
    for e, z, rest in hit_idi:
        bad = re.findall(r'不写「([^」]+)」', rest)
        idl.append('%s→%s%s' % (e, z, ('（不写「%s」）' % '／'.join(bad)) if bad else ''))
    L.append('；'.join(idl) or '（本章未命中已登记习语）')
    L.append('')
    L.append('【作者风格（逐句落笔时必须遵守）】')
    L += ['- ' + s for s in style_keep]

    out = '\n'.join(L)
    print('源文：%s' % os.path.basename(a.chapter))
    print('术语库：%s' % d)
    print('命中：术语 %d / %d 条；习语 %d / %d 条；风格 %d 条'
          % (len(hit_terms), len(terms), len(hit_idi), len(idioms), len(style_keep)))
    print('=' * 68)
    print(out)
    if a.out:
        io.open(a.out, 'w', encoding='utf-8').write(out + '\n')
        print('\n已写：%s' % a.out)
    if a.json:
        print(json.dumps({'terms': hit_terms, 'idioms': hit_idi, 'style': style_keep},
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
