#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_paragraph_map.py —— 段落边界门禁（零 token，任何模式交付前必跑）

为什么需要（2026-10-05 实测教训）：
    一份人工校验过的规整字幕（成色Ⅰ档）被按书籍规范处理——译文成形后用脚本并段。
    `check_numbers.py` 只管数值、`check_structure.py` 只点结构件、`qa_report.py` 六类里
    没有「段落被合并」这一类，`rewrap_source_lines.py` 的字符级零改写校验也放行
    （并段只改空白，字符序列与词序列都不变）。结果是 error_rate 0‰、四个脚本全绿，
    用户读不懂，整本返工。
    「一段对一段，不并不拆」原本就写在 SKILL.md 里——**只有规则、没有门禁**。
    本脚本就是这条规则的门禁。

检查项：
    1. 段数守恒（硬门禁，跨语言可判）：源文空行分段数 == 译文空行分段数
    2. 段末标点形态对应（跨语言可判）：源段以句末标点结尾 → 译段也应以句末标点结尾；
       源段是半句（无句末标点）→ 译段也应是半句。形态不一致率过高 = 段落边界被挪动
    3. 每段首尾字（仅 --same-lang，即模式 C 纯格式转 MD 这类同语言场景）

退出码：0 = 全部通过；1 = 有段数不一致 / 译文缺文件 / 首尾字不符 / 译文含页码等源文元数据

用法：
    python check_paragraph_map.py --book-dir <书目录>              # 配 source_en/*.txt ↔ zh/*.md
    python check_paragraph_map.py --book-dir <书目录> --zh-dir zh_line
    python check_paragraph_map.py --book-dir <书目录> --suffix _重译版
    python check_paragraph_map.py --source a.txt --target a.md
    python check_paragraph_map.py --book-dir <书目录> --show       # 打印首个不一致的段落对照
"""
import argparse, glob, json, os, re, sys

CJK = re.compile(r"[\u4e00-\u9fff]")
# 句末标点（含中英与常见收尾引号/括号）
END_PUNCT = re.compile(r'[.!?。！？…][”"\'’」』）)\]*_]*$')
# 需要从段落里剥掉的装饰：段首全角/半角缩进、markdown 标记、完成标记
STRIP_HEAD = re.compile(r'^(?:[　\s]+|[>#\-*]+\s*)+')
DONE_MARK = re.compile(r'<!--\s*本章翻译完成\s*-->')


def parse_tolerance(value):
    """--tolerance：整数（绝对段数）或百分比（如 15%）。0.25 这类小数直接报错。"""
    s = value.strip()
    if re.fullmatch(r'\d+', s):
        return int(s)
    if re.fullmatch(r'\d+(?:\.\d+)?%', s):
        return s
    raise argparse.ArgumentTypeError(
        '只接受整数或百分比（如 15%%），不接受 %r' % value)


# 纯元数据块：页码标记、图片页标记、单独的图片行
META_BLOCK = re.compile(
    r'^\s*\[(?:PDF 第|图片页|图片)|^\s*!\[[^\]]*\]\([^)]*\)\s*$'
    # 整行方括号包裹的图片描述（**源文侧**形态，如 `[The image shows …]`、`[QR code labeled "SCAN ME"]`）：
    # 译文侧写成全角 `［插图：…］`，行末无句末标点 → 被规则③排除；源文行末却是半角 `]`，
    # 恰在 END_PUNCT 里 → 被判成正文段。两侧尺子不同，单文件能差 6 段（2026-10-07 实测 GOATed Ads）。
    r'|^\s*\[[^\]]{12,}\]\s*$')
# 标签/小标题的形态判据：**不以句末标点收尾**（2026-10-07 改：原先还要求「短」，
# 实测长标签会漏网——如 `The Win Your Money Back Offer Has A Simple Structure With Lots Of
# Flexibility And Options`（书里是节标题，>60 字）在源文侧被当成正文段、在译文侧成了 `##` 被排除，
# 于是每章凭空少几段。去掉长度限制后，中位差从 4 降到 1、±1 内从 10/32 升到 18/32。
# 需要恢复长度限制（源文含大量「半句」断块时）用 `--label-max N`（0 = 不限长）。
# 为什么不只靠 `#`：源文常是**提取后丢了标题标记**的文本（实测《某商业书》里
# `Make a Magnetic "Reason Why"`、`Pro Tip: …`、`Author Note: …` 在书里本是标题，
# 提取后成了普通行），译文把它还原成 `##`/`###` 是对的；若只在译文侧排除 `#` 块，
# 就成了两边两把尺子，必然误报（实测 21/22 章标红）。
LABEL_MAX = 0          # 0 = 不限长（默认）
# 译文里绝不应出现的源文元数据：页码/图片页/插图标记。
# 反作弊：2026-10-24 回归发现，修复者可以往译文里补 `[PDF 第 X 页]` 让段数“对齐”，
# 这不是翻译，是把源文标记搬进成品。单独检查，不参与段落切分。
TARGET_META = re.compile(r'\[PDF 第|\[图片页|\[插图')


def paragraphs(text, skip_heading=False, strict=False):
    """按空行切段，去掉完成标记与装饰性前缀。

    strict=False（默认）：**两边同一把尺子**——只比「正文段」。
      排除：① `#` 开头的块（译文侧的标题）；② 页码/图片页标记与纯图片块；
            ③ 短且无句末标点的块（源文侧丢了标记的标题/标签）。
    strict=True：只排除 `#` 块（旧口径，保留以备对照）。
    """
    text = DONE_MARK.sub("", text)
    raw = [b for b in re.split(r'\n\s*\n', text) if b.strip()]
    out = []
    for i, b in enumerate(raw):
        b = b.strip()
        if skip_heading and i == 0 and b.startswith('#'):
            continue
        if b.startswith('#'):              # 标题（译文侧）
            continue
        if not strict:
            if META_BLOCK.match(b):        # 页码/图片页标记、纯图片行
                continue
            if (LABEL_MAX <= 0 or len(b) < LABEL_MAX) and not END_PUNCT.search(b):
                continue                   # 短且无句末标点 = 标签/小标题
        out.append(STRIP_HEAD.sub('', b).strip())
    return [p for p in out if p]


def norm_chars(s, n=6):
    s = re.sub(r'\s+', '', s)
    return (s[:n], s[-n:])


def compare(src_text, tgt_text, same_lang=False, show=False, strict=False, tolerance=0):
    sp = paragraphs(src_text, strict=strict)
    tp = paragraphs(tgt_text, skip_heading=True, strict=strict)
    diff = len(tp) - len(sp)
    limit = tolerance
    if isinstance(limit, str) and limit.strip().endswith('%'):
        limit = -(-len(sp) * int(float(limit.strip()[:-1]) * 100) // 10000)   # 向上取整
    limit = int(limit or 0)
    res = {"src_paras": len(sp), "tgt_paras": len(tp), "diff": diff, "limit": limit,
           "count_ok": abs(diff) <= limit,
           "end_punct_mismatch": 0, "head_tail_mismatch": 0,
           "target_meta": len(TARGET_META.findall(tgt_text)), "detail": None}
    if len(sp) == len(tp):
        for a, b in zip(sp, tp):
            if bool(END_PUNCT.search(a)) != bool(END_PUNCT.search(b)):
                res["end_punct_mismatch"] += 1
        if same_lang:
            for a, b in zip(sp, tp):
                if norm_chars(a) != norm_chars(b):
                    res["head_tail_mismatch"] += 1
        if show:
            for i, (a, b) in enumerate(zip(sp, tp), 1):
                if bool(END_PUNCT.search(a)) != bool(END_PUNCT.search(b)):
                    res["detail"] = {"index": i, "src": a[:90], "tgt": b[:90],
                                     "why": "源段%s句末标点，译段%s" % (
                                         "" if END_PUNCT.search(a) else "无",
                                         "" if END_PUNCT.search(b) else "无")}
                    break
    else:
        if show:
            lo = min(len(sp), len(tp))
            res["detail"] = {"index": lo + 1,
                             "src": (sp[lo][:90] if lo < len(sp) else "（源文已结束）"),
                             "tgt": (tp[lo][:90] if lo < len(tp) else "（译文已结束）"),
                             "why": "段数差 %d" % (len(tp) - len(sp))}
    return res


def _list_sources(src_dir):
    """源文既可能是 `.txt`（PDF/EPUB 提取产物）也可能是 `.md`（MD 转换产物，
    如《某商业书》系列）。同名时 `.txt` 优先（历史语料都是 .txt）。
    2026-10-07 补：此前硬编码只扫 `*.txt`，对 `.md` 源文直接报「没找到可配对的源文/译文」，
    段落门禁形同不存在。"""
    seen = {}
    for ext in (".md", ".txt"):
        for p in sorted(glob.glob(os.path.join(src_dir, "*" + ext))):
            seen[os.path.splitext(os.path.basename(p))[0]] = p
    return [(k, seen[k]) for k in sorted(seen)]


def resolve_pairs(args):
    if args.source and args.target:
        return [(os.path.basename(args.source), args.source, args.target)]
    if args.pair_dir:
        out = []
        for s in sorted(glob.glob(os.path.join(args.pair_dir, "*.txt"))):
            t = os.path.join(args.pair_dir, os.path.splitext(os.path.basename(s))[0] + ".md")
            out.append((os.path.basename(s), s, t))
        return out
    if args.book_dir:
        zh_dir = os.path.join(args.book_dir, args.zh_dir or "zh")
        src_dir = os.path.join(args.book_dir, args.source_dir or "source_en")
        out = []
        for stem, s in _list_sources(src_dir):
            t = os.path.join(zh_dir, stem + args.suffix + ".md")
            out.append((stem, s, t))
        return out
    raise SystemExit("需要 --book-dir，或 --source/--target，或 --pair-dir")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-dir")
    ap.add_argument("--source-dir", default="source_en")
    ap.add_argument("--zh-dir", default="zh")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--source")
    ap.add_argument("--target")
    ap.add_argument("--pair-dir")
    ap.add_argument("--same-lang", action="store_true",
                    help="源文与译文同语言（模式 C），额外校验每段首尾字")
    ap.add_argument("--show", action="store_true", help="打印首个不一致处的段落对照")
    ap.add_argument("--label-max", type=int, default=None,
                    help="把「无句末标点」的源文块视为标签的长度上限（0=不限长，默认；"
                         "源文含大量半句断块时可设 60 恢复旧口径）")
    ap.add_argument("--tolerance", type=parse_tolerance, default=0,
                    help='允许的段数差：整数（绝对处数）或百分比（如 15%%）；'
                         '0.25 这类小数会直接报错。'
                         '默认 0 —— **Ⅰ 档源文（段落边界原始完好）必须相等**；'
                         'Ⅱ/Ⅲ 档（段落边界是机器重建的）用百分比放宽，并在 README 记录偏差原因')
    ap.add_argument("--strict", action="store_true",
                    help="旧口径：只排除 # 块，不做「标题/标签」对称过滤（默认关闭）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    pairs = resolve_pairs(a)
    if not pairs:
        raise SystemExit("没找到可配对的源文/译文")

    report, bad = [], 0
    for name, sp, tp in pairs:
        if not os.path.exists(tp):
            report.append({"file": name, "error": "译文缺文件: %s" % tp})
            bad += 1
            continue
        r = compare(open(sp, encoding="utf-8").read(),
                    open(tp, encoding="utf-8").read(),
                    same_lang=a.same_lang, show=a.show,
                    strict=a.strict, tolerance=a.tolerance)
        r["file"] = name
        ok = r["count_ok"] and r.get("target_meta", 0) == 0 \
            and r["end_punct_mismatch"] * 10 <= max(r["src_paras"], 1) \
            and (not a.same_lang or r["head_tail_mismatch"] == 0)
        r["ok"] = ok
        if not ok:
            bad += 1
        report.append(r)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in report:
            if "error" in r:
                print("✗ %-34s %s" % (r["file"], r["error"]))
                continue
            flag = "✓" if r["ok"] else "✗"
            extra = ""
            if not r["count_ok"]:
                extra = "  （差 %+d 段）" % (r["tgt_paras"] - r["src_paras"])
                if a.show and r["detail"]:
                    print("    首个不一致（第 %d 段）：" % r["detail"]["index"])
                    print("      源：%s" % r["detail"]["src"])
                    print("      译：%s" % r["detail"]["tgt"])
            elif r["end_punct_mismatch"]:
                extra = "  段末形态不一致 %d/%d" % (r["end_punct_mismatch"], r["src_paras"])
                if a.show and r["detail"]:
                    print("    首个不一致（第 %d 段）：%s" % (r["detail"]["index"], r["detail"]["why"]))
                    print("      源：%s" % r["detail"]["src"])
                    print("      译：%s" % r["detail"]["tgt"])
            if r.get("target_meta"):
                extra += "  译文含源文元数据标记 %d 处（应删除）" % r["target_meta"]
            if a.same_lang and r["head_tail_mismatch"]:
                extra += "  首尾字不符 %d" % r["head_tail_mismatch"]
            print("%s %-34s 源 %3d 段 / 译 %3d 段%s" % (flag, r["file"], r["src_paras"], r["tgt_paras"], extra))

    total = len([r for r in report if "error" not in r])
    missing = len([r for r in report if "error" in r])
    shifted = len([r for r in report if "error" not in r and not r["ok"]])
    if bad == 0:
        print("\n结论：段落边界守恒（%d/%d 文件通过）" % (total, total))
    else:
        bits = []
        if shifted:
            bits.append("段落边界被改动 %d 处" % shifted)
        if missing:
            bits.append("译文缺文件 %d 处" % missing)
        print("\n结论：%s（%d/%d 已配对文件通过）" % ("；".join(bits), total - shifted, total))
        if shifted:
            print("提示：若确属刻意整理的书面版，成品名加 `_书面整理版` 并在前言声明形态；"
                  "否则按源文段落边界回切译稿（分段只能在翻译前做）。")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
