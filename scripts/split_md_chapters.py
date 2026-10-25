#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_md_chapters.py —— 把一个 Markdown 书稿**按标题级切分成章节文件**

为什么需要（2026-10-07，《某商业书》系列实测）：
    这批书到手就是干净的 Markdown（转换产物），章节就是 `#` 级标题，不需要 OCR／PDF 提取。
    但**不能直接按 `#` 切**就开译——**页眉**（章名的全大写版，如 `# START HERE`）也是 `#` 级，
    直接切会切出几十个假章节（实测《Closing》53 个 `#` 里 36 个是页眉）。所以顺序是：
        `clean_running_heads.py --apply`  →  本脚本 `--level 1`

判据：
    · 以 `#{level}` + 一个空格开头的行 = 章节起点（`# ` 后必须跟空格，避免把 `#tag` 当标题）
    · 第一个标题**之前**的内容（封面／版权／前言）单独成 `01_front.md`
    · 标题 → 文件名 slug：小写、非字母数字转 `-`、去强调标记（`*`/`` ` ``/`_`/`~`）

零改写：只做**切分与文件命名**，不改任何字符、不重排。

用法：
    python split_md_chapters.py --in <book.md> --out <dir>              # 按 `#` 切
    python split_md_chapters.py --in <book.md> --out <dir> --level 2    # 按 `##` 切
选项：
    --prefix-len 2   序号宽度（默认 2 → `01_`）
    --drop-front     丢弃首个标题前的内容（默认保留为 `01_front.md`，封面通常要保留）
    --dry            只打印将生成的文件与规模，不落盘
"""
import argparse
import io
import os
import re
import sys


def slug(title):
    s = re.sub(r'^#+\s*', '', title.strip())
    s = re.sub(r'[*`_~]', '', s)                 # 去掉强调标记，别把 `**SALES**` 带进文件名
    s = re.sub(r'[^A-Za-z0-9]+', '-', s.lower()).strip('-')
    return s or 'sec'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--level', type=int, default=1)
    ap.add_argument('--prefix-len', type=int, default=2)
    ap.add_argument('--drop-front', action='store_true')
    ap.add_argument('--front-until', default=None,
                    help='把首个匹配该正则的 `#` 标题之前的内容并成一个 front，'
                         '如 --front-until "^# Table of Contents"')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    text = io.open(a.src, encoding='utf-8').read().replace('\r\n', '\n')
    lines = text.split('\n')
    pat = re.compile(r'^#{%d} ' % a.level)

    idx = [i for i, l in enumerate(lines) if pat.match(l)]
    if not idx:
        sys.exit('没找到 %d 级标题：%s' % (a.level, a.src))

    # --front-until：把「首个匹配该正则的 `#` 标题」之前的全部内容并成一个 front。
    # 为什么需要：转换产物把封面/书名页/版权页/免责声明各写成独立 `#` 块（《某商业书》
    # 系列每本 2–4 个），不合并会切出一堆 `01_acquisition-com.md` 这类碎文件。
    # 典型用法：`--front-until "^# Table of Contents"`。没匹配到则退回「第一个标题之前」。
    start = idx[0]
    if a.front_until:
        pf = re.compile(a.front_until)
        for i in idx:
            if pf.search(lines[i]):
                start = i
                break

    chunks = []
    front = '\n'.join(lines[:start]).strip()
    if front and not a.drop_front:
        chunks.append(('# front', front))
    for n, i in enumerate(idx):
        if i < start:
            continue
        end = idx[n + 1] if n + 1 < len(idx) else len(lines)
        chunks.append((lines[i], '\n'.join(lines[i:end]).strip()))

    seen, out = {}, []
    for title, body in chunks:
        s = slug(title)
        if s in seen:
            seen[s] += 1
            s = '%s-%d' % (s, seen[s])
        else:
            seen[s] = 1
        out.append((s, body))

    for k, (s, body) in enumerate(out, 1):
        name = '%0*d_%s.md' % (a.prefix_len, k, s)
        nb = sum(1 for l in body.split('\n') if l.strip() and not l.startswith('#'))
        print('  %-48s 正文块 %4d' % (name, nb))
        if not a.dry:
            os.makedirs(a.out, exist_ok=True)
            io.open(os.path.join(a.out, name), 'w', encoding='utf-8').write(body + '\n')
    print('\n共 %d 个文件%s' % (len(out), '（dry-run，未落盘）' if a.dry else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
