#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pdf_text.py —— 通用 PDF → `source_en/*.txt` + `figs/`

为什么需要（2026-10-07）：EPUB 侧早有通用提取器 `extract_epub_text.py`，**PDF 侧没有**——
每本 PDF 书都现写一次切分脚本（正是「每本书现写一次」这个反模式）。本脚本把
「按 PDF 书签（outline）切章 + 按块顺序内嵌插图」这条路固化下来。

切分依据：**PDF 书签 `doc.get_toc()`**（页边界由出版方给出，最准）。
没有书签的 PDF，本脚本**不猜**——直接报错退出。

插图（2026-10-07 补，实测踩过）：
  图必须**按位置**插进正文，不能只在 `figs/` 里躺着——否则译者无从嵌入，整本书的插图会静默丢失。
  做法：把该页的**文本块**与**图片块**按 `(y, x)` 排序合并输出，图片位置写一行
  `[插图 figs/pXXX_Y.ext]`。命名与 `extract_figs.py` 一致（`p<页码>_<序号>`）。

零改写：只**删行**（页码、重复页眉），不改任何行内字符。两类删除都带条件：
  ① **页码**——仅当纯数字行落在本页**头两行或末两行**、且数值≈PDF 页码（±1）才删。
     ⚠️ 不能见纯数字就删：《某商业书》实测 37 个纯数字行里只有 1 个真是页码，
     其余 36 个是**表格单元格**（`1023`／`2047`／`4095`…），见数字就删会整批丢表内容。
  ② **重复页眉**——与书签标题同名的行，**保留第一次出现**（章标题就在首页首行，
     删掉它等于删掉章标题），其后重复出现的一律删。去重**按文件**做——不然目录页
     会把所有章名提前登记，导致每章标题被误删（实测踩过）。

用法：
    python extract_pdf_text.py --pdf <书.pdf> --book-dir <书目录> --front-end 7 --from-page 8
    # --front-end  N  1..N 页并入 `00_front.txt`（默认 0 = 不设前置）
    # --from-page  P  只取「起始页 >= P」的书签（默认 1）
    # --no-figs       不导图片、不插图标记
选项：--ranges-out <path> 写各章页码范围 JSON；--dry-run 只打印切分表。
退出码：0 成功；非 0 失败（无书签、目录为空等）。
"""
import argparse
import io
import glob
import json
import os
import re
import sys


def slug(s):
    s = re.sub(r'[^\w\s-]', '', s, flags=re.U).strip()
    s = re.sub(r'[\s-]+', '_', s)
    return s[:48] or 'untitled'


def main():
    ap = argparse.ArgumentParser(
        description='通用 PDF 提取器：按书签切章 → source_en/*.txt，按位置内嵌插图标记。',
        epilog='示例：python extract_pdf_text.py --pdf 书.pdf --book-dir 书目录 '
               '--front-end 7 --from-page 8')
    ap.add_argument('--pdf', required=True, help='源 PDF 路径（必须有书签/outline）')
    ap.add_argument('--book-dir', required=True, help='书目录；写 <书目录>/source_en 与 figs')
    ap.add_argument('--front-end', type=int, default=0, help='1..N 页并入 00_front（默认 0）')
    ap.add_argument('--from-page', type=int, default=1, help='只取起始页 >= P 的书签（默认 1）')
    ap.add_argument('--no-figs', action='store_true', help='不导图片、不插图标记')
    ap.add_argument('--min-px', type=int, default=100, help='小于该边长(px)的图视为装饰，跳过')
    ap.add_argument('--ranges-out', default=None, help='写各章页码范围 JSON（供 extract_figs.py）')
    ap.add_argument('--dry-run', action='store_true', help='只打印切分表，不落盘')
    a = ap.parse_args()

    try:
        import fitz
    except ImportError:
        sys.exit('需要 PyMuPDF：pip install pymupdf')

    doc = fitz.open(a.pdf)
    n_pages = doc.page_count
    all_toc = [(lvl, t.strip(), p) for lvl, t, p in doc.get_toc() if t.strip()]
    if not all_toc:
        sys.exit('这份 PDF 没有书签（outline）——本脚本不猜页边界，请先另定切分依据。')
    toc = [(lvl, t, p) for lvl, t, p in all_toc if p >= a.from_page]
    if not toc:
        sys.exit('--from-page %d 之后没有书签条目' % a.from_page)

    # 只把书签标题当「重复页眉」判据；不掺任何单本书的书名/章名。
    titles = {t for _l, t, _p in all_toc}
    figs_dir = os.path.join(a.book_dir, 'figs')
    src_dir = os.path.join(a.book_dir, 'source_en')

    # ---------- 每页：文本块与图片块按 (y, x) 排序合并 ----------
    def page_items(pno):
        page = doc[pno - 1]
        rows = []
        for b in page.get_text('blocks'):
            x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
            if b[6] == 0 and txt.strip():
                rows.append([y0, x0, 't', txt])
        if not a.no_figs:
            for k, info in enumerate(page.get_image_info(xrefs=True), 1):
                x0, y0, x1, y1 = info['bbox']
                if min(x1 - x0, y1 - y0) < a.min_px:
                    continue
                rows.append([y0, x0, 'i', info['xref']])
        rows.sort(key=lambda r: (round(r[0], 1), round(r[1], 1)))
        # **无文字的整页图页 = 封面类**，其图不进正文（否则封面图会被当插图嵌进译文）
        if not any(r[2] == 't' for r in rows):
            return []
        return rows

    cleaned_pages = set()

    def save_fig(xref, pno):
        out = doc.extract_image(xref)
        ext = out.get('ext', 'png')
        os.makedirs(figs_dir, exist_ok=True)
        # **幂等**：本页第一次写图时，先清掉本页已有的 p<页码>_* 文件，否则重跑会
        # 生成 pXXX_2 / pXXX_3 变体、把上一轮的引用全变成孤儿（实测踩过：58 张里只用 29 张）
        if pno not in cleaned_pages:
            cleaned_pages.add(pno)
            for old in glob.glob(os.path.join(figs_dir, 'p%03d_*' % pno)):
                os.remove(old)
        k = 1
        while os.path.exists(os.path.join(figs_dir, 'p%03d_%d.%s' % (pno, k, ext))):
            k += 1
        name = 'p%03d_%d.%s' % (pno, k, ext)
        io.open(os.path.join(figs_dir, name), 'wb').write(out['image'])
        return 'figs/' + name

    # ---------- 每章：拼页 → 清理（只删行） ----------
    def build(name, s, e, ranges):
        seen_titles = set()
        out = []
        for p in range(s, e + 1):
            items = page_items(p)
            text_lines, marks = [], []          # marks: 插入位置索引 → 标记行
            for y, x, kind, payload in items:
                if kind == 'i':
                    marks.append((len(text_lines), '[插图 %s]' % save_fig(payload, p)))
                else:
                    text_lines.extend(payload.split('\n'))
            ne = [i for i, l in enumerate(text_lines) if l.strip()]
            edge = set(ne[:2]) | set(ne[-2:])
            seq = []
            for i, l in enumerate(text_lines):
                st = l.strip()
                if st and re.fullmatch(r'\d{1,4}', st) and i in edge and abs(int(st) - p) <= 1:
                    continue
                if st in titles:
                    if st in seen_titles:
                        continue
                    seen_titles.add(st)
                seq.append(l)
            # 把图标记插回去，**前后各留一个空行**（让它独占一段，别粘住相邻正文）
            for idx, mark in marks:
                pos = min(idx, len(seq))
                seq[pos:pos] = ['', mark, '']
            body = '\n'.join(seq).strip('\n')
            out.append('[PDF 第 %d 页]' % p)
            if body:
                out.append(body)
        text = re.sub(r'\n{3,}', '\n\n', '\n\n'.join(out)).strip() + '\n'
        io.open(os.path.join(src_dir, name + '.txt'), 'w', encoding='utf-8').write(text)
        ranges[name] = [s, e]
        print('  写入 %-46s p%-4d–%-4d ｜ %6d 字符' % (name + '.txt', s, e, len(text)))

    chapters = []
    for i, (lvl, title, page) in enumerate(toc):
        end = toc[i + 1][2] - 1 if i + 1 < len(toc) else n_pages
        chapters.append((lvl, title, page, max(end, page)))

    print('PDF 共 %d 页 ｜ 书签 %d 条 ｜ 切出 %d 章%s'
          % (n_pages, len(toc), len(chapters), '（+ 前置）' if a.front_end else ''))
    for lvl, title, st, en in chapters:
        print('   %s%-52s p%-4d–%-4d' % ('  ' * (lvl - 1), title[:52], st, en))
    if a.dry_run:
        print('\n（dry-run，未落盘）')
        return 0

    os.makedirs(src_dir, exist_ok=True)
    ranges = {}
    if a.front_end:
        build('00_front', 1, a.front_end, ranges)
    for i, (lvl, title, st, en) in enumerate(chapters, 1):
        build('%02d_%s' % (i, slug(title)), st, en, ranges)
    if a.ranges_out:
        json.dump(ranges, open(a.ranges_out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('  页码范围 → %s' % a.ranges_out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
