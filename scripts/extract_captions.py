#!/usr/bin/env python3
"""extract_captions.py —— 图片注释识别（问题④）

区分：图下小字注释（题注/来源）vs 叙述式正文；并把「图中文字」剔除。
产出：captions.json（图->注解映射）+ 带图注的 markdown。

依赖：本脚本不导出图片文件。图片由 extract_figs.py 导出（命名 p<页码>_<序号>.<ext>），
      本脚本按该命名规则引用；缺文件时写 HTML 注释提示，不产生失效链接。

用法：python extract_captions.py <PDF> <FIGS_DIR> <OUT_MD>
依赖：pymupdf (fitz)
"""
import argparse, glob, json, os, re
try:
    import fitz
except ImportError:
    fitz = None

CAPTION_PAT = re.compile(r"^((图|表)\s*\d+|数据来源|来源|资料来源|注[:：]|注释)", re.I)


def classify(block_text: str) -> str:
    t = block_text.strip()
    if not t:
        return ""
    if CAPTION_PAT.match(t):
        return "caption"
    return "body"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("figs_dir")
    ap.add_argument("out_md")
    a = ap.parse_args()
    if not fitz:
        raise SystemExit("需要 pip install pymupdf")
    doc = fitz.open(a.pdf)
    os.makedirs(a.figs_dir, exist_ok=True)
    mapping = []
    md_parts = []
    for idx, page in enumerate(doc):
        page_imgs = page.get_image_info()
        blocks = page.get_text("blocks")
        imgs_below = []
        for img in page_imgs:
            rb = img["bbox"]
            # 图下方小字：几何上紧邻图片下缘的文本块
            below = []
            for b in blocks:
                x0, y0, x1, y1, text, *_ = b
                if y0 > rb[3] and y0 - rb[3] < 60 and x0 >= rb[0] - 20:
                    below.append((x0, y0, text.strip()))
            below.sort(key=lambda t: (t[1], t[0]))
            caption = ""
            for x0, y0, t in below:
                kind = classify(t)
                if kind == "caption":
                    caption = t
                    break
            mapping.append({"page": idx + 1, "img_bbox": [round(v) for v in rb], "caption": caption})
            imgs_below.append([round(v) for v in rb])
            # 引用 extract_figs.py 已导出的图片（命名 p<页码>_<序号>.<ext>）
            exported = sorted(glob.glob(os.path.join(a.figs_dir, f"p{idx+1}_*")))
            if len(imgs_below) <= len(exported):
                fname = os.path.basename(exported[len(imgs_below) - 1])
                md_parts.append(f"![图 p{idx+1}](./figs/{fname})")
            else:
                md_parts.append(f"<!-- 图片未导出：PDF 第 {idx+1} 页第 {len(imgs_below)} 张，"
                                f"请先跑 extract_figs.py 导出到 figs/ -->")
            if caption:
                md_parts.append(f"> {caption}")
        # 正文文本（图外）
        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            if not text.strip():
                continue
            inside_img = any(x0 >= r[0] and x1 <= r[2] and y0 >= r[1] and y1 <= r[3] for r in imgs_below)
            if not inside_img and classify(text) == "body":
                md_parts.append(text.strip())
    json.dump(mapping, open(os.path.join(a.figs_dir, "captions.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    open(a.out_md, "w", encoding="utf-8").write("\n\n".join(md_parts))
    print("OK captions.json + 图注 markdown ->", a.out_md)


if __name__ == "__main__":
    main()
