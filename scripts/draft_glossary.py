#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""draft_glossary.py —— 把「审校发现的问题」自动变成「术语库条目草稿」（零 token）

补的是闭环的最后一环（2026-10-07 立）：

    审校发现问题 → 自动起草术语库条目 → 使用者一次确认 → 回写术语库

为什么必须自动：术语库的价值全在「越用越厚」，但如果每本书都要使用者手动挑错、手动记表，
没人会做。所以把「起草」这一步自动化——脚本从《审校差错清单》里提取条目草稿，
使用者只需**删掉不同意的行**，剩下的用 `--promote` 一次回写。

分工（照「元规则进 skill、词条进术语库」）：
  - 脚本只管**起草与回写**（机械动作，零 token）
  - 「对不对」由使用者定（他的语感，脚本不替他判断）

用法：
    python draft_glossary.py --book-dir <书目录>                 # 起草 → 追加到 <术语体系>/_待确认.md
    python draft_glossary.py --promote --into business           # 把 _待确认.md 的条目回写进 business.md
选项：--terms-dir（默认 $MBX_TERMS_DIR）、--dry-run
退出码恒 0。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

from mbx_config import terms_dir

DEFAULT_TERMS = terms_dir()
PENDING = '_待确认.md'
SECTION_RE = re.compile(r'^#{2,4}\s*习语')
DRAFT_HEAD = '## 待确认草稿（由 draft_glossary.py 生成，确认后 --promote 回写）'


def clean(s, n=46):
    s = re.sub(r'\s+', ' ', (s or '')).strip().replace('|', '｜')
    return s[:n]


def load_errors(book_dir):
    p = os.path.join(book_dir, '_过程', '审校差错清单.json')
    if not os.path.exists(p):
        p = os.path.join(book_dir, '审校差错清单.json')      # 兼容旧结构
    if not os.path.exists(p):
        sys.exit('找不到《审校差错清单.json》：%s' % book_dir)
    return json.load(open(p, encoding='utf-8')), os.path.basename(book_dir.rstrip('\\/'))


def draft(book_dir, terms_dir):
    errs, book = load_errors(book_dir)
    if not errs:
        print('《审校差错清单》是空的，没有可起草的条目。')
        return 0
    pending = os.path.join(terms_dir, PENDING)
    done = set()
    if os.path.exists(pending):
        done = set(open(pending, encoding='utf-8').read().splitlines())
    rows, skipped = [], 0
    for e in errs:
        src = clean(e.get('source'), 40)
        tgt = clean(e.get('target'), 40)
        note = clean(e.get('note'), 56)
        cls = e.get('class', '?')
        ch = e.get('chapter', '')
        if not src and not tgt:
            continue
        row = '| %s | %s | %s %s | ⚠️ 待确认（%s 类）：%s |' % (src or '—', tgt or '—', book, ch, cls, note or '')
        if row in done:
            skipped += 1
            continue
        rows.append(row)
    new = not os.path.exists(pending)
    with open(pending, 'a', encoding='utf-8') as f:
        if new:
            f.write('# 待确认术语条目\n\n> 由 `draft_glossary.py` 从《审校差错清单》起草。\n'
                    '> **请删掉你不同意的行、修正中间的译法**，然后跑：\n'
                    '> `python draft_glossary.py --promote --into <作者或类型 slug>`\n\n')
        f.write(('' if new else '\n') + DRAFT_HEAD + '\n\n')
        f.write('| 原文片段 | 现译法 | 出处 | 备注 |\n|---|---|---|---|\n')
        f.write('\n'.join(rows) + '\n')
    print('从《%s》起草 %d 条（跳过已存在 %d 条）→ %s' % (book, len(rows), skipped, pending))
    print('请编辑该文件：删掉不同意的行、修正中间栏，然后 --promote 回写。')
    return 0


def promote(terms_dir, slug, dry):
    pending = os.path.join(terms_dir, PENDING)
    target = os.path.join(terms_dir, slug + '.md')
    if not os.path.exists(pending):
        sys.exit('没有待确认文件：%s' % pending)
    if not os.path.exists(target):
        sys.exit('目标档案不存在：%s' % target)
    rows = [ln for ln in open(pending, encoding='utf-8').read().splitlines()
            if ln.startswith('|') and '---' not in ln and '原文片段' not in ln]
    if not rows:
        print('待确认文件里没有条目。')
        return 0
    txt = open(target, encoding='utf-8').read()
    lines = txt.splitlines()
    # 找到「习语与句式」小节的表尾；没有就追加小节
    idx = next((i for i, l in enumerate(lines) if SECTION_RE.match(l)), None)
    if idx is None:
        add = ['', '## 习语与句式', '', '| 英文习语／句式 | 中文现成说法 | 出处 | 备注 |', '|---|---|---|---|'] + rows
        out = lines + add
    else:
        j = idx + 1
        while j < len(lines) and not lines[j].startswith('#'):
            j += 1
        while j > idx and not lines[j - 1].strip():
            j -= 1
        out = lines[:j] + rows + lines[j:]
    if dry:
        print('[dry-run] 将 %d 条写入 %s，示例：\n  %s' % (len(rows), target, rows[0][:90]))
        return 0
    shutil.copyfile(target, target + '.bak')
    open(target, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    shutil.move(pending, pending + '.已回写_' + datetime.date.today().isoformat())
    print('已把 %d 条回写进 %s（备份 %s.bak，待确认文件已改名归档）' % (len(rows), target, target))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--promote', action='store_true')
    ap.add_argument('--into', help='回写目标：作者或类型 slug（不带 .md）')
    ap.add_argument('--terms-dir', default=DEFAULT_TERMS)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if args.promote:
        if not args.into:
            sys.exit('--promote 需要 --into <slug>')
        return promote(args.terms_dir, args.into, args.dry_run)
    if not args.book_dir:
        sys.exit('需要 --book-dir，或 --promote --into <slug>')
    return draft(args.book_dir, args.terms_dir)


if __name__ == '__main__':
    sys.exit(main())
