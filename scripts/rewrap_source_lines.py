#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rewrap_source_lines.py —— 源文长行预折行（翻译前必做，防 read 截断静默丢尾）

为什么需要：`read` 工具**按行截断在 2000 字符**。古典与学术类源文常把一整节挤在一个物理行里
（实测有源文单行上万字符），译者读到的就是被砍掉尾巴的残行：
有的子代理自己用 pwsh 补读（多付往返），有的**静默按残行翻译**——丢内容且无人察觉。
折行后每行 ≤ 目标长度，译者的「只读源文一个文件」才成立。

安全边界（本项目「格式转换零改写」硬规则）：
- 只增删**空白与换行**，不动任何字符；落盘前用「去掉全部空白后逐字符相等」硬校验，不等就中止
- 断点优先级：`[n]` 段标记前 > 句末标点后 > 分号/冒号后 > 空格；绝不在单词中间断
- `[n]` 标记数量、`[图片页]`/`[PDF 第 N 页]` 计数前后必须相等

用法：
    python rewrap_source_lines.py --source-dir <书>/source_en                # dry-run，只报统计
    python rewrap_source_lines.py --source-dir <书>/source_en --apply        # 落盘（先备份）
    python rewrap_source_lines.py --file <单文件> --max-len 900 --apply
参数：
    --max-len   目标行上限（默认 1000；需明显小于 read 的 2000 截断线）
    --min-fill  同一行内切点与前一切点的最小间隔（默认 300，避免切出碎行）
    --sep       换行方式：newline（默认，单换行，纯折行）| blank（空行分段）
    --at-markers  只在 [n] 段标记处切，并把每段写成独立段落（用于「整节挤一行」的书）
"""
import argparse, os, re, shutil, sys

# 断点：句末标点（含引号/括号收尾）后接空格；要求后面跟大写或引号开头，避免缩写误切
SENT = re.compile(r'(?<=[.!?])["”\')]?\s+(?=[A-Z"“(\d])')
CLAUSE = re.compile(r'(?<=[;:])\s+')
MARK = re.compile(r'\s+(?=\[\d+\])')          # [n] 标记前
SPACE = re.compile(r'\s+')


def _ws_at(m):
    """切点 = 匹配内部第一个空白字符的位置。

    为什么不能直接用 m.start()：句末标点的匹配会把收尾引号一起吃掉
    （`action.” “I have…`），若在 m.start() 处切，收尾引号会被推到下一行行首，
    词序列随之改变（实测 03_book_iii.txt 因此触发零改写校验失败）。
    """
    w = re.search(r'\s', m.group(0))
    return m.start() + (w.start() if w else 0)


def cut_points(line, at_markers=False):
    """返回可切位置列表（字符下标，切割点在该空白之前）"""
    pts = [_ws_at(m) for m in MARK.finditer(line)]
    if not at_markers:
        for rx in (SENT, CLAUSE):
            pts.extend(_ws_at(m) for m in rx.finditer(line))
    pts = sorted(set(p for p in pts if p > 0))
    if not pts or not at_markers:
        pts.extend(_ws_at(m) for m in SPACE.finditer(line) if _ws_at(m) > 0)
    return sorted(set(pts))


def wrap_plain(text, max_len, min_fill):
    """纯折行：只按空白切，不改动任何非空白字符"""
    out, rest = [], text
    while len(rest) > max_len:
        pts = [p for p in cut_points(rest) if min_fill <= p <= max_len]
        if not pts:
            pts = [p for p in cut_points(rest) if p <= max_len]
        if not pts:
            break                              # 单个超长无空格 token：放弃，原样保留
        cut = max(pts)
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    out.append(rest)
    return [x for x in out if x != '']


def wrap_line(line, max_len, min_fill, at_markers=False):
    """把一行切成多行；返回列表（不改动任何非空白字符）

    at_markers=True：先在每个 [n] 段标记前断开（恢复「一节一行」被挤扁的段落结构），
    再对仍然超过 max_len 的**单个段**退回纯折行——否则一个超长 [n] 段会原样留住，
    read 的 2000 字符截断照旧发生（实测 09_book_ix.txt 会留下 5,267 字符的行）。
    """
    if at_markers:
        marks = [_ws_at(m) for m in MARK.finditer(line)]
        bounds = [0] + [p for p in marks if 0 < p < len(line)] + [len(line)]
        pieces, out = [], []
        for a, b in zip(bounds, bounds[1:]):
            seg = line[a:b].strip()
            if not seg:
                continue
            pieces.extend(wrap_plain(seg, max_len, min_fill) if len(seg) > max_len else [seg])
        return pieces
    return wrap_plain(line, max_len, min_fill)


def content(text):
    """去掉全部空白后的内容签名——防止增删字符"""
    return re.sub(r'\s+', '', text)


def words(text):
    """空白标准化后的词序列签名——防止词间空格丢失把两个词粘成一个"""
    return ' '.join(text.split())


def wrap_text(text, max_len, min_fill, sep, at_markers):
    nl = '\n\n' if sep == 'blank' else '\n'
    lines = text.split('\n')
    wrapped, touched = [], 0
    for ln in lines:
        if at_markers or len(ln) > max_len:
            parts = wrap_line(ln, max_len, min_fill, at_markers)
            if len(parts) > 1:
                touched += 1
            wrapped.extend(parts)
        else:
            wrapped.append(ln)
    return nl.join(wrapped), touched


def stats(text):
    lines = text.split('\n')
    body = [l for l in lines if l.strip()]
    return dict(行数=len(body), 最长行=max((len(l) for l in body), default=0),
                超限行=sum(1 for l in body if len(l) > 2000),
                段标记=len(re.findall(r'\[\d+\]', text)),
                页标记=len(re.findall(r'\[(?:PDF 第 \d+ 页|图片页[^\]]*)\]', text)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir')
    ap.add_argument('--file')
    ap.add_argument('--max-len', type=int, default=1000)
    ap.add_argument('--min-fill', type=int, default=300)
    ap.add_argument('--sep', choices=['newline', 'blank'], default='newline')
    ap.add_argument('--at-markers', action='store_true')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    if args.file:
        targets = [(os.path.dirname(args.file), [os.path.basename(args.file)])]
    elif args.source_dir:
        targets = [(args.source_dir, sorted(f for f in os.listdir(args.source_dir) if f.endswith('.txt')))]
    else:
        sys.exit('需要 --file 或 --source-dir')

    plan, bad = [], []
    for d, files in targets:
        for fn in files:
            p = os.path.join(d, fn)
            old = open(p, encoding='utf-8').read()
            new, touched = wrap_text(old, args.max_len, args.min_fill, args.sep, args.at_markers)
            # 零改写双重校验：① 去掉全部空白后逐字符相等（没增删字符）② 词序列相等（没丢词间空格）
            if content(old) != content(new):
                bad.append(fn + '（字符内容变化）')
                continue
            if words(old) != words(new):
                bad.append(fn + '（词序列变化，疑丢空格）')
                continue
            so, sn = stats(old), stats(new)
            if so['段标记'] != sn['段标记'] or so['页标记'] != sn['页标记']:
                bad.append(fn + '（标记数变化）')
                continue
            plan.append((p, fn, touched, so, sn, new))

    print('%-34s %6s %6s %6s %8s %8s' % ('文件', '最长行', '→最长', '折行数', '段落前', '段落后'))
    print('-' * 78)
    tot_touch, still = 0, []
    for p, fn, touched, so, sn, new in plan:
        tot_touch += touched
        over = [l for l in new.split('\n') if len(l) > max(args.max_len, 2000)]
        if over:
            still.append((fn, max(len(l) for l in over)))
        print('%-34s %6d %6d %6d %8d %8d' % (fn[:34], so['最长行'], sn['最长行'], touched,
                                             so['行数'], sn['行数']))
    if still:
        print('\n注意：以下文件折行后仍有超过 %d 字符的行（多为无空格的长 token，需人工看）：' % args.max_len)
        for fn, n in still:
            print('   %s 最长 %d 字符' % (fn, n))
    if bad:
        print('\n零改写校验未通过（已跳过，不会落盘）：%s' % ', '.join(bad))
    print('\n合计折行 %d 行；目标行上限 %d，read 截断线 2000' % (tot_touch, args.max_len))

    if not args.apply:
        print('（dry-run，未落盘；确认后加 --apply）')
        return 1 if bad else 0

    if bad:
        sys.exit('存在校验失败项，拒绝落盘')
    for d, files in targets:
        bak = d.rstrip('\\/') + '_旧_长行版'
        if not os.path.exists(bak):
            shutil.copytree(d, bak)
            print('旧源文已备份到 %s' % bak)
    for p, fn, touched, so, sn, new in plan:
        open(p, 'w', encoding='utf-8', newline='').write(new)
    print('已重写 %d 个文件' % len(plan))
    return 0


if __name__ == '__main__':
    sys.exit(main())
