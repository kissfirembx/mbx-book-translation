#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild_source_from_ocr.py —— 从行级 OCR JSON 重建 source_en（扫描书模式 B 用）

为什么需要：OCR 产物（行 + bbox）经「丢空格」的转换管道写进 source_en 后，会出现大量粘连
（实测某书 1,513 处小写接大写、空格密度 0.13，如 `HowtoWin`、`VolumeNegatesLuck`），
而 OCR 原始数据本身是好的（同一语料重建后仅 60 处、密度 0.92）。
译者面对粘连文本会误判词边界，直接损害译文质量，因此翻译前应先重建源文。

做法：
1. 从既有 source_en 读 `[PDF 第 N 页]` 标记，得到「页 → 章节」归属（保持原切分不变）
2. 逐页读 OCR JSON（需含 `page` 与 `lines[].text`/`lines[].box`），按 bbox 纵向位置排序
3. 合并为段落：行间距 > 1.6×中位行高，或前行以句末标点结尾且下一行以大写开头且间距偏大 → 断段
4. 写出，并打印重建前后的空格密度与粘连计数（质量对比）

用法：
    python rebuild_source_from_ocr.py --ocr-dir <书>/ocr --source-dir <书>/source_en [--ignore a,b] [--apply]
默认 dry-run（只打印质量对比，不落盘）；确认后再加 --apply（会先备份 source_en）。
"""
import argparse, json, os, re, shutil, sys


def load_lines(path):
    d = json.load(open(path, encoding='utf-8'))
    rows = []
    for l in d.get('lines', []):
        txt = re.sub(r'\s+', ' ', l.get('text', '')).strip()
        if not txt:
            continue
        box = l.get('box') or [[0, 0], [0, 0], [0, 0], [0, 0]]
        y = (box[0][1] + box[2][1]) / 2
        x = box[0][0]
        rows.append((y, x, txt))
    rows.sort(key=lambda r: (round(r[0] / 8), r[1]))
    return d.get('page'), rows


def paragraphs(rows):
    if not rows:
        return []
    ys = [r[0] for r in rows]
    gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1) if ys[i + 1] > ys[i]]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 40
    paras, cur, prev_y = [], [], None
    for y, x, txt in rows:
        if cur:
            gap = y - prev_y
            ends = bool(re.search(r'[.!?:;"”)]$', cur[-1]))
            caps = bool(re.match(r'^[A-Z"“(\d]', txt))
            if gap > med * 1.6 or (ends and caps and gap > med * 1.2):
                paras.append(' '.join(cur)); cur = []
        cur.append(txt); prev_y = y
    if cur:
        paras.append(' '.join(cur))
    return paras


def metric(texts):
    txt = ' '.join(texts)
    letters = len(re.findall(r'[A-Za-z]', txt))
    words = len(txt.split())
    camel = len(re.findall(r'[a-z][A-Z]', txt))
    return letters, words, (words / letters * 4 if letters else 0), camel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ocr-dir', required=True)
    ap.add_argument('--source-dir', required=True)
    ap.add_argument('--ignore', default='', help='不参与重建的章节名（逗号分隔，如与拆分版重复的合并文件）')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    ignore = {s.strip() for s in args.ignore.split(',') if s.strip()}

    page2ch = {}
    for fn in sorted(os.listdir(args.source_dir)):
        if not fn.endswith('.txt') or fn[:-4] in ignore:
            continue
        t = open(os.path.join(args.source_dir, fn), encoding='utf-8').read()
        for m in re.finditer(r'\[PDF 第 (\d+) 页\]', t):
            page2ch[int(m.group(1))] = fn[:-4]
    if not page2ch:
        sys.exit('source 目录里没有 [PDF 第 N 页] 标记，无法建立页码→章节映射')

    ocr_files = {}
    for fn in sorted(os.listdir(args.ocr_dir)):
        if fn.endswith('.json'):
            pno, rows = load_lines(os.path.join(args.ocr_dir, fn))
            if pno is not None:
                ocr_files[int(pno)] = rows

    ch_pages = {}
    for pno in sorted(page2ch):
        ch_pages.setdefault(page2ch[pno], []).append((pno, paragraphs(ocr_files.get(pno, []))))

    old_texts, new_texts = [], []
    for ch, pgs in sorted(ch_pages.items()):
        ol = open(os.path.join(args.source_dir, ch + '.txt'), encoding='utf-8').read()
        old_texts.append(re.sub(r'\[PDF 第 \d+ 页\]', '', ol))
        for _, paras in pgs:
            new_texts.extend(paras)

    for tag, texts in (('重建前', old_texts), ('重建后', new_texts)):
        letters, words, dens, camel = metric(texts)
        print('%s：字母 %-7d 词 %-7d 空格密度 %.2f  小写接大写粘连 %d 处' % (tag, letters, words, dens, camel))

    print('\n章节 %d，OCR 页 %d，映射页 %d' % (len(ch_pages), len(ocr_files), len(page2ch)))
    if not args.apply:
        print('（dry-run，未落盘；确认后加 --apply）')
        return
    bak = os.path.join(args.source_dir + '_旧_未重建版')
    if not os.path.exists(bak):
        shutil.copytree(args.source_dir, bak)
        print('旧源文已备份到 %s' % bak)
    for ch, pgs in sorted(ch_pages.items()):
        parts = ['[PDF 第 %d 页]\n\n%s' % (p, '\n\n'.join(paras) if paras else '') for p, paras in pgs]
        open(os.path.join(args.source_dir, ch + '.txt'), 'w', encoding='utf-8', newline='').write(
            '\n\n'.join(parts).strip() + '\n')
    print('已重建 %d 章' % len(ch_pages))


if __name__ == '__main__':
    main()
