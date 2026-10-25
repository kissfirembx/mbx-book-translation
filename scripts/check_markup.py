#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_markup.py —— Markdown 标记体检（正则，零 token）

为什么需要：Obsidian 对 `*` 极敏感。源文用 `*` 同时当**列表符**（`* Option #1:`）和
**斜体强调**（`*aspect*`），译者若照抄，译文里就会留下**落单的 `*`**——Obsidian 要么当
斜体、要么当标签，渲染出来是一坨乱码。2026-10-07 真实试水：一整章 219 处星号游程全错
（`**粗体**` 被写成 `***粗体***`），且**段落级指标（`check_fluency.py`）完全看不见**——
它只看中文行文，不看符号。

七类形态：
  ① 落单星号：一个 `*` 两侧都不是 `*` —— Obsidian 里必坏，最高优先级
  ② 奇数长游程：`***`/`*****`（粗+斜，模板明令不写）
  ③ 行首 `* ` 列表符：应统一为 `- `
  ④ 加粗未闭合：整行 `**` 个数为奇（落单的开或闭）
  ⑤ HTML 表格残留：`<table>`/`<td>` 等（FORMAT_BLOCK 要求转 Markdown 表）
  ⑥ 加粗配对错位：按 `**…**` 配对后，某段内容以中文标点开头（如 `**，尽可能多地收费。**`）
  ⑦ 井号会成标签：`#`+数字 后紧跟中文或全角标点（如 `选项 #1：…`）——
     Obsidian 会一直吃到空格为止，把整句索引成标签（2026-10-07 实测标签索引里有
     `#1：把每月新增客户数翻倍（也就是`）。ASCII 的 `#1:`／`#1.` 不成标签，不报。

不体检的地方：代码块（``` 围栏内）、行内代码（`…`，其中的 `*` 是字面内容）、图片行、
以及**独立成行的纯星号行**（`***`／`* * *`，是作者有意保留的**装饰分隔符**，不是标记错误）。
行内代码必须挖掉，否则文档里 `` `*.bak` ``、`` `***` `` 这类正常写法会被全报成落单星号。

用法：
    python check_markup.py --book-dir <书目录>
    python check_markup.py --dir <书目录> --suffix _重译版
    python check_markup.py --target <译.md>
选项：--no-html（跳过 ⑤）、--json
退出码：有命中 1，干净 0。
"""
import argparse
import json
import os
import re
import sys

RUN = re.compile(r'\*+')
# ⑥ 配对后的加粗段以中文标点开头 —— 说明 `**` 配对错位
#    （实测 `**在让客户满意的**同时**，尽可能多地收费。**` 会被配成 `**，尽可能多地收费。**`）
#    必须先按 `**…**` 配对再看内容，不能直接扫 `**`+标点——否则会把「闭合 `**` 紧跟标点」全误报
SPAN = re.compile(r'\*\*([^*\n]+?)\*\*')
LEAD_PUNCT = re.compile(r'^[，。；：、！？）】」』]')
LIST_STAR = re.compile(r'^(\s*)\*(\s+)')
# **独立成行的纯星号行 = 装饰分隔符**（源文实测 `***` 单占一行，用作段间分隔，如 某商业书 8 处）。
# 它是作者有意保留的「标志符号」，不是标记错误——不能按「奇数长游程」报，更不能被修掉。
DIVIDER = re.compile(r'^\s*\*[\s*]*$')
HTML_TBL = re.compile(r'</?(?:table|thead|tbody|tr|th|td)\b', re.I)
# ⑦ 会变成 Obsidian 标签的井号（2026-10-07 实测：`#1：把每月新增客户数翻倍（也就是` 整条进了标签索引）
#    Obsidian 标签 = `#` 紧跟非空白字符；**纯数字不算标签，但只要后面接了非数字就成立**——
#    中文与全角标点都算合法标签字符，所以 `#1：中文…` 会一直吃到空格为止，整段变成标签。
#    口径（2026-10-07 用 Obsidian 标签索引校准）：**只有「`#`+数字 后面紧跟中文/全角标点」才会成标签**。
#    ASCII 的 `#1:`／`#1.` 不成标签（`:` `.` 不是合法标签字符，剩下的 `#1` 是纯数字、Obsidian 不算标签）；
#    全角 `#1：`／`#1、`／`#1，` 成标签（实测索引里就有）。所以只报含中文或全角标点的形态。
HASH = re.compile(r'(?<!\\)#(?=[0-9]*[A-Za-z_一-鿿　-〿＀-￯])')
HEADING_PREFIX = re.compile(r'^#{1,6}(?=\s)')
# 行内代码 / 代码块 / 图片行不体检
SKIP_LINE = re.compile(r'^\s*(```|~~~|!\[|\|?\s*<img)')
# **行内代码里的星号是字面内容，不是标记**——不挖掉会把 `` `\*([^*]+)\*` ``、`` `***` ``、
# `` `*.bak` `` 这类正常写法全报成落单星号（2026-10-07 自检 skill 文档时实测的假阳性）。
CODE = re.compile(r'``[^`]*``|`[^`\n]*`')
# **转义过的星号是字面内容**：`\*` 在 Markdown 里渲染成一个可见的 `*`。
# 不排除就会误报——`\*\*`（显示成 `**` 的字面写法）是「`\`+`*`+`\`+`*`」，
# 两个 `*` 被反斜杠隔开、各成单星游程，会被判成「落单星号」（2026-10-07 实测误报）。
ESCAPED_STAR = re.compile(r'\\\*')


def scan(text, html=True):
    """返回 [(line_no, kind, detail), ...]"""
    out = []
    in_fence = False
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if in_fence or SKIP_LINE.match(ln):
            continue
        # 独立成行的纯星号行 = 装饰分隔符：本身不是错，但按规定写法要转成 `---`
        if DIVIDER.match(ln):
            out.append((i, '分隔符应为 ---', '源文独立成行的星号分隔符，规定转 `---`：%s'
                        % ln.strip()[:40]))
            continue
        # 行内代码与转义星号替换成等长空格：长度不变（定位不偏），字符不再计入
        s = CODE.sub(lambda m: ' ' * len(m.group(0)), ln)
        s = ESCAPED_STAR.sub('  ', s)
        runs = sorted({len(m.group(0)) for m in RUN.finditer(s)})
        if 1 in runs:
            out.append((i, '落单星号', '有单个 `*`（Obsidian 会当斜体/标签）：%s' % ln.strip()[:60]))
        elif any(r % 2 for r in runs):
            out.append((i, '奇数长游程', '本行星号游程长度 %s（只允许 2）'
                        % [r for r in runs if r % 2]))
        if LIST_STAR.match(s):
            out.append((i, '行首星号列表符', '应为 `- `：%s' % ln.strip()[:60]))
        if s.count('**') % 2:
            out.append((i, '加粗未闭合', '本行 `**` 个数为奇：%s' % ln.strip()[:60]))
        elif any(LEAD_PUNCT.match(m.group(1)) for m in SPAN.finditer(s)):
            out.append((i, '加粗配对错位', '有加粗段以中文标点开头（`**` 配对错位）：%s' % ln.strip()[:60]))
        if html:
            m = HTML_TBL.search(s)
            if m:
                out.append((i, 'HTML 表格残留', '应转 Markdown 表：%s' % m.group(0)))
        # ⑦ 井号会成标签（先把行首标题标记挖掉，再找残留的 `#`）
        body = s[HEADING_PREFIX.match(s).end():] if HEADING_PREFIX.match(s) else s
        for m in HASH.finditer(body):
            tok = re.match(r'#\S*', body[m.start():]).group(0)
            out.append((i, '井号会成标签', 'Obsidian 会索引成标签 `%s`：%s'
                        % (tok[:30], ln.strip()[:50])))
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--dir')
    ap.add_argument('--target')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--no-html', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.target:
        files = [args.target]
    else:
        d = args.dir or args.book_dir
        if not d:
            sys.exit('需要 --book-dir / --dir / --target 之一')
        tgt = os.path.join(d, 'zh')
        if not os.path.isdir(tgt):
            tgt = d
        files = [os.path.join(tgt, f) for f in sorted(os.listdir(tgt))
                 if f.endswith('.md') and (args.suffix or '') in f]
    if not files:
        sys.exit('未找到 .md')

    report, bad = {}, 0
    for fp in files:
        text = open(fp, encoding='utf-8').read()
        found = scan(text, html=not args.no_html)
        report[os.path.basename(fp)] = [
            dict(line=n, kind=k, detail=d) for n, k, d in found]
        name = os.path.basename(fp)
        if found:
            bad += 1
            print('✗ %s（%d 处）' % (name, len(found)))
            for n, k, d in found[:12]:
                print('   行 %-5d [%s] %s' % (n, k, d))
            if len(found) > 12:
                print('   …另 %d 处' % (len(found) - 12))
        else:
            print('✓ %s 标记干净' % name)
    print('\n文件 %d 个，有问题 %d 个' % (len(files), bad))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
