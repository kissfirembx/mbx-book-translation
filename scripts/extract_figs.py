#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_figs.py —— PDF 按页导出实质图片 + 给各章追加「原书插图」附录（通用，无书专属常量）

为什么需要：文字层 PDF 里的插图不会自动进入译文。本脚本按页导出图片（命名 `p<页码>_<序号>.<ext>`），
再按各章的页码范围把图追加到章末附录，路径统一 `./figs/<文件名>`（合并成品时由 merge_book.py 统一）。

用法：
    # 页码范围写进 JSON：{"01_intro": [3, 12], "02_ch1": [13, 20]}
    python extract_figs.py --pdf <书.pdf> --book-dir <书目录> --ranges <范围.json>
    # 或直接在命令行给（可重复）
    python extract_figs.py --pdf <书.pdf> --book-dir <书目录> --range 01_intro:3:12 --range 02_ch1:13:20

参数：
    --pdf          源 PDF
    --book-dir     书目录：图片写 <book-dir>/figs/，附录写 <book-dir>/zh/<章节><后缀>.md
    --ranges       页码范围 JSON（对象或 [[章, 起, 止], ...] 数组）
    --range        单章范围，格式 `章节名:起页:止页`，可重复
    --skip-pages   已作整页图内嵌的页（逗号分隔），不重复追加
    --suffix       章节译文文件名后缀（默认空，如 `_重译版`）
    --min-px       图片最小边长，默认 100（滤装饰性小图）
    --no-appendix  只导出图片，不写章节附录
    --dry-run      只打印计划，不落盘
"""
import argparse, glob, json, os, re, sys


def load_ranges(args):
    ranges = []
    if args.ranges:
        d = json.load(open(args.ranges, encoding="utf-8"))
        if isinstance(d, dict):
            ranges += [(k, int(v[0]), int(v[1])) for k, v in d.items()]
        else:
            ranges += [(str(a), int(b), int(c)) for a, b, c in d]
    for spec in args.range or []:
        name, a, b = spec.rsplit(":", 2)
        ranges.append((name, int(a), int(b)))
    if not ranges and not args.no_appendix:
        sys.exit("需要 --ranges 或 --range（除非 --no-appendix 只导图）")
    return ranges


def export_pdf_images(doc, fig_dir, min_px, dry_run):
    """按页导出实质图片，返回 {页码: [(文件名, 宽, 高)]}"""
    import fitz  # noqa: F401  （调用方已确保依赖存在）
    page_imgs = {}
    for i in range(doc.page_count):
        page = doc[i]
        found = []
        infos = page.get_image_info()
        for info, img in zip(infos, page.get_images(full=True)):
            data = doc.extract_image(img[0])
            w, h = data["width"], data["height"]
            if w < min_px or h < min_px:
                continue                              # 装饰性小图
            fname = "p%d_%d.%s" % (i + 1, len(found) + 1, data["ext"])
            if not dry_run:
                os.makedirs(fig_dir, exist_ok=True)
                with open(os.path.join(fig_dir, fname), "wb") as f:
                    f.write(data["image"])
            found.append((fname, w, h))
        if found:
            page_imgs[i + 1] = found
    return page_imgs


def append_appendix(book_dir, name, suffix, start, end, page_imgs, skip, dry_run):
    dst = os.path.join(book_dir, "zh", name + suffix + ".md")
    if not os.path.exists(dst):
        print("  跳过缺失章节: %s" % name)
        return 0
    content = open(dst, encoding="utf-8").read()
    lines = ["![原书插图（PDF 第 %d 页，%dx%d）](./figs/%s)" % (p, w, h, img)
             for p in range(start, end + 1) if p not in skip and p in page_imgs
             for (img, w, h) in page_imgs[p]]
    if not lines:
        return 0
    appendix = "\n\n---\n\n## 原书插图（PDF 第 %d–%d 页）\n\n" % (start, end) + "\n\n".join(lines)
    if "## 原书插图" in content:                      # 幂等：替换旧附录
        content = re.sub(r"\n\n---\n\n## 原书插图.*$", "", content, flags=re.S)
    content = content.rstrip() + appendix + "\n\n<!-- 本章翻译完成 -->"
    if not dry_run:
        open(dst, "w", encoding="utf-8").write(content)
    print("  %s: %s插图 %d 张" % (name, "计划" if dry_run else "补充", len(lines)))
    return len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--book-dir", required=True)
    ap.add_argument("--ranges")
    ap.add_argument("--range", action="append")
    ap.add_argument("--skip-pages", default="")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--min-px", type=int, default=100)
    ap.add_argument("--no-appendix", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        import fitz
    except ImportError:
        sys.exit("需要 PyMuPDF：pip install pymupdf")

    skip = {int(x) for x in re.split(r"[,\s]+", args.skip_pages) if x.strip().isdigit()}
    doc = fitz.open(args.pdf)
    fig_dir = os.path.join(args.book_dir, "figs")
    page_imgs = export_pdf_images(doc, fig_dir, args.min_px, args.dry_run)
    print("导出图片：%d 页有实质图片，共 %d 张%s"
          % (len(page_imgs), sum(len(v) for v in page_imgs.values()),
             "（dry-run 未落盘）" if args.dry_run else ""))
    total = 0
    if not args.no_appendix:
        for name, start, end in load_ranges(args):
            total += append_appendix(args.book_dir, name, args.suffix, start, end,
                                     page_imgs, skip, args.dry_run)
    doc.close()
    print("附录插图合计 %d 张" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
