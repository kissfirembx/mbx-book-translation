#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rotate_round.py —— 轮次归档（把「当前轮」整包搬进 `_归档/`）

为什么需要：`<书名>/` 顶层同时堆着多轮产物（第一稿、重译版、质检清单、规格）时，
分不清哪份是当前的。本 skill 的结构规则是——**任何时刻顶层只有一份译稿、一份成品、
一份规格**；开新一轮之前，把上一轮整体搬进 `_归档/<日期>_<轮次名>/`。本脚本执行这一步。

搬什么（= 本轮区）：
  - `zh/**`            → `_归档/<日期>_<名>/zh/`
  - 顶层成品 md          → `_归档/<日期>_<名>/`（名字含「中文全译」或「原文版」）
  - `翻译任务规格.md`     → 同上
  - `_过程/**`          → `_归档/<日期>_<名>/_过程/`

不搬什么（= 输入区，跨轮稳定）：原件、`source_en/`、`figs/`、`ocr/`、`ocr_md/`、
`chapter-figs.json`、`merge-config.json`。

移动走 Obsidian CLI（`obsidian move`），落盘后逐条用文件系统核实——**该 CLI 的报错
与退出码不可信**（实测会报 "not found" 却已移动成功），所以只认事后检查。
（CLI 的入口是 `obsidian.COM`，不是 `Obsidian.exe`；后者从 PowerShell 调会静默失败。）

用法：
    python rotate_round.py --book-dir <书目录> --name 重译            # 预演（默认 dry-run）
    python rotate_round.py --book-dir <书目录> --name 首译 --apply    # 执行
选项：--date YYYY-MM-DD（默认今天）、--vault <vault 名>（默认本库）
退出码：0 成功/预演，1 失败。
"""
import argparse
import datetime
import os
import subprocess
import sys

FINISH_PAT = ('中文全译', '原文版')          # 顶层成品的识别特征
ROUND_ITEMS = ['zh', '_过程']               # 整目录搬走
ROUND_FILES = ['翻译任务规格.md']


def vault_root(vault):
    """用 Obsidian CLI 取 vault 根路径。"""
    out = subprocess.run(['obsidian', 'vault=%s' % vault, 'eval',
                          'code=app.vault.adapter.basePath'],
                         capture_output=True, text=True)
    line = (out.stdout or '').strip()
    if line.startswith('=>'):
        return line[2:].strip()
    sys.exit('取不到 vault 根路径：%r %r\n（Obsidian 没开？vault 名不对？）'
             % (out.stdout, out.stderr))


def cli_move(vault, src_rel, dst_rel):
    """调用 obsidian move；返回值不可信，由调用方用文件系统核实。"""
    subprocess.run(['obsidian', 'vault=%s' % vault, 'move',
                    'path=%s' % src_rel, 'to=%s' % dst_rel],
                   capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir', required=True)
    ap.add_argument('--name', required=True, help='轮次名，如 首译 / 重译 / 校订')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--vault', default='wyz-obsidian-main')
    ap.add_argument('--apply', action='store_true', help='不传则只预演')
    args = ap.parse_args()

    root = vault_root(args.vault)
    book = os.path.abspath(args.book_dir)
    if not os.path.isdir(book):
        sys.exit('书目录不存在：%s' % book)
    if not book.startswith(root):
        sys.exit('书目录不在 vault 内：%s' % book)

    def rel(p):
        return os.path.relpath(p, root).replace('\\', '/')

    arch = os.path.join(book, '_归档', '%s_%s' % (args.date, args.name))
    if os.path.exists(arch):
        sys.exit('归档目标已存在，拒绝合并：%s' % arch)

    # 收集待搬条目
    moves = []   # (绝对源, 绝对目标, 是否目录)
    for item in ROUND_ITEMS:
        s = os.path.join(book, item)
        if os.path.isdir(s) and os.listdir(s):
            moves.append((s, os.path.join(arch, item), True))
    for fn in ROUND_FILES:
        s = os.path.join(book, fn)
        if os.path.isfile(s):
            moves.append((s, os.path.join(arch, fn), False))
    for fn in sorted(os.listdir(book)):
        if fn.endswith('.md') and any(p in fn for p in FINISH_PAT):
            moves.append((os.path.join(book, fn), os.path.join(arch, fn), False))

    if not moves:
        print('本轮区是空的，没有可归档的东西。')
        return 0

    print('轮次归档：%s → _归档/%s_%s/' % (os.path.basename(book), args.date, args.name))
    print('以下 %d 项将搬走（输入区的原件/source_en/figs/ocr 不动）：' % len(moves))
    for s, _d, isdir in moves:
        print('   %s%s' % (os.path.basename(s), '/' if isdir else ''))
    if not args.apply:
        print('\n（预演。加 --apply 执行。）')
        return 0

    # 建目标目录（目录创建走文件系统，不涉及链接）
    for _s, d, _isd in moves:
        os.makedirs(os.path.dirname(d), exist_ok=True)

    ok, fail = 0, []
    for s, d, isdir in moves:
        if isdir:
            # 目录逐文件搬（CLI 的 move 只管文件），保持相对结构
            for cur, _dirs, fns in os.walk(s):
                for fn in fns:
                    sp = os.path.join(cur, fn)
                    rel_in = os.path.relpath(sp, s)
                    dp = os.path.join(d, rel_in)
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    cli_move(args.vault, rel(sp), rel(dp))
                    if os.path.exists(dp):
                        ok += 1
                    else:
                        fail.append(rel(sp))
        else:
            cli_move(args.vault, rel(s), rel(d))
            if os.path.exists(d):
                ok += 1
            else:
                fail.append(rel(s))

    # 收尾：清空后的目录重建（下一轮的落点）
    for item in ROUND_ITEMS:
        os.makedirs(os.path.join(book, item), exist_ok=True)

    print('\n搬移 %d 个文件成功，%d 个失败' % (ok, len(fail)))
    for f in fail[:10]:
        print('   失败：%s' % f)
    print('归档位置：%s' % rel(arch))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
