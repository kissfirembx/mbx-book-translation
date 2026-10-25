#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unwrap_paragraphs.py —— 硬折行源文的**段落重组**（Ⅲ 档源文的翻译前置步骤）

为什么需要（2026-10-07，《某商业书》实测）：
    PDF/EPUB 提取出的英文源文常常是「**按印刷行硬折、段落边界全丢**」：
    每行 110–160 字符、段落之间只有一个换行（没有空行），`preflight_probe.py` 判成 Ⅲ 档
    （实测：22 章全部 `paras=2`、段均 22–141 行）。
    Ⅲ 档规范要求「**翻译前**做确定性重组」，否则译者会各按各的感觉分段，无法复现。

判定信号（确定性、可复现）：
    **段落最后一行填不满版面**——所以「明显短于满行宽度」的行就是段落末行。
    满行宽度 W 取该文件非结构行长度的 75 分位（稳健，不受少数超长行影响）。

安全边界（本项目「格式转换零改写」硬规则）：
    **只增删空白与换行，不动任何字符**。落盘前做硬校验：
    去掉全部空白后逐字符相等，不等就中止。

用法：
    python unwrap_paragraphs.py --source-dir <书>/source_en                 # dry-run，只看统计
    python unwrap_paragraphs.py --source-dir <书>/source_en --apply         # 落盘（原文件备份为 *.hardwrap.bak）
    python unwrap_paragraphs.py --file <单个.txt> --apply
选项：--ratio 0.85（短行阈值＝满行宽度 × 该值）、--inplace/--out <dir>

阈值怎么定的（2026-10-07，《某商业书》实测）：
    对全书 4,119 个「非结构行」做行长直方图，结果是**双峰**——
    满行聚在 70–79（占 47.7%），段末短行均匀铺在 60 以下；**谷底落在 60**。
    交叉验证：全书切出约 1,206 段 ↔ 实测 <60 字符的行 1,270 个，数字对得上。
    W（满行宽）取该文件行长的 75 分位，落在那组满行里，故 **阈值 = 0.85W**。
    旧默认 0.75 偏保守，会把「59–60 字符的段末行」误当满行 → 段与段粘连
    （实测某章 65 段里 7 段超 100 词）。
"""
import argparse
import glob
import io
import os
import re
import sys

STRUCT = re.compile(r'^\s*(\[PDF 第|\[图片页|\[图片|\[插图|#{1,6}\s|>|[-*+]\s|\d+\.\s)')
HEAD_EN = re.compile(r'\s*\([A-Za-z][^()]*\)\s*$')      # 章标题尾部的英文括注


def unwrap(text, ratio):
    lines = text.split('\n')
    plain = [l for l in lines if l.strip() and not STRUCT.match(l) and not l.strip().startswith('#')]
    lens = sorted(len(l) for l in plain) or [120]
    W = lens[int(len(lens) * 0.75)]
    thr = max(40, int(W * ratio))

    out, buf = [], []

    PAGE = re.compile(r'^\s*\[(PDF 第|图片页|图片|插图)')

    def flush(blank=True):
        if buf:
            out.append(' '.join(buf).strip())
            if blank:
                out.append('')      # 段落之间补空行——不然并出来的段还是粘在一块，块数不变
            buf.clear()

    for l in lines:
        s = l.rstrip()
        if not s.strip():
            flush()
            out.append('')
            continue
        if PAGE.match(s):
            # **页码/图片页标记不切断段落**（跨页断句）：一段话常被分到两页，
            # 标记处若补空行，同一段会被拆成两段。所以这里 flush 但不补空行，
            # 标记之后的行继续留在同一个「空行分隔块」里，段数仍然守恒。
            flush(blank=False)
            out.append(s)
            continue
        if STRUCT.match(s):
            flush()
            # **标题原样保留**——本脚本只动空白，不改任何字符（零改写硬规则）。
            # 章标题尾部的中英文括注由译者按 FORMAT_BLOCK 处理（用给定的 {TITLE}）。
            out.append(s)
            continue
        buf.append(s.strip())
        if len(s) < thr:                        # 填不满版面 → 段落末行
            flush()
    flush()
    # 折叠连续空行
    res, prev_blank = [], False
    for l in out:
        if not l.strip():
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        res.append(l)
    return '\n'.join(res).strip() + '\n', W, thr


def _block_join(text, near=8):
    """只并块内换行：空行块 = 段落（2026-10-07）。

    页码标记 `[PDF 第 X 页]` 的处理（2026-10-07 补②，《某商业书》实测 375 处）：
      PDF 提取常把页码标记**单独放一行、且前后都没有空行**，于是一个「空行块」里
      往往夹着**两段不同的正文**——只并换行会把它们黏成一段（实测某章 18 处，
      读起来「两段合成一段」）。判据取自印刷事实：**跨页续接时，页末行几乎排满；
      段落末尾才会留白**。
        · 标记前一行**接近满行宽**（≥ W−8）**且**没有句末标点 → 句子跨页续接 → **不断段**
        · 其余 → 段落边界 → **在此断段**
      标记本身**并入段落行内**（译者按 FORMAT_BLOCK 丢弃），
      以保证「只增删空白、不动任何字符」的零改写自检仍然成立。
    """
    PAGE = re.compile(r'^\s*\[(PDF 第|图片页|图片|插图)')
    SENT_END = re.compile(r'[.!?…]["”’\')]]?\s*$')
    out = []
    for blk in re.split(r'\n\s*\n', text):
        raw = [l.rstrip() for l in blk.splitlines() if l.strip()]
        if not raw:
            continue
        plain = sorted(len(l) for l in raw
                       if not PAGE.match(l) and not l.lstrip().startswith('#'))
        W = plain[int(len(plain) * 0.75)] if plain else 120
        nearw = max(40, W - near)
        buf = []

        def flush():
            if buf:
                out.append(' '.join(buf))
                out.append('')
                del buf[:]

        for idx, l in enumerate(raw):
            s = l.strip()
            if s.startswith('#'):
                flush(); out.append(s); out.append('')
                continue
            if PAGE.match(s):
                prev = raw[idx - 1].strip() if idx > 0 else ''
                nxt = raw[idx + 1].strip() if idx + 1 < len(raw) else ''
                is_cont = bool(prev) and len(prev) >= nearw and not SENT_END.search(prev)
                buf.append(s)                     # 标记并入所在段（译者会丢弃）
                if (not is_cont and len(buf) > 1 and nxt
                        and not nxt.startswith('#') and not PAGE.match(nxt)):
                    flush()
                continue
            buf.append(s)
        flush()
    res, prev = [], False
    for l in out:
        if not l.strip():
            if prev:
                continue
            prev = True
        else:
            prev = False
        res.append(l)
    return '\n'.join(res).strip() + '\n'



SENT_END = re.compile(r"""[.!?…]["”’')\]]?\s*$""")
PAGE_ONLY = re.compile(r'^\[PDF 第 \d+ 页\]$')
BLOCK_STRUCT = re.compile(r'^\s*(#{1,6}\s|\[PDF|\[插图|\[图片|[-*+]\s|\d+[.)]\s|>)')


def merge_dangling(text):
    """把「末尾不是句末标点」的块并回下一块（2026-10-07 补，PDF 源必需）。

    病灶：`PyMuPDF` 的 `get_text('text')` 会在**文本块之间插空行**，而 PDF 的「块」
    比段落细——一个段落常被切成 2–8 块（作者注、带斜体的句子尤其容易）。
    《某商业书》实测：不做这一步，1,672 块里 **796 块（47.6%）** 以非句末标点结尾。
    只并「句中断口」：下一块若是标题/页码/插图/列表项等结构行，则不并。
    """
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
    out = []
    for b in blocks:
        # **跨页断句**：单独成块的页码标记不是段落边界——先并回上一块，
        # 这样紧随其后的续写文字还能继续并（否则 20% of… / [PDF] / revenue. If… 会被截成两段）
        if PAGE_ONLY.match(b):
            if out:
                out[-1] = out[-1] + ' ' + b
            else:
                out.append(b)
            continue
        if (out and len(out[-1]) >= 60 and not SENT_END.search(out[-1])
                and not BLOCK_STRUCT.match(b) and not out[-1].startswith('[')):
            out[-1] = out[-1] + ' ' + b
        else:
            out.append(b)
    return '\n\n'.join(out) + '\n'


def nows(s):
    return re.sub(r'\s+', '', s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir')
    ap.add_argument('--file')
    ap.add_argument('--ratio', type=float, default=0.85,
                    help='短行阈值＝满行宽度 × 该值（默认 0.85；推导见文件头「阈值怎么定的」）')
    ap.add_argument('--out', default=None, help='输出到别的目录（默认原地覆盖）')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--merge-dangling', action='store_true',
                    help='把「末尾不是句末标点」的块并回下一块（PDF 源；配合 --no-split 用）')
    ap.add_argument('--no-split', action='store_true',
                    help='只把「空行块内的换行」并起来，**不按短行再切段**——'
                         '源文的空行分段本来就是段落时用这个（否则会把段中短行误当段末，切出大量「一句一段」）')
    a = ap.parse_args()

    files = [a.file] if a.file else sorted(glob.glob(os.path.join(a.source_dir or '', '*.txt')))
    if not files:
        sys.exit('没找到 .txt（给 --source-dir 或 --file）')

    for fp in files:
        src = io.open(fp, encoding='utf-8', errors='replace').read()
        if a.no_split:
            new = _block_join(src)
            if a.merge_dangling:
                new = merge_dangling(new)
            W = thr = 0
        else:
            new, W, thr = unwrap(src, a.ratio)
        if nows(src) != nows(new):
            print('✗ %s：零改写校验失败（去空白后字符不等）——已跳过，请人工查' % os.path.basename(fp))
            continue
        n_before = len([b for b in re.split(r'\n\s*\n', src) if b.strip()])
        n_after = len([b for b in re.split(r'\n\s*\n', new) if b.strip()])
        print('  %-30s 满行宽 %3d 阈值 %3d │ 段 %3d → %3d │ 字符 %d→%d' % (
            os.path.basename(fp), W, thr, n_before, n_after, len(src), len(new)))
        if a.apply:
            dst = os.path.join(a.out, os.path.basename(fp)) if a.out else fp
            if a.out:
                os.makedirs(a.out, exist_ok=True)
            else:
                io.open(fp + '.hardwrap.bak', 'w', encoding='utf-8').write(src)
            io.open(dst, 'w', encoding='utf-8').write(new)
    print('\n%s' % ('已落盘。' if a.apply else '（dry-run，未落盘）'))


if __name__ == '__main__':
    main()
