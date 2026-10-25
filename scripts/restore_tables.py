#!/usr/bin/env python3
"""restore_tables.py —— 真实文字表格还原（问题①③）

仅处理「描边线」判定的真实文字表格；图片数据图不拆，保留整图。
产出：插入 Markdown 表格的 MD。

用法：python restore_tables.py <PDF> <OUT_MD>
依赖：pymupdf (fitz)
"""
import argparse
try:
    import fitz
except ImportError:
    fitz = None


def get_lines(page):
    horiz, vert = [], []
    for d in page.get_drawings():
        t = d.get("type")
        if t == "l":
            p = d["rect"]
            if p.width > p.height:
                horiz.append((p.y0, p.x0, p.x1))
            else:
                vert.append((p.x0, p.y0, p.y1))
        elif t == "re":
            p = d["rect"]
            horiz.append((p.y0, p.x0, p.x1))
            vert.append((p.x0, p.y0, p.y1))
    return horiz, vert


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_md")
    a = ap.parse_args()
    if not fitz:
        raise SystemExit("需要 pip install pymupdf")
    doc = fitz.open(a.pdf)
    md = []
    for idx, page in enumerate(doc):
        horiz, vert = get_lines(page)
        # 判定为真表格：有足够多的横向线贯穿同一 x 区间，且成网格
        if len(horiz) >= 3:
            ys = sorted(set(round(h[0]) for h in horiz))
            xs = sorted(set(round(v[0]) for v in vert))
            if len(xs) >= 2:
                # 提取表内 words，按最近行列归档
                words = page.get_text("words")
                rows = len(ys)
                cols = len(xs) - 1 if len(xs) > 1 else max(len(words), 1)
                grid = [[""] * cols for _ in range(max(rows - 1, 1))]
                for w in words:
                    x0, y0, _, _, txt, *_ = w
                    r = min(range(len(ys) - 1), key=lambda k: abs((ys[k] + ys[k + 1]) / 2 - y0), default=0)
                    c = min(range(cols), key=lambda k: abs(xs[k] - x0), default=0)
                    if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
                        grid[r][c] = (grid[r][c] + " " + txt).strip()
                md.append("\n\n" + "\n".join(
                    "|" + "|".join(cell for cell in row) + "|" for row in grid) + "\n")
            else:
                md.append(page.get_text())
        else:
            md.append(page.get_text())
    doc.close()
    open(a.out_md, "w", encoding="utf-8").write("\n\n".join(md))
    print("OK restore_tables ->", a.out_md)


if __name__ == "__main__":
    main()
