#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_epub_text.py —— 通用 EPUB → `source_en/*.txt` + `figs/` + `chapter-figs.json`

为什么要有它（2026-10-07 补）：
    技能里此前**没有通用 EPUB 提取器**——只有 Delphi 版专用的 `extract_delphi_epub.py`。
    于是每本 EPUB 书都现写一次提取，写法各异，正是「遇到一个补一次」的典型。
    A1 第 9 步又要求**提取后必跑覆盖率卡口**，所以这个提取器必须按 spine 顺序走，
    把「不在 TOC 里的续页」正确归到前一个 TOC 章，否则续页会被整段丢掉。

关键设计（对齐 A1 各条）：
    · **按 spine 顺序分组**：TOC 条目开新章，其后未出现在 TOC 的 spine 文档**归入该章**（续页）
    · **扫全部 `<img>`**（不限定父元素）——历史事故：82 张图因只查 `<p>` 里的 img 而静默全丢
    · **图片保持原文件名**，落到 `figs/`，并生成书级 `chapter-figs.json`（章 → 有序图片名）
    · 段内斜体 `<span class=…>` → `*…*`、粗体 → `**…**`（译者按「斜体→加粗」处理）
    · 每段一个空行分隔（EPUB 的 `<p>` 就是段落边界）→ 源文天然是成色 Ⅰ 档

用法：
    python extract_epub_text.py --epub <书.epub> --out-dir <书目录>            # 预演，只报统计
    python extract_epub_text.py --epub <书.epub> --out-dir <书目录> --apply    # 落盘
选项：--ignore <前置页 href 列表，逗号分隔>、--max-title 60
退出码：0 成功；2 目录/OPF 解析失败。
"""
import argparse
import html
import io
import json
import os
import re
import sys
import zipfile

IMG = re.compile(r'<img[^>]*src="([^"]+)"[^>]*>')
P_BLOCK = re.compile(r'<(p|div|h[1-6]|li)\b[^>]*>(.*?)</\1>', re.S | re.I)
TAG = re.compile(r'<[^>]+>')
ITAL = re.compile(r'<span[^>]*class="[^"]*s2ta[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
BOLD = re.compile(r'<(b|strong)\b[^>]*>(.*?)</\1>', re.S | re.I)
DROP = re.compile(r'<(script|style|head)\b.*?</\1>', re.S | re.I)


def slug(s, maxlen=48):
    s = s.replace("’", "").replace("'", "")
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    return s[:maxlen].strip('_')


def text_of(block):
    """把一个块转成文本：保留斜体/粗体标记，剥掉其余标签，解实体。"""
    s = block
    s = ITAL.sub(lambda m: '*' + m.group(1) + '*', s)
    s = BOLD.sub(lambda m: '**' + m.group(2) + '**', s)
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)
    s = TAG.sub('', s)
    s = html.unescape(s)
    s = s.replace(' ', ' ').replace('　', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def blocks_of(xhtml):
    """按文档顺序产出 ('p', 文本) 或 ('img', 文件名)。"""
    body = DROP.sub('', xhtml)
    out = []
    pos = 0
    for m in re.finditer(r'<(p|div|h[1-6]|li)\b[^>]*>(.*?)</\1>', body, re.S | re.I):
        for im in IMG.finditer(body[pos:m.start()]):
            out.append(('img', os.path.basename(im.group(1))))
        inner = m.group(2)
        for im in IMG.finditer(inner):
            out.append(('img', os.path.basename(im.group(1))))
        t = text_of(IMG.sub('', inner))
        if t:
            out.append(('p', t))
        pos = m.end()
    for im in IMG.finditer(body[pos:]):
        out.append(('img', os.path.basename(im.group(1))))
    # 图片去重（同一 img 可能被内外层各扫到一次）
    seen, res = set(), []
    for kind, val in out:
        key = (kind, val)
        if kind == 'img':
            if key in seen:
                continue
            seen.add(key)
        res.append((kind, val))
    return res


def main():
    ap = argparse.ArgumentParser(
        description='通用 EPUB 提取器：按 spine 分组 → source_en/*.txt + figs/ + chapter-figs.json。',
        epilog='示例：python extract_epub_text.py --epub 书.epub --out-dir 书目录 --apply')
    ap.add_argument('--epub', required=True, help='源 EPUB 路径')
    ap.add_argument('--out-dir', required=True, help='书目录；写 <书目录>/source_en 与 figs')
    ap.add_argument('--ignore', default='', help='要跳过的 href，逗号分隔（封面等纯图片页）')
    ap.add_argument('--keep-front', action='store_true', help='保留前置页为首个章节文件')
    ap.add_argument('--apply', action='store_true', help='真正落盘；默认只预演并打印分组')
    a = ap.parse_args()

    z = zipfile.ZipFile(a.epub)
    names = z.namelist()
    opf_name = next((n for n in names if n.endswith('.opf')), None)
    if not opf_name:
        sys.exit('OPF 未找到')
    base = os.path.dirname(opf_name)
    # **OPF 也必须用 XML 解析**：正则对「属性顺序不同 / 中间夹别的属性」会静默漏项，
    # 漏掉的 spine 文档不会报错，只会**悄悄不进 source**（实测漏 6 个文档，
    # 靠 `check_epub_coverage.py` 才查出来）。
    import xml.etree.ElementTree as ET
    oroot = ET.fromstring(z.read(opf_name).decode('utf-8', 'replace'))
    onsp = oroot.tag.split('}')[0] + '}' if oroot.tag.startswith('{') else ''
    id2href = {it.get('id'): it.get('href') for it in oroot.iter(onsp + 'item')
               if it.get('id') and it.get('href')}
    spine = [id2href[m.get('idref')] for m in oroot.iter(onsp + 'itemref')
             if m.get('idref') in id2href]
    ncx_name = next((n for n in names if n.endswith('.ncx')), None)
    toc = []
    if ncx_name:
        # **必须用 XML 解析、不能用正则切 `<navPoint>`**：NCX 里 navPoint 是**嵌套**的
        # （Section 下挂子项），正则的非贪婪匹配会停在内层的 `</navPoint>` 上，
        # 把每个 Section 的**首个子项**整条吞掉（实测 31 条只剩 25 条）。
        import xml.etree.ElementTree as ET
        root = ET.fromstring(z.read(ncx_name).decode('utf-8', 'replace'))
        nsp = ''
        if root.tag.startswith('{'):
            nsp = root.tag.split('}')[0] + '}'

        def walk(el):
            for np in el.findall(nsp + 'navPoint'):
                lab = np.find(nsp + 'navLabel')
                txt = lab.find(nsp + 'text').text.strip() if lab is not None and lab.find(nsp + 'text') is not None else ''
                cont = np.find(nsp + 'content')
                src = cont.get('src') if cont is not None else None
                if txt and src:
                    toc.append((txt, src))
                walk(np)

        navmap = root.find(nsp + 'navMap')
        walk(navmap if navmap is not None else root)
    if not spine or not toc:
        sys.exit('spine/TOC 解析失败：spine %d，toc %d' % (len(spine), len(toc)))

    def full(h):
        return os.path.normpath(os.path.join(base, h)).replace('\\', '/')

    href2title = {full(h): t for t, h in toc}
    ignore = {x.strip() for x in a.ignore.split(',') if x.strip()}

    groups, cur = [], None
    for h in spine:
        fh = full(h)
        if fh in href2title:
            cur = (href2title[fh], [fh])
            groups.append(cur)
        elif cur is not None:
            cur[1].append(fh)
        else:
            groups.insert(0, ('（前置页）', [fh])) if not groups or groups[0][0] != '（前置页）' else groups[0][1].append(fh)
            cur = groups[0]

    print('EPUB：%s' % os.path.basename(a.epub))
    print('  spine %d 条 → 分组 %d 个（TOC %d）' % (len(spine), len(groups), len(toc)))
    if not a.apply:
        for i, (t, hs) in enumerate(groups, 1):
            print('   %02d %-46s %d 个文档' % (i, t[:46], len(hs)))
        print('\n（预演。加 --apply 落盘。）')
        return 0

    src = os.path.join(a.out_dir, 'source_en')
    figdir = os.path.join(a.out_dir, 'figs')
    os.makedirs(src, exist_ok=True)
    os.makedirs(figdir, exist_ok=True)
    figmap, written, imgs = {}, 0, 0
    for i, (title, hs) in enumerate(groups):
        # 前置页（免责声明/指导原则/献词/目录/评价）是**真内容**，保留为 `00_front`；
        # 封面这类纯图片页用 `--ignore` 排除。**不要整块丢掉**——实测一本书的
        # 「免责声明 + 指导原则 + 献词 + 目录 + 评价」5 个文档（含 1000+ 词）被整块丢过。
        n = len(figmap) + 1
        stem = '00_front' if title == '（前置页）' else '%02d_%s' % (n - (1 if any(k == '00_front' for k in figmap) else 0) + (0 if title != '（前置页）' else 0), slug(title) or 'section')
        if title == '（前置页）':
            stem = '00_front'
        else:
            stem = '%02d_%s' % (sum(1 for k in figmap if k != '00_front') + 1, slug(title) or 'section')
        lines = ['# %s' % title]
        chap_imgs = []
        for h in hs:
            if h in ignore or h not in names:
                continue
            try:
                x = z.read(h).decode('utf-8', 'replace')
            except KeyError:
                continue
            for kind, val in blocks_of(x):
                if kind == 'p':
                    # 正文首段若与 TOC 标题相同，是页眉重复（EPUB 常见）——丢掉，别写成第二个 `#`
                    if val.strip().lower() == title.strip().lower() and len(lines) <= 1:
                        continue
                    lines.append(val)
                else:
                    chap_imgs.append(val)
                    lines.append('[原文插图]')
        io.open(os.path.join(src, stem + '.txt'), 'w', encoding='utf-8').write('\n\n'.join(lines) + '\n')
        written += 1
        for f in dict.fromkeys(chap_imgs):
            for n2 in names:
                if os.path.basename(n2) == f:
                    io.open(os.path.join(figdir, f), 'wb').write(z.read(n2))
                    imgs += 1
                    break
        figmap[stem] = list(dict.fromkeys(chap_imgs))
        print('   %-40s %d 段  %d 图' % (stem, len([l for l in lines if l and l != '[原文插图]']) - 1, len(figmap[stem])))
    json.dump(figmap, io.open(os.path.join(a.out_dir, 'chapter-figs.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n已写：source_en/ %d 个文件；figs/ %d 张；chapter-figs.json' % (written, imgs))
    print('下一步：跑覆盖率卡口 check_epub_coverage.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
