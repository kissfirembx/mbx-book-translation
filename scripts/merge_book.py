#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_book.py —— 通用书籍合并与插图附录（替代一次性临时脚本）

用法：
    python merge_book.py --config <book_dir>/merge-config.json

配置文件（merge-config.json，放在书目录下）示例：
{
  "title": "<书名> 中文全译",
  "subtitle": "<副标题（可省）>",
  "source_info": "英文书名：<原名>\n> 作者：<作者>（<年份>）",
  "suffix": "",
  "out_name": "<书名> 中文全译.md",
  "parts": ["00_front", "02_s1_intro"],
  "fig_ranges": {"01_start": [8, 13], "03_ch2": [14, 30]},
  "fig_cover": {"00_front": ["p1_1.jpeg"]}
}

规则：
- `parts` 列出的章节保持 # 级（部分引言/前置）；其余章节整体 +1 级（章 → ##）
- `fig_ranges` 指定各章的 PDF 页码范围，脚本从 figs/ 里按 `p<页码>_*` 取图，追加到章末
- `fig_cover` 为指定章追加固定图片（如封面）
- 幂等：已存在 `## 原书插图` 的章节不重复追加
- 图片路径：章节文件在 `zh/` 下用 `../figs/`，合并时统一改写为 `./figs/`（成品位于书根，与 figs/ 同级）
- `--dry-run` 只打印计划不落盘
"""
import argparse, json, os, re, glob, sys


def remap(text, keep_level):
    """keep_level=True 时保持标题级别；否则整体 +1（最多到 ######）"""
    if keep_level:
        return text
    out = []
    for l in text.split('\n'):
        m = re.match(r'^(#{1,6})(\s+.+)$', l)
        if m:
            l = '#' * min(len(m.group(1)) + 1, 6) + m.group(2)
        out.append(l)
    return '\n'.join(out)


def collect_figs(figs_dir):
    """返回 {页码: [文件名, ...]}"""
    by_page = {}
    for f in glob.glob(os.path.join(figs_dir, '*')):
        m = re.match(r'p(\d+)_', os.path.basename(f))
        if m:
            by_page.setdefault(int(m.group(1)), []).append(os.path.basename(f))
    for k in by_page:
        by_page[k].sort()
    return by_page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True, help='merge-config.json 路径')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding='utf-8'))
    book_dir = os.path.dirname(os.path.abspath(args.config))
    zh_dir = os.path.join(book_dir, 'zh')
    figs_dir = os.path.join(book_dir, 'figs')
    suffix = cfg.get('suffix', '')
    parts_keep = set(cfg.get('parts', []))
    by_page = collect_figs(figs_dir) if os.path.isdir(figs_dir) else {}

    files = sorted(glob.glob(os.path.join(zh_dir, '*' + suffix + '.md')))
    if not files:
        sys.exit('未找到章节文件：%s/*%s.md' % (zh_dir, suffix))

    def fig_lines(pages):
        out = []
        for p in pages:
            for fn in by_page.get(p, []):
                out.append('![原书插图（PDF 第 %d 页）](./figs/%s)' % (p, fn))
        return out

    # 1) 先给各章追加插图附录（幂等：已有 `## 原书插图` 的跳过）
    for name, rng in cfg.get('fig_ranges', {}).items():
        path = os.path.join(zh_dir, name + suffix + '.md')
        if not os.path.exists(path):
            continue
        t = open(path, encoding='utf-8').read()
        if '## 原书插图' in t:
            continue
        lines = fig_lines(range(rng[0], rng[1] + 1))
        if not lines:
            continue
        block = '\n\n---\n\n## 原书插图（PDF 第 %d–%d 页）\n\n' % (rng[0], rng[1]) + '\n\n'.join(lines)
        t = t.replace('<!-- 本章翻译完成 -->', '').rstrip() + block + '\n\n<!-- 本章翻译完成 -->\n'
        if not args.dry_run:
            open(path, 'w', encoding='utf-8', newline='').write(t)
        print('  插图 %s: +%d 张' % (name, len(lines)))

    # 封面等固定图片
    for name, imgs in cfg.get('fig_cover', {}).items():
        path = os.path.join(zh_dir, name + suffix + '.md')
        if not os.path.exists(path):
            continue
        t = open(path, encoding='utf-8').read()
        if imgs[0] in t:
            continue
        block = '\n\n' + '\n'.join('![原书封面（PDF 第 1 页）](./figs/%s)' % i for i in imgs)
        t = t.replace('<!-- 本章翻译完成 -->', '').rstrip() + block + '\n\n<!-- 本章翻译完成 -->\n'
        if not args.dry_run:
            open(path, 'w', encoding='utf-8', newline='').write(t)
        print('  封面 %s: +%d 张' % (name, len(imgs)))

    body, stats = [], []
    for f in files:
        name = os.path.basename(f)[:-len(suffix) - 3]
        t = open(f, encoding='utf-8').read().replace('<!-- 本章翻译完成 -->', '')
        # 章节文件在 zh/ 子目录，用 ../figs/；成品在书根，改为 ./figs/
        t = t.replace('](../figs/', '](./figs/')
        t = remap(t, name in parts_keep).rstrip()
        body.append(t)
        stats.append(name)

    full = '\n\n'.join(body)
    header = '# %s\n\n%s\n\n> %s\n> 本文件为合并成品；原成品保留未动\n\n---\n\n' % (
        cfg['title'], cfg.get('subtitle', ''), cfg.get('source_info', ''))
    out_path = os.path.join(book_dir, cfg.get('out_name') or (cfg['title'] + '.md'))
    final = header + full + '\n'

    print('章节数: %d（%s）' % (len(stats), ', '.join(stats[:3]) + ' …'))
    print('成品: %s' % out_path)
    print('字符数: %d' % len(final))
    if args.dry_run:
        print('（dry-run，未落盘）')
        return
    open(out_path, 'w', encoding='utf-8', newline='').write(final)


if __name__ == '__main__':
    main()
