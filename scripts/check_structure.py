#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_structure.py —— 双语结构件清点（源文 ↔ 译文），零成本发现整块漏译

为什么需要：`check_numbers.py` 只能发现数值类问题；语义/段落级漏译在数值上不可见。
而脚本类、话术类、习题类文本里有一批**语言无关的结构件**，译前译后应当接近 1:1：
占位符 `[PRODUCT]`→`［产品］`、舞台提示 `*Wait for response*`→`*等待回应*`、
`When to use`→`使用时机`、编号步骤、小节名（`SomethingScript` 这类驼峰名）。
逐项点数比一比，整块漏译就会露出来——实测某章曾整节漏掉一段话术
和两段异议话术，正是靠这套比对发现的（数字校验只顺带暴露了其中一句里的 `$1M`）。

用法：
    python check_structure.py --source <源.txt> --target <译.md> [--json]
    python check_structure.py --book-dir <书目录>       # 自动配对 source_en/*.txt 与 zh/*_重译版.md
退出码：发现疑似漏块 1，干净 0。
"""
import argparse, glob, json, os, re, sys

# 语言无关结构件：(名称, 源文正则, 译文正则, 是否作为门禁)
# 门禁只留三种**译法约定无关**的结构件：占位符、舞台提示、使用时机。
# 编号步骤/小节名受排版约定影响大（源文 1./2. 常被译成「第一、第二」或项目符号），
# 只报数不动用退出码，供人工一眼扫过——实测把它们当门禁会让 136 章里 18 章误报。
SIGNALS = [
    # 源文占位符一律是全大写英文（[PRODUCT]/[REP]）；译文可能写成［产品］或 [产品]，
    # 所以译文侧放宽为「任意方括号槽位」，只比槽位数量。
    ("占位符", r'\[[A-Z][A-Z0-9 _/\-]{2,24}\]', r'[\[［][^\]］\n]{1,24}[\]］]', True),
    # 舞台提示 = 源文 `*斜体*`。⚠️ **译文侧下限必须是 1，不能跟源文一样是 3**：
    # 英译中里一个英文词（`and`，3 字符）常只对应一个汉字（`并`），按 {3,45} 数就会
    # 把 `**并**` 漏掉 → 整章误报「漏译」（2026-10-07《某商业书》实测，
    # 抽查原文后确认译文完好，只是强调词短）。
    ("舞台提示", r'\*[^*\n]{3,45}\*', r'[＊*][^＊*\n]{1,45}[＊*]', True),
    ("使用时机", r'\bWhen to use\b', r'使用时机|何时使用|什么时候用', True),
    ("编号步骤", r'(?m)^\s*\d{1,2}[\.\)]\s', r'(?m)^\s*\d{1,2}[\.\)、）]\s', False),
    ("小节名", r'\b[A-Z][A-Za-z]*(?:Script|Scripts|Objections)\b', r'(?m)^#{1,4}\s', False),
]
# 只有源文里出现 ≥MIN_SRC 次、且译文覆盖 < RATIO 才报警，避免噪声
MIN_SRC, RATIO = 3, 0.7


def counts(text, pat):
    return len(re.findall(pat, text))


def sections(text):
    """源文小节名清单（驼峰脚本名 / 全大写标题行），供人工一眼核对。"""
    out = []
    for m in re.finditer(r'\b[A-Z][A-Za-z]*(?:Script|Scripts|Objections)\b', text):
        if m.group(0) not in out:
            out.append(m.group(0))
    for m in re.finditer(r'(?m)^([A-Z][A-Z0-9 ,\'\-/&:\.]{5,60})$', text):
        v = m.group(1).strip()
        if v not in out and not re.match(r'^(SCANME|ADDITIONALTRAININGS|DO\.THIS)$', v):
            out.append(v)
    return out


def check(source, target):
    issues, hints = [], []
    rows = []
    for name, ps, pt, gate in SIGNALS:
        a, b = counts(source, ps), counts(target, pt)
        miss = gate and a >= MIN_SRC and b < a * RATIO
        rows.append((name, a, b, miss))
        if miss:
            issues.append(dict(kind='结构件缺失', item=name,
                               expect='源文 %d 处，译文仅 %d 处' % (a, b),
                               note='整块漏译风险：请逐条核对源文对应小节'))
        elif not gate and a >= MIN_SRC and b < a * RATIO:
            hints.append(dict(kind='%s 计数差异（仅提示，排版约定不同也会如此）' % name,
                              source='源文 %d / 译文 %d' % (a, b), expect='—',
                              note='逐条扫一眼：源文有的条目译文是否都在'))
    # 小节名清单：只作提示（中英标题无法自动配对）
    secs = sections(source)
    if secs:
        hints.append(dict(kind='源文小节名清单（人工核对译文标题）', source=' / '.join(secs[:14]),
                          expect='—', note='译文标题应能一一对应'))
    return issues, hints, rows


def outline(source, target):
    """源文大纲：每个小节名 + 其后第一句，供审计逐条对到译文标题上。

    为什么这一步不能省：结构件计数只报「明显不对等」，**抓不到少了一整段话术**——
    实测整块漏译时，这类计数往往只差一处（未触发
    0.7 阈值），而按本大纲逐条点数一眼就能看出 8 个源文小节只对上了 6 个译文标题。
    """
    lines = []
    pats = [
        re.compile(r'\b[A-Z][A-Za-z]*(?:Script|Scripts|Objections)\b'),                  # CamelCase
        re.compile(r'\b[A-Z]{3,}[A-Z0-9]*(?:SCRIPT|SCRIPTS|OBJECTIONS)\b'),              # OCR 全大写
        re.compile(r'\b[A-Z][a-z]+ [A-Za-z]*(?:Script|Scripts|Objections)\b'),           # Stall Objections
        re.compile(r'(?m)^([A-Z][A-Za-z0-9 ,\'\-/&:\.]{3,50})$'),                        # 独立标题行
        re.compile(r'(?i)\bWhen to use\b'),
    ]
    seen = set()
    for pat in pats:
        for m in pat.finditer(source):
            name = (m.group(0) if m.re.groups == 0 else (m.group(1) or m.group(0))).strip()
            if re.match(r'^(When to use'
                        r'|Script|Scripts|Objections)$', name, re.I):
                continue
            if name.lower() in seen or len(name) < 5:
                continue
            seen.add(name.lower())
            tail = re.sub(r'\s+', ' ', source[m.end():m.end() + 70]).strip()
            lines.append((name, tail))
    return lines, [h.strip() for h in re.findall(r'(?m)^#{1,4}\s+(.*)$', target)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source')
    ap.add_argument('--target')
    ap.add_argument('--book-dir', help='书目录：自动配对 source_en/*.txt 与 zh/*_重译版.md')
    ap.add_argument('--outline', action='store_true', help='打印源文小节清单 + 译文标题，供逐条核对')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    pairs = []
    if args.book_dir:
        # 源文可能是 `.txt`（PDF/EPUB 提取）或 `.md`（MD 转换产物，如《某商业书》系列）；
        # 译文一律 `<zh>/<stem>.md`——**不带后缀**（轮次规则：顶层只放一份稿，上一轮移入 `_归档/`）。
        # 2026-10-07 修：此前只扫 `*.txt` 且硬编码 `_重译版.md`，对 Playbook 报「共 0 章」＝门禁失效。
        srcs = {}
        for ext in ('.md', '.txt'):
            for p in sorted(glob.glob(os.path.join(args.book_dir, 'source_en', '*' + ext))):
                srcs[os.path.splitext(os.path.basename(p))[0]] = p
        for stem, s in sorted(srcs.items()):
            t = os.path.join(args.book_dir, 'zh', stem + '.md')
            if os.path.exists(t):
                pairs.append((s, t))
    elif args.source and args.target:
        pairs.append((args.source, args.target))
    else:
        sys.exit('需要 --source/--target 或 --book-dir')

    bad, report = 0, {}
    for s, t in pairs:
        stext = open(s, encoding='utf-8').read()
        ttext = open(t, encoding='utf-8').read()
        iss, hints, rows = check(stext, ttext)
        name = os.path.basename(s)
        report[name] = dict(结构件=[dict(名称=n, 源=a, 译=b, 报警=m) for n, a, b, m in rows],
                            问题=iss, 提示=hints)
        if iss:
            bad += 1
            print('✗ %s' % name)
            print('   ' + '  '.join('%s %d/%d%s' % (n, a, b, '←' if m else '') for n, a, b, m in rows))
            for i in iss:
                print('   [%s] %s：%s；%s' % (i['kind'], i['item'], i['expect'], i['note']))
            for h in hints:
                print('   · %s：%s' % (h['kind'], h['source']))
        else:
            print('✓ %-28s 结构件齐 %s' % (name, '  '.join('%s %d/%d' % (n, a, b) for n, a, b, _ in rows)))
        if args.outline:
            secs, heads = outline(stext, ttext)
            print('   ── 源文小节清单（%d 条）→ 译文标题（%d 条），逐条核对有无遗漏：' % (len(secs), len(heads)))
            for i, (nm, tail) in enumerate(secs, 1):
                print('      %2d. %-34s | %s' % (i, nm[:34], tail[:60]))
            print('     译文标题：' + ' / '.join(h[:24] for h in heads))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    print('\n共 %d 章，疑似漏块 %d 章' % (len(pairs), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
