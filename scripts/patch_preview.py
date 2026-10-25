#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_preview.py —— 批量改稿的机械闸门（**先改一段、验证、再批量**）

为什么必须有这个脚本（2026-10-07，代价：整章 219 处标记被改坏）：
    规则早就写在 SKILL.md 里——「样本确认是唯一能挡住按一条错误规则改坏全书的闸门」——
    但**规则写了没有机器卡住，就等于没写**。当天 AI 自己发现一个问题，直接跑了一把全量正则，
    那把正则把已配对的 `**粗体**` 一起吃成了 `***粗体***`；**中文行文毫无异常**，
    `check_fluency` / `check_numbers` / `check_paragraph_map` 全绿，只有符号烂了。
    所以：**批量替换不再允许「手工跑脚本」，一律走这里。**

三步对应：
    第 1 步「先改一段」 → 不带 `--apply`，只看命中清单 + 样本「改前 / 改后」
    第 2 步「抽段验证」 → 带 `--sample-lines 345,388` 单独看指定行的效果
    第 3 步「验证通过才批量」 → 带 `--apply`，且必须带 `--expect <数>` 对齐命中数

安全网（`--apply` 时自动执行，任一失败即**回滚**）：
    · 命中数必须等于 `--expect`（数对不上＝正则没匹配到你以为的位置，拒绝落盘）
    · 落盘前每个文件备份为 `<文件>.bak`
    · 落盘后自动跑 `check_markup.py`，标记变脏 → 回滚
    · 书目录下有 `source_en/` 时，同时跑 `check_paragraph_map.py`，段落边界被破坏 → 回滚

用法：
    # 只看（DRY-RUN）
    python patch_preview.py --book-dir <书目录> --find '\\*([^*\\n]{1,60})\\*' --replace '**\\1**' -n 3
    # 只看指定行
    python patch_preview.py --book-dir <书目录> --find 'A' --replace 'B' --sample-lines 345,388
    # 落盘（必须给出期望命中数）
    python patch_preview.py --book-dir <书目录> --find 'A' --replace 'B' --expect 219 --apply
选项：--suffix（只改 `*<suffix>.md`）、--dir（默认 `<book-dir>/zh`）、--json
退出码：DRY-RUN 恒 0；`--apply` 成功 0，被拦下/回滚 1。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _run_checker(name, book_dir):
    """跑同目录下的校验器，返回 (ok, 输出)。找不到脚本即视为通过。"""
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return True, '(缺 %s，跳过)' % name
    p = subprocess.run([sys.executable, path, '--book-dir', book_dir],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode == 0, (p.stdout or '') + (p.stderr or '')


# 每个校验器「坏掉多少」的口径（用于改前改后对比）。
# 关键设计：**闸门只拦「这次改坏了」，不拦「本来就坏」**——
# 书可能带着既存问题（如段落边界本来就差几段），若按「退出码非 0 即回滚」，
# 任何一次改动都会被既存问题挡住，闸门就废了。所以比的是「改前 vs 改后」的坏点数。
_BAD_COUNT = {
    'check_markup.py': re.compile(r'有问题\s*(\d+)\s*个'),
    'check_paragraph_map.py': re.compile(r'段落边界被改动\s*(\d+)\s*处'),
}


def _bad_count(name, out):
    pat = _BAD_COUNT.get(name)
    if not pat:
        return 0
    m = pat.search(out)
    return int(m.group(1)) if m else 0


def collect(files, pat, repl):
    """返回 {file: [(lineno, 改前, 改后, 本行命中数)]}"""
    hits = {}
    for fp in files:
        rows = []
        for i, ln in enumerate(open(fp, encoding='utf-8').read().splitlines(), 1):
            n = len(pat.findall(ln))
            if n:
                rows.append((i, ln, pat.sub(repl, ln), n))
        if rows:
            hits[fp] = rows
    return hits


def first_diff(a, b):
    """第一处差异的位置；完全相同则返回 0。"""
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), 0)


def window(s, k, width=80):
    """以 k 为中心截一段，两端加省略号。"""
    a = max(0, k - width // 2)
    seg = s[a:k + width // 2 + 40]
    return ('…' if a else '') + seg + ('…' if a + len(seg) < len(s) else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir', default=None, help='书目录（用 --target 时可省）')
    ap.add_argument('--target', default=None, help='只改这一个文件（修已生成的成品时用）')
    ap.add_argument('--dir', default=None, help='默认 <book-dir>/zh')
    ap.add_argument('--suffix', default='')
    ap.add_argument('--find', default=None, help='正则（Python re 语法）')
    ap.add_argument('--replace', default=None, help=r'替换串，可用 \1 反向引用')
    ap.add_argument('--script', default=None,
                    help='提供 transform(line)->line 的 .py（替代 --find/--replace；'
                         '用于多步转换，如「保护已配对的 ** 再改单星斜体」）')
    ap.add_argument('-n', type=int, default=3, help='打印几处样本（默认 3）')
    ap.add_argument('--sample-lines', default='', help='只细看指定行，如 345,388（逗号分隔）')
    ap.add_argument('--expect', type=int, default=None, help='期望命中总数（--apply 时必填）')
    ap.add_argument('--apply', action='store_true', help='真正落盘（不加以外一律 DRY-RUN）')
    ap.add_argument('--keep-bak', action='store_true', help='成功也保留 *.bak（默认成功后清理）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.target:
        d = os.path.dirname(os.path.abspath(a.target))
        files = [a.target]
        if not os.path.exists(a.target):
            sys.exit('文件不存在：%s' % a.target)
    else:
        if not a.book_dir:
            sys.exit('需要 --book-dir 或 --target')
        d = a.dir or os.path.join(a.book_dir, 'zh')
        if not os.path.isdir(d):
            sys.exit('目录不存在：%s' % d)
        files = [f for f in sorted(glob.glob(os.path.join(d, '*.md')))
                 if a.suffix in os.path.basename(f)]
        if not files:
            sys.exit('没找到 .md（目录 %s，后缀过滤 %r）' % (d, a.suffix))

    transform = None
    if a.script:
        import importlib.util
        spec = importlib.util.spec_from_file_location('patch_transform', a.script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, 'transform'):
            sys.exit('--script 里没有 transform(line)->line 函数：%s' % a.script)
        transform = mod.transform
        if a.find or a.replace:
            sys.exit('--script 与 --find/--replace 不能同时用')
    elif not (a.find and a.replace is not None):
        sys.exit('需要 --find + --replace，或 --script')

    if transform is not None:
        def _apply(ln):
            return transform(ln)
        pat_desc = '脚本 %s' % os.path.basename(a.script)
    else:
        try:
            pat = re.compile(a.find)
        except re.error as e:
            sys.exit('--find 正则不合法：%s' % e)
        def _apply(ln):
            return pat.sub(a.replace, ln)
        pat_desc = a.find

    def collect2(fs):
        out = {}
        for fp in fs:
            rows = []
            for i, ln in enumerate(open(fp, encoding='utf-8').read().splitlines(), 1):
                new = _apply(ln)
                if new != ln:
                    rows.append((i, ln, new, 1))
            if rows:
                out[fp] = rows
        return out

    hits = collect2(files)
    total = sum(len(v) for v in hits.values())
    nchar = sum(n for v in hits.values() for _, _, _, n in v)

    print('=' * 68)
    print('模式：%s' % ('APPLY（真正落盘）' if a.apply else 'DRY-RUN（只看不写）'))
    print('规则：%s' % pat_desc)
    if a.replace is not None:
        print('替换：%s' % a.replace)
    print('目录：%s ｜ 文件 %d 个' % (d, len(files)))
    print('=' * 68)
    if not total:
        print('✗ 全书 0 命中——正则没匹配到任何东西，检查写法或 --suffix')
        return 1 if a.apply else 0
    print('命中：%d 行 / %d 处，分布于 %d 个文件' % (total, nchar, len(hits)))
    for fp, rows in hits.items():
        print('   %-38s %d 行' % (os.path.basename(fp), len(rows)))

    want = {int(x) for x in a.sample_lines.split(',') if x.strip()}
    shown = 0
    print('\n样本「改前 / 改后」：')
    for fp, rows in hits.items():
        for ln_no, before, after, n in rows:
            if want and ln_no not in want:
                continue
            if not want and shown >= a.n:
                break
            shown += 1
            k = first_diff(before, after)
            print('\n  [%d] %s:%d' % (shown, os.path.basename(fp), ln_no))
            print('    - %s' % window(before, k))
            print('    + %s' % window(after, k))
        if not want and shown >= a.n:
            break
    if shown == 0:
        print('   （--sample-lines 指定的行没有命中）')

    # 幂等自检：同一处样本再跑一次若还会变，说明替换不是幂等的——
    # 转义类替换（`#` → `\#`）最典型：正则若不排除已转义的，二次运行会把 `\#` 变成 `\\#`。
    sample = [ln for rows in hits.values() for _, ln, _, _ in rows][:30]
    twice = sum(1 for ln in sample
                if _apply(_apply(ln)) != _apply(ln))
    if twice:
        print('\n⚠ 非幂等：%d/%d 处样本再跑一次还会变。若是转义类替换，'
              '正则要加 `(?<!\\\\)` 排除已转义的，否则二次运行会重复转义。' % (twice, len(sample)))

    if not a.apply:
        print('\nDRY-RUN 结束，未写任何文件。确认样本无误后，加 --expect %d --apply 落盘。' % nchar)
        if a.json:
            print(json.dumps({os.path.basename(k): [r[0] for r in v] for k, v in hits.items()},
                             ensure_ascii=False, indent=1))
        return 0

    # ---------------- 落盘 ----------------
    if a.expect is None:
        print('\n✗ --apply 必须同时给 --expect <命中处数>（本次实测 %d）。拒绝落盘。' % nchar)
        return 1
    if a.expect != nchar:
        print('\n✗ 命中数与 --expect 不一致（实测 %d，期望 %d）——'
              '说明正则匹配到的位置和你想的不一样。拒绝落盘。' % (nchar, a.expect))
        return 1

    # 改前基线（只拦「这次改坏了」，不拦既存问题）
    checks = [('check_markup.py', 'Markdown 标记')]
    if a.book_dir and os.path.isdir(os.path.join(a.book_dir, 'source_en')):
        checks.append(('check_paragraph_map.py', '段落边界'))
    check_dir = a.book_dir or d
    before = {}
    for name, label in checks:
        _, out = _run_checker(name, check_dir)
        before[name] = _bad_count(name, out)

    originals = {fp: open(fp, encoding='utf-8').read() for fp in hits}
    for fp, rows in hits.items():
        shutil.copy2(fp, fp + '.bak')
        src = originals[fp]
        # **必须逐行替换**：`collect()` 是按行计数、按行看样本的，
        # 若这里改成对整篇文本一次 sub，带 `^`/`$` 的模式在整篇上（无 re.MULTILINE）
        # 只会匹配首尾——结果就是「按行报 N 处命中、实际一处都没替换」，而 --expect 还照样通过。
        # 2026-10-07 实测踩过（`^\s*\*[\s*]*$` 转分隔符，报 6 处、0 处生效）。
        new = '\n'.join(_apply(ln) for ln in src.split('\n'))
        open(fp, 'w', encoding='utf-8').write(new)
    print('\n已落盘 %d 个文件（备份 `*.bak`）。跑校验器（对比改前基线）…' % len(hits))

    failed = False
    for name, label in checks:
        _, out = _run_checker(name, check_dir)
        after = _bad_count(name, out)
        gained = after - before[name]
        mark = '✓' if gained <= 0 else '✗'
        print('   %s %s：改前 %d → 改后 %d%s'
              % (mark, label, before[name], after,
                 '' if gained <= 0 else '（本次新增 %d）' % gained))
        if gained > 0:
            failed = True
            print(out.strip()[:1200])
    if failed:
        for fp, txt in originals.items():
            open(fp, 'w', encoding='utf-8').write(txt)
        print('\n✗ 本次改动让校验变差 → **已回滚**全部文件（`*.bak` 保留）。')
        return 1
    print('\n✓ 落盘成功，未让任何校验变差。')
    if not a.keep_bak:
        for fp in hits:
            if os.path.exists(fp + '.bak'):
                os.remove(fp + '.bak')
        print('已清理备份（要留备份用 --keep-bak）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
