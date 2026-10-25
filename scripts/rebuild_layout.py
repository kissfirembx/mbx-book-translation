#!/usr/bin/env python3
"""rebuild_layout.py —— 版面/段落重建 + 跨页断句续接 + 页眉页脚清理（问题②③）

输入：原始提取文本（每行一行；可含 [PDF 第 X 页] 标记）。
输出：重建后的 Markdown。
规则（可调）：段首缩进=段落边界；句尾无终结标点=断句续接；页眉页脚/孤立数字/重复页眉清理。

用法：python rebuild_layout.py <IN.txt> <OUT.md>

能力边界（骨架版）：仅按「上一行无句末标点 → 拼接」与「纯数字行 → 判为页眉页脚」两条规则处理。
不做：段首缩进/行距判断（输入为纯文本，无坐标）、栏序修正、非数字型页眉页脚清理。
需要上述能力时，用 OCR 版管线（rebuild_human_action.py，有 box 坐标）或按书补规则。
"""
import argparse, re

TERM = "。！？；：”》）」"
KEEP_HEADERS = ("目录", "版权", "序", "前言", "引言", "导言", "附录", "参考文献", "后记")


def is_header_footer(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # 页码、罗马页码、孤立数字
    if re.fullmatch(r"[•·\s]*[0-9ivxlc]+[•·\s]*", s, re.I):
        return True
    if len(s) <= 6 and s.isdigit():
        return True
    return False


def clean_line(line: str) -> str:
    s = line.strip()
    # 去掉尾部重复出现的页眉行（如公司名/章节名反复出现）——骨架：交由人工配置，这里不强删
    return s


def rebuild(text: str):
    raw = [l.rstrip("\n") for l in text.splitlines()]
    paras = []
    cur = ""
    for line in raw:
        s = line.strip()
        if not s:
            continue
        if s.startswith("[PDF 第"):
            # 跨页标记：若当前段&上一段均无句末标点，则续接
            continue
        if is_header_footer(s):
            continue
        if s.startswith("第") and ("章" in s[:8] or "节" in s[:8]) and len(s) < 40:
            paras.append("\n\n## " + s + "\n")
            cur = ""
            continue
        if cur and (cur[-1] not in TERM):
            # 断句续接：直接拼（无标点则上一行未结束）
            cur += s
        elif cur and (s[0] in "，。！？；：”》）（"):
            cur += s
        else:
            # 新段落
            if cur:
                paras.append(cur)
            cur = s
    if cur:
        paras.append(cur)
    out = "\n\n".join(p for p in paras if p and p.strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_txt")
    ap.add_argument("out_md")
    a = ap.parse_args()
    text = open(a.in_txt, encoding="utf-8").read()
    open(a.out_md, "w", encoding="utf-8").write(rebuild(text))
    print("OK rebuild_layout ->", a.out_md)


if __name__ == "__main__":
    main()
