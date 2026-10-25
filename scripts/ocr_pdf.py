#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocr_pdf.py —— 扫描 PDF 逐页 OCR → 按页 JSON

通用驱动：PaddleOCR-json（Umi-OCR 自带）+ PyMuPDF 渲染；支持断点续传与页范围试跑。
主流程见 `references/mode-b-ocr.md` B1–B3。

安全约定：
- 只有 `if __name__ == "__main__"` 才进 main；`--help` 不加载引擎、不写盘。
- 必须给 `--pdf` / `--out-dir`，并加 `--apply` 才真正 OCR、写 JSON；不加只打印计划。

用法：
    python ocr_pdf.py --pdf <扫描.pdf> --out-dir <书>/ocr --apply
    python ocr_pdf.py --pdf <扫描.pdf> --out-dir <书>/ocr --pages 1-3 --apply
选项：--dpi 150（高精度用 300）、--engine-dir、--exe、--pages
"""
import argparse
import json
import os
import sys
import time

from mbx_config import ocr_engine_dir, ocr_exe

# 公共默认：空；本机通过 MBX_OCR_EXE / MBX_OCR_ENGINE_DIR 或 --exe/--engine-dir 指定。
DEFAULT_ENGINE_DIR = ocr_engine_dir()
DEFAULT_EXE = ocr_exe()


def parse_pages(spec, total):
    """把 `1-3` / `1,3,5` 解析成 0-based 页索引；空 = 全书。"""
    if not spec.strip():
        return list(range(total))
    pages = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            lo, hi = int(a), int(b)
            if lo < 1 or hi < lo:
                raise ValueError('页码范围不合法：%s' % part)
            pages.update(range(lo - 1, hi))
        else:
            n = int(part)
            if n < 1:
                raise ValueError('页码从 1 开始：%s' % part)
            pages.add(n - 1)
    return [p for p in sorted(pages) if 0 <= p < total]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='通用扫描 PDF OCR：逐页渲染 → PaddleOCR-json → 按页 JSON，支持断点续传。',
        epilog='示例：python ocr_pdf.py --pdf 书.pdf --out-dir 书/ocr --apply')
    ap.add_argument('--pdf', required=True, help='扫描版 PDF 路径（必填）')
    ap.add_argument('--out-dir', required=True, help='按页 JSON 输出目录（必填）')
    ap.add_argument('--dpi', type=int, default=150, help='渲染 dpi（默认 150；引用点密集用 300）')
    ap.add_argument('--engine-dir', default=DEFAULT_ENGINE_DIR, help='PPOCR_api.py 所在目录')
    ap.add_argument('--exe', default=DEFAULT_EXE, help='PaddleOCR-json 可执行文件')
    ap.add_argument('--pages', default='', help='页码范围，如 1-3 或 1,3,5；空=全书')
    ap.add_argument('--md-out', default='', help='可选：把所选页 OCR 文本合并成一份 MD（含 [PDF 第 N 页] 标记）')
    ap.add_argument('--apply', action='store_true',
                    help='真正执行 OCR 并写盘；不加只打印计划')
    a = ap.parse_args(argv)

    if not a.exe:
        print('未配置 OCR 引擎：设置 MBX_OCR_EXE，或传 --exe <PaddleOCR-json.exe>', file=sys.stderr)
        return 2
    if not a.engine_dir:
        a.engine_dir = os.path.dirname(os.path.abspath(a.exe))

    if not a.apply:
        print('dry-run：将用 %s' % a.exe)
        print('         以 %d dpi 识别 %s' % (a.dpi, a.pdf))
        print('         页范围：%s' % (a.pages or '全书'))
        print('         输出到 %s' % a.out_dir)
        if a.md_out:
            print('         合并 MD：%s' % a.md_out)
        print('（未创建目录、未加载 OCR 引擎；加 --apply 才执行）')
        return 0

    os.makedirs(a.out_dir, exist_ok=True)
    sys.path.insert(0, a.engine_dir)
    try:
        from PPOCR_api import PPOCR_pipe
        import fitz
    except ImportError as e:
        print('缺少依赖：%s（检查 --engine-dir/--exe 与 PyMuPDF 安装）' % e, file=sys.stderr)
        return 1

    doc = fitz.open(a.pdf)
    total = doc.page_count
    try:
        pages = parse_pages(a.pages, total)
    except ValueError as e:
        print('页码参数错误：%s' % e, file=sys.stderr)
        doc.close()
        return 2
    if not pages:
        print('页范围为空', file=sys.stderr)
        doc.close()
        return 2
    print('总页数: %d，本次识别 %d 页' % (total, len(pages)))
    ocr = PPOCR_pipe(a.exe, argument={'config_path': 'models/config_chinese.txt'})
    t_start = time.time()
    done = 0
    try:
        for p in pages:
            out_path = os.path.join(a.out_dir, 'p%04d.json' % (p + 1))
            if os.path.exists(out_path):
                done += 1
                continue
            try:
                pix = doc[p].get_pixmap(dpi=a.dpi)
                res = ocr.runBytes(pix.tobytes('png'))
                if res and res.get('code') == 100:
                    data = [{'text': d['text'], 'box': d['box'],
                             'score': round(d['score'], 3)} for d in res['data']]
                else:
                    data = []
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump({'page': p + 1, 'lines': data}, f, ensure_ascii=False)
                done += 1
            except Exception as e:
                print('第%d页失败: %s' % (p + 1, e))
                # 失败页写占位文件，避免断点续传死循环
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump({'page': p + 1, 'lines': [], 'error': str(e)},
                              f, ensure_ascii=False)
                done += 1
            if done % 50 == 0:
                el = time.time() - t_start
                speed = done / el if el else 0
                remain = (len(pages) - done) / speed if speed > 0 else 0
                print('进度 %d/%d (%.0f分, 预计剩余 %.0f分)'
                      % (done, len(pages), el / 60, remain / 60), flush=True)
    finally:
        ocr.exit()
        doc.close()
    el = time.time() - t_start
    print('OCR 完成: %d/%d 页, 用时 %.1f 分钟' % (done, len(pages), el / 60))
    if a.md_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.md_out)), exist_ok=True)
        with open(a.md_out, 'w', encoding='utf-8') as f:
            for p in pages:
                jf = os.path.join(a.out_dir, 'p%04d.json' % (p + 1))
                if not os.path.exists(jf):
                    continue
                data = json.load(open(jf, encoding='utf-8'))
                f.write('\n[PDF 第 %d 页]\n\n' % (p + 1))
                for d in data.get('lines', []):
                    t = (d.get('text') or '').strip()
                    if t:
                        f.write(t + '\n')
        print('合并 MD ->', a.md_out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
