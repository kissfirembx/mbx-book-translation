#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_epub_coverage.py —— EPUB 源文覆盖率核查（防止「无标题续页」被静默丢失）

背景：EPUB 常把一个章节拆成多个 spine 文档，续页往往没有自己的章标题。
按标题切分章节的提取脚本会把这类续页整段丢掉，且旧译稿、旧图片映射都会一起继承这个缺口。
本书实战案例：某章正文 1497 词条 100% 覆盖，紧随其后的续页 905 词条只有 2.4% 覆盖，
包含 6 个小节 + 要点总结 + 免费礼物 + 二维码图，全部缺失。另有 4 章同型缺失。

用法：
    python check_epub_coverage.py --epub <书.epub> --source-dir <书目录>/source_en [--fig-map <book>/chapter-figs.json]

输出：
    1) 每个 spine 文档的最佳匹配章节与覆盖率；低于阈值的标 `<== 提取丢失`
    2) 未被任何章节文件覆盖的图片清单（对照 --fig-map 与 EPUB 实际图片）
退出码：全部通过 0，存在丢失 1（便于流水线卡口）。
"""
import argparse, json, os, re, sys, zipfile
from collections import Counter

NGRAM = 6
TRANS = str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '—': '-', '–': '-',
                       '…': '.', '\u00a0': ' '})


def plain(html):
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<[^>]+>', ' ', html)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&#8217;', '’'), ('&#8216;', '‘'),
                 ('&#8220;', '“'), ('&#8221;', '”'), ('&#8212;', '—'), ('&quot;', '"'),
                 ('&#39;', "'"), ('&lt;', '<'), ('&gt;', '>')):
        html = html.replace(a, b)
    return html


def grams(text):
    t = text.translate(TRANS).lower()
    # 首字母下沉/字距排版：EPUB 解包常呈 `D ollar`、`W elcome` 形态，而 source txt 已归一化，
    # 不修掉会整章误报「提取丢失」（实测某书 5 章因此假阳性）
    t = re.sub(r'(?<![a-z0-9])([a-z]) (?=[a-z])', r'\1', t)
    t = re.sub(r"\b([a-z]) '", r"\1'", t)
    t = re.sub(r'^[a-z0-9]{1,6}\s+', '', t.strip())   # 去掉 xhtml 开头的锚点文字（如 cM1）
    words = re.findall(r"[a-z0-9$%.']+", t)
    return {' '.join(words[i:i + NGRAM]) for i in range(max(0, len(words) - NGRAM + 1))}


def spine_order(z, names):
    opf = [n for n in names if n.lower().endswith('.opf')]
    if not opf:
        return sorted(n for n in names if n.lower().endswith(('.xhtml', '.html', '.htm')))
    o = z.read(opf[0]).decode('utf-8', 'ignore')
    base = os.path.dirname(opf[0])
    idmap = dict(re.findall(r'<item\b[^>]*id="([^"]+)"[^>]*href="([^"]+)"', o))
    order = []
    for m in re.finditer(r'<itemref[^>]*idref="([^"]+)"', o):
        href = idmap.get(m.group(1))
        if href:
            order.append(os.path.normpath(os.path.join(base, href)).replace('\\', '/'))
    return order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epub', required=True)
    ap.add_argument('--source-dir', required=True, help='放章节 txt 的目录（如 source_en/）')
    ap.add_argument('--fig-map', help='chapter-figs.json，用于核对图片是否被登记')
    ap.add_argument('--threshold', type=float, default=0.85)
    ap.add_argument('--min-grams', type=int, default=5, help='文档词条少于该值视为装饰页/前置页，跳过')
    ap.add_argument('--ignore', default='', help='逗号分隔的 xhtml 文件名，视为前置页（版权/推荐语/目录）不参与缺失判定')
    args = ap.parse_args()
    ignores = {s.strip() for s in args.ignore.split(',') if s.strip()}

    with zipfile.ZipFile(args.epub) as z:
        names = z.namelist()
        docs = {n: z.read(n).decode('utf-8', 'ignore')
                for n in names if n.lower().endswith(('.xhtml', '.html', '.htm'))}
        media = sorted(os.path.basename(n) for n in names
                       if n.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')))
        order = [p for p in spine_order(z, names) if p in docs] or sorted(docs)

    src = {}
    for fn in sorted(os.listdir(args.source_dir)):
        if fn.endswith('.txt'):
            src[fn[:-4]] = grams(open(os.path.join(args.source_dir, fn), encoding='utf-8').read())
    if not src:
        sys.exit('source 目录没有 txt：%s' % args.source_dir)

    lost, rows = [], []
    for path in order:
        g = grams(plain(docs[path]))
        if len(g) < args.min_grams:
            continue
        best, best_ch = 0.0, ''
        for ch, sg in src.items():
            r = len(g & sg) / len(g)
            if r > best:
                best, best_ch = r, ch
        rows.append((os.path.basename(path), len(g), best, best_ch))
        if best < args.threshold and os.path.basename(path) not in ignores:
            lost.append((os.path.basename(path), len(g), best, best_ch))

    print('%-16s %8s %8s  %s' % ('xhtml', '词条数', '覆盖率', '最匹配章节'))
    for label, n, r, ch in rows:
        print('%-16s %8d %7.1f%%  %-44s%s' % (label, n, r * 100, ch,
                                              '' if r >= args.threshold else '  <== 提取丢失'))

    if args.fig_map and os.path.exists(args.fig_map):
        cfg = json.load(open(args.fig_map, encoding='utf-8'))
        used = {f for v in cfg.values() for f in v}
        unreg = [m for m in media if m not in used]
        if unreg:
            print('\nEPUB 里有、chapter-figs.json 未登记的图片（确认是否属装饰/前置页）：')
            for m in unreg:
                where = [os.path.basename(n) for n, h in docs.items() if m in h]
                print('   %-24s 出现在 %s' % (m, where))
        dup = {k: v for k, v in Counter(f for v in cfg.values() for f in v).items() if v > 1}
        if dup:
            print('\n跨章重复登记的图片（二维码类图属正常）：%s' % ', '.join(sorted(dup)))

    # 超链接核查：txt 提取常把 <a href> 整条丢掉（实测一本书 3 处内容链接全丢）
    all_src_text = ' '.join(
        open(os.path.join(args.source_dir, fn), encoding='utf-8').read()
        for fn in sorted(os.listdir(args.source_dir)) if fn.endswith('.txt'))
    lost_links, minor_links = [], []
    for label, html in sorted(docs.items()):
        for href, inner in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            if href.startswith('#') or '.xhtml' in href or '.html' in href:
                continue          # 目录内部跳转，无需进正文
            if href.split('&#')[0].rstrip() in all_src_text:
                continue
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', inner)).strip()
            # 锚文本极短（如话题标签 `#1`）的社交跳转，读者用不上，只提示不判失败
            (minor_links if len(text) < 8 else lost_links).append((label, href, text[:40]))
    if lost_links:
        print('\n超链接未进入 source 目录（%d 条，需补回源文与译文）：' % len(lost_links))
        for label, href, text in lost_links:
            print('   %-14s %-46s %s' % (label, href[:46], text))
    if minor_links:
        print('\n锚文本过短的链接（%d 条，仅提示）：%s'
              % (len(minor_links), ', '.join('%s:%s' % (l, h[:30]) for l, h, _ in minor_links[:6])))

    if lost or lost_links:
        if lost:
            print('\n结论：%d 个 spine 文档未进入 source 目录，需补提取后再翻译：' % len(lost))
            for label, n, r, ch in lost:
                print('   %s（%d 词条，覆盖率 %.1f%%，疑属 %s）' % (label, n, r * 100, ch or '未匹配'))
        if lost_links:
            print('结论：%d 条超链接缺失，补回后再翻译。' % len(lost_links))
        return 1
    print('\n结论：全部 spine 文档均已被 source 目录覆盖，超链接无缺失。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
