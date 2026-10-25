# -*- coding: utf-8 -*-
"""italic_to_bold.py —— 单星斜体 → 双星加粗（供 `patch_preview.py --script` 调用）

规则（`executor-prompt-templates.md` FORMAT_BLOCK）：
    源文的 `*斜体*` 与 `**加粗**` **在译文里一律写成 `**加粗**`**。

**为什么不能一把正则 `\\*([^*]+)\\*` 了事**（2026-10-07 实测踩过，代价：整章 219 处标记被改坏）：
    那把正则会把已配对的 `**粗体**` 一起吃成 `***粗体***`，而**中文行文毫无异常**，
    `check_fluency` / `check_numbers` / `check_paragraph_map` 全绿，只有符号烂了。

正确做法是「**占位符保护**」四步：
    ① 保护转义星号 `\\*`（字面内容，不能动）
    ② 归一 `***X***`（粗+斜）→ `**X**`
    ③ 保护已配对的 `**X**`
    ④ 剩下的 `*X*` 才转 `**X**`
最后按逆序还原占位符。**幂等**：再跑一次不会变（`patch_preview.py` 会自检这一点）。
"""
import re

ESC = re.compile(r'\\\*')
TRIPLE = re.compile(r'\*{3,}([^*\n]+?)\*{3,}')
BOLD = re.compile(r'\*\*[^*\n]+\*\*')
ITAL = re.compile(r'(?<!\*)\*([^*\n]+?)\*(?!\*)')

PH = ''   # 占位符（私有区，正文里不会出现）


def _protect(line, store):
    def keep(m):
        store.append(m.group(0))
        return '%s%d%s' % (PH, len(store) - 1, PH)
    return keep


def transform(line):
    # 独立成行的分隔符行不动（`***` 已按规范转 `---`，这里只兜底）
    if line.strip() and set(line.strip()) <= set('*　 '):
        return line
    store = []
    line = ESC.sub(_protect(line, store), line)               # ① 转义星号
    line = TRIPLE.sub(lambda m: '**%s**' % m.group(1), line)  # ② 粗+斜 → 粗
    line = BOLD.sub(_protect(line, store), line)              # ③ 保护已配对加粗
    line = ITAL.sub(lambda m: '**%s**' % m.group(1), line)    # ④ 单星斜体 → 加粗
    for i in range(len(store) - 1, -1, -1):                   # 逆序还原
        line = line.replace('%s%d%s' % (PH, i, PH), store[i])
    return line
