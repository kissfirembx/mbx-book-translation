#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""escape_hash.py —— 给「会变成 Obsidian 标签」的 `#` 加反斜杠（供 patch_preview.py --script）

为什么需要：正文里的 `#1：`、`#mozination`、`#gymlord` 都会被 Obsidian **索引成标签**——
标签 = `#` 紧跟非空白字符；**纯数字不算**，但只要后面接了任何非数字（字母／中文／全角标点）就算。
实测：《某商业书》漏 5 处、《某商业书》漏 2 处、《_术语体系》漏 1 处。

判据（与 Obsidian 实际行为同口径）：**`#` 后面只要不是「纯数字」就转义**——
`#1：`／`#mozination`／`#1］` 都转，`#1`（后面跟空白）不转。
已转义的（前面有反斜杠）不动 → **幂等**。
⚠️ **行首的标题标记 `# `~`###### ` 必须先排除**，否则会把整个标题转义掉。
⚠️ 本脚本按**行**变换，**看不见代码块状态**——若目标文件含 ``` 围栏且围栏内有 `#`，
先 `--sample-lines` 看样本再落盘（这类书几乎没有，但要知道这个边界）。

用法：
    python scripts/patch_preview.py --book-dir <书> --script <本文件>              # dry-run
    python scripts/patch_preview.py --book-dir <书> --script <本文件> --expect N --apply
"""
import re

# `#` 后跟「非空白、非 #」的串，且该串里**至少有一个非数字** → 是标签
HASH = re.compile(r'(?<!\\)#(?=[^\s#]*[^\s\d#])')
HEADING = re.compile(r'^#{1,6}\s')


def transform(line):
    m = HEADING.match(line)
    if m:                                    # 保住行首标题标记，只处理正文部分
        return line[:m.end()] + HASH.sub(r'\\#', line[m.end():])
    return HASH.sub(r'\\#', line)
