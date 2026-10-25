#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_unit_residue.py —— 英文单位／缩写残渣检测（正则，零 token）

为什么需要：实测译文里出现过 `$1,000/wk` 这种「数字留了半角、单位却仍是英文缩写」
的残渣。它对中文读者是纯噪声，且**整段其余部分都通顺**——属点缺陷，段落级指标
（`check_fluency.py`）抓不到，只能靠正则。

两类形态：
  ① 斜杠单位：`/wk`、`/mo`、`/yr`、`/ea`、`/hr` 等（URL 与图片路径排除）；
  ② 量级后缀：`3.5B`、`1.2M`、`120K`——**紧跟英文单词的不算**（排除书名
     `100M 商业书` 这类专名写法），只抓「量级词后面接非英文字母」的真残渣。

用法：
    python check_unit_residue.py --book-dir <书目录>
    python check_unit_residue.py --dir <书目录> --suffix _重译版
    python check_unit_residue.py --target <译.md>
选项：--allow "SLA,POC"（允许保留的 token，逗号分隔）、--json
退出码：有命中 1，干净 0。
"""
import argparse
import json
import os
import re
import sys

# ① 斜杠单位（排除路径/URL：只挡「字母、斜杠、点」在前的形态）
#    注意不能把数字也挡掉——`$1,000/wk` 的 `/` 前面正是数字 0，
#    早期写成 `(?<![\w/.])` 会把这一类**全部漏掉**（实测漏掉 `$1,000/wk`）。
SLASH_UNIT = re.compile(
    r'(?<![A-Za-z/.])(?:/(?:wk|wks|mo|mos|yr|yrs|hr|hrs|min|mins|ea|day|days|'
    r'week|weeks|month|months|year|years|pcs|unit|units|user|users|'
    r'person|head|seat|show|lead|leads|order|orders|install|client|customer))\b',
    re.I)
# ② 量级后缀（后面不能紧跟英文字母——把 100M 商业书 这类专名放过去）
SCALE = re.compile(r'(?<![A-Za-z]-)\b\d+(?:\.\d+)?\s?(?:bn|mn|B|M|K)(?![A-Za-z])')
# ③ 英文 per 短语
PER = re.compile(r'\bper\s+(?:week|month|year|day|hour|user|customer|unit|show|lead|order)\b', re.I)

# 排除：URL、图片/文件路径、行内代码
URL_OR_PATH = re.compile(r'https?://\S+|!\[[^\]]*\]\([^)]*\)|\S*\bfigs/\S+|\b[\w\-]+\.(?:png|jpe?g|gif|webp|svg|md|json)\b')
SCALE_HINT = {'b': '亿（十亿）', 'bn': '亿（十亿）', 'm': '百万／万', 'mn': '百万／万', 'k': '千'}

# 默认豁免：术语库规定「系列书名一律保留英文原名」，`100M 商业书` 这类写法里的 100M
# 是**书名的一部分、不是待本地化的量级**，按残渣报是假阳性。用 --allow 可增删。
DEFAULT_ALLOW = {'100m'}


def scan_line(line, allow):
    hits = []
    masked = URL_OR_PATH.sub(lambda m: ' ' * len(m.group(0)), line)
    for pat, kind in ((SLASH_UNIT, '斜杠单位'), (SCALE, '量级后缀'), (PER, '英文 per 短语')):
        for m in pat.finditer(masked):
            tok = m.group(0).strip()
            if tok.lower() in allow:
                continue
            hint = ''
            if kind == '量级后缀':
                unit = tok[-1] if not tok[-2:-1].isalpha() else tok[-2:]
                hint = ' → 建议写成中文量级（%s）' % SCALE_HINT.get(unit.lower(), '万／亿')
            hits.append((kind, tok, hint))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--dir')
    ap.add_argument('--target')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--allow', default='', help='允许保留的 token，逗号分隔（如 SLA,POC）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    allow = set(DEFAULT_ALLOW) | {t.strip().lower() for t in args.allow.split(',') if t.strip()}

    files = []
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
        lines = open(fp, encoding='utf-8').read().splitlines()
        found = []
        for i, ln in enumerate(lines, 1):
            if ln.lstrip().startswith(('```', '![', '~~~')):
                continue
            for kind, tok, hint in scan_line(ln, allow):
                found.append(dict(line=i, kind=kind, token=tok,
                                  snippet=ln.strip()[:70]))
        report[os.path.basename(fp)] = found
        if found:
            bad += 1
            print('✗ %s（%d 处）' % (os.path.basename(fp), len(found)))
            for h in found[:12]:
                print('   行 %-4d [%s] %s%s' % (h['line'], h['kind'], h['token'],
                                                ('  ' + h['snippet'])))
        else:
            print('✓ %s 无英文单位残渣' % os.path.basename(fp))
    print('\n文件 %d 个，有残渣 %d 个' % (len(files), bad))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
