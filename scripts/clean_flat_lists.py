#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_flat_lists.py —— 清理 EPUB 展平产物造成的重复清单

背景：EPUB 的嵌套 `<ol>` 被文本提取展平后，同一清单常在一章里出现两遍
（段落版 + 文末 `- ` 清单版）。译文若照单全收，读者会看到相邻重复的小结。

两遍处理（都只删「内容行」本身，不删块内夹着的插图行、标题行、空行）：
  第一遍 content-run：连续 ≥MINRUN 条内容行在文件中另有一处完全相同的连续序列 → 删后一段
  第二遍 orphan-tail：章末（完成标记之前）一段 ≥3 条的 `- ` 清单，条目在前文均已出现 → 整段删除

安全约束：
- 只考虑长度 ≥MINLEN 的归一化内容行（默认 18 字符；`--min-len 8` 可覆盖短条目清单）
- 归一化抹掉粗体/斜体标记、列表前缀、全角缩进、空白，避免 `*x*` 与 `**x**` 造成的假阴性
- 删除前后各校验一次：被删文本必须仍能在文件别处找到；插图引用数不得减少
- 默认 dry-run，须显式 `--apply`

用法：
    python clean_flat_lists.py --dir <书目录>/zh              # 默认处理 *.md，dry-run
    python clean_flat_lists.py --dir <书目录>/zh --apply      # 落盘
    python clean_flat_lists.py --dir <书目录>/zh --suffix _重译版.md
        # --suffix 只按文件名结尾过滤；默认 .md 适配现行 zh/NN_名字.md。
        # 只有需要单独清理历史稿时才传 _重译版.md。
"""
import argparse, os, re, sys

BULLET = re.compile(r'^\s*[-*]\s+\S')
SKIP = re.compile(r'^\s*(!\[|<!--|#{1,6}\s|>)')
MARK = '<!-- 本章翻译完成 -->'


def norm(line):
    s = re.sub(r'^\s*[-*]\s*', '', line.strip())
    s = re.sub(r'^\u3000+', '', s)
    s = re.sub(r'\s+', '', s.replace('*', '').replace('_', ''))
    return s


def is_ignorable(line):
    s = line.strip()
    return s == '' or s.startswith('<!--') or s.startswith('![')


def content_lines(lines, minlen):
    out = []
    for i, l in enumerate(lines):
        if SKIP.match(l) or not l.strip():
            continue
        k = norm(l)
        if len(k) >= minlen:
            out.append((i, k))
    return out


def content_run_blocks(lines, minlen, minrun):
    """返回需删除的行号集合（仅内容行本身）"""
    cs = content_lines(lines, minlen)
    keys = [k for _, k in cs]
    n = len(keys)
    del_idx, covered = set(), set()
    for i in range(n):
        if i in covered:
            continue
        for j in range(i + 1, n):
            if j in covered or keys[j] != keys[i]:
                continue
            m = 0
            while i + m < j and j + m < n and keys[i + m] == keys[j + m]:
                m += 1
            if m >= minrun:
                for x in range(j, j + m):
                    del_idx.add(cs[x][0])
                    covered.add(x)
                break
    return del_idx


def orphan_tail_block(lines, min_items=3):
    i = len(lines) - 1
    while i >= 0 and is_ignorable(lines[i]):
        i -= 1
    end = i
    if end < 0 or not BULLET.match(lines[end]):
        return None
    while i >= 0 and (is_ignorable(lines[i]) or BULLET.match(lines[i])):
        i -= 1
    start = i + 1
    items = [k for k in range(start, end + 1) if BULLET.match(lines[k])]
    if len(items) < min_items:
        return None
    before = [norm(l) for l in lines[:start] if l.strip()]
    hit = sum(1 for k in items if norm(lines[k]) and norm(lines[k]) in before)
    # 必须「全部条目」在前文逐字出现才算残留：实测放宽到 70% 会误删书里真正的章尾清单
    if hit != len(items):
        return None
    return items


def collapse_blanks(lines):
    out, prev_blank = [], False
    for l in lines:
        b = (l.strip() == '')
        if b and prev_blank:
            continue
        out.append(l)
        prev_blank = b
    return out


def process(path, minlen, apply):
    text = open(path, encoding='utf-8').read()
    lines = text.split('\n')
    imgs_before = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)

    del_idx = content_run_blocks(lines, minlen, 3)
    tail = orphan_tail_block(lines)
    if tail:
        del_idx |= set(tail)
    if not del_idx:
        return None

    out = [l for i, l in enumerate(lines) if i not in del_idx]
    out = collapse_blanks(out)
    res = '\n'.join(out)

    # 安全校验
    imgs_after = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', res)
    if len(imgs_after) != len(imgs_before):
        print('  !! 插图数变化 %d -> %d，已中止该文件' % (len(imgs_before), len(imgs_after)))
        return None
    survivor = {norm(l) for l in out if l.strip()}
    orphan = [lines[i] for i in sorted(del_idx)
              if norm(lines[i]) and len(norm(lines[i])) >= minlen and norm(lines[i]) not in survivor
              and not SKIP.match(lines[i])]
    # 粗粒度判定：条目可能在别处措辞不同，这里仅提示，不阻断
    if apply:
        open(path, 'w', encoding='utf-8', newline='').write(res)
    return (len(del_idx), len(orphan))


def main():
    ap = argparse.ArgumentParser(
        description='清理 EPUB 展平造成的重复清单（默认 dry-run）。',
        epilog='示例：python clean_flat_lists.py --dir 书目录/zh --apply')
    ap.add_argument('--dir', required=True, help='章节 md 所在目录')
    ap.add_argument('--suffix', default='.md',
                    help='只处理以该串结尾的文件（默认 .md，适配现行 zh/NN_名字.md；'
                         '清历史稿可传 _重译版.md）')
    ap.add_argument('--min-len', type=int, default=18,
                    help='内容行归一化后的最少字符数（默认 18；短条目清单用 8）')
    ap.add_argument('--apply', action='store_true', help='真正写盘；默认只预演')
    args = ap.parse_args()

    matched = 0
    total, files = 0, 0
    for fn in sorted(os.listdir(args.dir)):
        if not fn.endswith(args.suffix):
            continue
        matched += 1
        r = process(os.path.join(args.dir, fn), args.min_len, args.apply)
        if not r:
            continue
        n, orphan = r
        total += n
        files += 1
        print('%-52s 删除 %3d 行%s%s' % (os.path.splitext(fn)[0], n,
              ('，前文未逐字留存 %d 条（请人工确认）' % orphan) if orphan else '',
              '' if args.apply else '  [dry-run]'))
    if matched == 0:
        print('\n未匹配到任何文件：%s（--suffix %r）' % (args.dir, args.suffix),
              file=sys.stderr)
        print('提示：现行章节命名是 zh/NN_名字.md，默认 --suffix .md；'
              '只有单独清历史稿时才传 _重译版.md。', file=sys.stderr)
        return 2
    print('\n合计：%d 个文件、%d 行%s' % (files, total, '（已落盘）' if args.apply else '（dry-run，未落盘）'))
    print('注意：删除前请核对 orphan 提示；插图数已在文件级校验，不一致会中止该文件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
