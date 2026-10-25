#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_idiom.py —— 习语直译检测（查表，零 token）

为什么需要：实测证明「翻译腔」里最刺眼的一类是**习语被字面直译**——
`race to the bottom` 该用现成的「逐底竞赛」，却被译成「向下比烂的比赛」。
这类错误是**点缺陷**：整段中文都通顺，就一个词不对，所以按段落密度排序的
`check_fluency.py` 抓不到它（实测 0/5 命中）。它只能靠**查表**抓。

表从哪来：`<术语体系>/` 下各档案的「习语与句式」表（作者库/类型库）。
元规则在 `references/翻译规范.md` 第七节（禁止自造解释性译法），词条由使用者
逐本翻译时累积——本脚本只做匹配，不做判断。

查法：源文出现该英文习语 → 译文里必须出现表中给出的中文现成说法之一；
没有则报警（可能是直译，也可能译者用了别的现成说法，人工 3 秒定性）。

用法：
    python check_idiom.py --book-dir <书目录>            # 用 <书目录>/source_en ↔ /zh
    python check_idiom.py --dir <书目录> --suffix _重译版
    python check_idiom.py --source a.txt --target b.md
选项：--terms-dir <术语体系目录>（默认 <书>/../_术语体系 → $MBX_TERMS_DIR → ./_术语体系）、--json
退出码：有未匹配 1，全通过 0。
"""
import argparse
import json
import os
import re
import sys

from mbx_config import terms_dir
# 整节都算「习语表」：`## 习语与句式`、`### 习语种子表` 一类标题都要进（实测漏过 44 条种子）
SECTION = re.compile(r'^#{2,4}\s*习语')
# 备注里的已知错译写法（出现即报，属点缺陷里最好抓的一类）
BAD_LITERAL = re.compile(r'不写「([^」]+)」|不要写「([^」]+)」|不译「([^」]+)」')


def load_idioms(terms_dir):
    """从 <术语体系>/*.md 的「习语与句式」表里取条目。

    返回 [(英文习语, [中文现成说法…], 出处, 备注)]。表格式：
        | english | 中文 | 出处 | 备注 |
    中文列用 `/`、`／`、`、` 分隔多个可接受说法，任一命中即通过。
    """
    idioms = []
    if not os.path.isdir(terms_dir):
        return idioms
    for fn in sorted(os.listdir(terms_dir)):
        if not fn.endswith('.md'):
            continue
        in_sec = False
        for line in open(os.path.join(terms_dir, fn), encoding='utf-8'):
            s = line.strip()
            if s.startswith('#'):
                in_sec = bool(SECTION.match(s))
                continue
            if not in_sec or not s.startswith('|'):
                continue
            cells = [c.strip() for c in s.strip('|').split('|')]
            if len(cells) < 2:
                continue
            en, zh = cells[0], cells[1]
            if set(en) <= set('-: ') or en.startswith('英文') or not en or not zh:
                continue
            alts = [a.strip() for a in re.split(r'[/／、]', zh) if a.strip()]
            note = cells[3] if len(cells) > 3 else ''
            # 备注里写「不写「X」」的，X 是**已知错译**——出现即报，不依赖源文是否命中
            bads = [g for m in BAD_LITERAL.finditer(note) for g in m.groups() if g]
            idioms.append((en, alts, cells[2] if len(cells) > 2 else '', note, bads))
    return idioms


def pair_files(args):
    if args.source and args.target:
        return [(args.source, args.target)]
    d = args.dir
    if args.book_dir:
        d = args.book_dir
    if not d or not os.path.isdir(d):
        sys.exit('需要 --book-dir / --dir / --file 之一，且目录存在')
    src_dir, tgt_dir = os.path.join(d, 'source_en'), os.path.join(d, 'zh')
    if not os.path.isdir(src_dir) or not os.path.isdir(tgt_dir):
        sys.exit('目录下需同时有 source_en/ 与 zh/')
    pairs = []
    for fn in sorted(os.listdir(src_dir)):
        # 源文可能是 .txt（PDF/EPUB 提取）或 .md（MD 转换产物，如《某商业书》系列）
        if not fn.endswith(('.txt', '.md')):
            continue
        stem = os.path.splitext(fn)[0]
        cands = [f for f in sorted(os.listdir(tgt_dir))
                 if f.endswith('.md') and f[:-3].replace(args.suffix, '') == stem]
        if cands:
            pairs.append((os.path.join(src_dir, fn), os.path.join(tgt_dir, cands[0])))
    return pairs


def check_pair(src_text, tgt_text, idioms):
    low = src_text.lower()
    hits = []
    for en, alts, srcbook, note, bads in idioms:
        # ① 已知错译直接出现 → 报（与源文是否命中无关）
        shown = [b for b in bads if b in tgt_text]
        if shown:
            hits.append(dict(idiom=en, expect='／'.join(alts), source=srcbook, note=note,
                             bad='、'.join(shown)))
            continue
        # ② 源文命中该习语、译文却没出现任何规定说法 → 报
        if en.lower() not in low:
            continue
        if any(a in tgt_text for a in alts):
            continue
        hits.append(dict(idiom=en, expect='／'.join(alts), source=srcbook, note=note, bad=''))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--dir')
    ap.add_argument('--source')
    ap.add_argument('--target')
    ap.add_argument('--suffix', default='', help='译稿文件名后缀，如 _重译版')
    ap.add_argument('--terms-dir', default=None,
                    help='术语体系目录；默认先找 <book-dir> 的上一级 `_术语体系`，'
                         '再退到相对路径 %s' % terms_dir())
    ap.add_argument('--include-maybe', action='store_true',
                    help='同时报「待查」档（源文有该习语、译文未见规定说法）——召回高但噪声大，默认关闭')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    # 术语库路径解析（2026-10-07 修）：原来只用相对路径 `Library/书籍翻译/_术语体系`，
    # **从非 vault 根目录跑就静默找不到表**，却只打印「习语表为空」——看着像「本来就没有习语」。
    # 现在优先按书目录上溯（`<book-dir>/../_术语体系`）。
    if not args.terms_dir:
        cand = []
        d = args.book_dir or args.dir
        if d:
            cand.append(os.path.join(os.path.dirname(os.path.abspath(d)), '_术语体系'))
        cand.append(terms_dir())
        args.terms_dir = next((c for c in cand if os.path.isdir(c)), cand[-1])

    idioms = load_idioms(args.terms_dir)
    if not idioms:
        print('习语表为空（%s 下未找到「习语与句式」表）——本脚本无内容可查。' % args.terms_dir)
        print('元规则与表位见 references/翻译规范.md 第七节、references/authors/_模板.md。')
        return 0

    pairs = pair_files(args)
    report, bad = {}, 0
    for src, tgt in pairs:
        hits = check_pair(open(src, encoding='utf-8').read(),
                          open(tgt, encoding='utf-8').read(), idioms)
        # 默认只报「错译」档（高置信）；「待查」档实测噪声极大（某条习语 45 次命中 0 次为真），
        # 需显式 --include-maybe 才开——它的判据「译文没出现规定说法」对合法同义译法一律误报。
        if not args.include_maybe:
            hits = [h for h in hits if h.get('bad')]
        name = os.path.basename(tgt)
        report[name] = hits
        if hits:
            bad += 1
            print('✗ %s' % name)
            for h in hits:
                if h.get('bad'):
                    print('   [错译] %s → 译文写成「%s」，应为「%s」'
                          % (h['idiom'], h['bad'], h['expect']))
                else:
                    print('   [待查] %s → 规定说法「%s」未出现；**可能是合法同义译法，也可能是直译**'
                          % (h['idiom'], h['expect']))
        else:
            print('✓ %s 习语核对通过' % name)
    print('\n习语表 %d 条，文件 %d 个，[错译] 命中 %d 个%s'
          % (len(idioms), len(pairs), bad,
             '' if args.include_maybe else '（「待查」档默认关闭；加 --include-maybe 一并看）'))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
