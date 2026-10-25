#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_numbers.py —— 与陷阱类型无关的数字/折扣/倍数校验（不依赖"提前知道陷阱"）

为什么需要：把 `X% off` 之类规则内联进 prompt 只是**知识注入**——它只覆盖已知陷阱。
新书、新领域会出现没见过的数值陷阱，此时译错是静默的，规则帮不上忙。
本脚本改用**结构比对**：不看语义，只核对「原文里的数与译文里的数对不对得上」，
因此对未知陷阱同样有效。

三类检查：
1. **折扣方向**：原文 `X% off` → 期望「降价 X%」或「打 (10 − X/10) 折」。
   译文若出现「打 N 折」（含中文数字『八折』）且 N ≠ 10 − X/10 → I 类风险。
   （实测：把 `80% off` 译成「八折」是高频方向错。）
2. **数字对齐**：原文数字集合 vs 译文数字集合；原文有而译文无 → 可能漏译/改数；
   译文有而原文无 → 可能编造。
3. **倍数方向**：原文 `Nx more` → 译文出现「高 N 倍」即 I 类风险（中文「高 N 倍」= N+1 倍）。

用法：
    python check_numbers.py --source <源.txt> --target <译.md>
    python check_numbers.py --pair-dir <目录>            # 目录内 a.txt / a.md 同名配对
退出码：发现问题 1，干净 0。
"""
import argparse, glob, json, os, re, sys

CN = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6,
      '七': 7, '八': 8, '九': 9, '十': 10}


CN_DIGIT = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CN_UNIT = {'十': 10, '百': 100, '千': 1000}
CN_BIG = {'万': 10000, '亿': 100000000}


def cn2num(s):
    """中文数字 → 数值（支持 三十四/一千/一百/一百万/9.5 等全部常见写法）。

    为什么必须完整支持：译文用「一千」「一百万美元」写数时，若解析不出来就会被
    误报成「数字缺失」（实测 5 章因此误报）。
    """
    s = (s or '').strip().replace(',', '').replace('，', '')
    if not s:
        return None
    try:
        return float(s)                          # 9.5 / 8.5 这类小数折数
    except ValueError:
        pass
    total = section = num = 0
    for ch in s:
        if ch in CN_DIGIT:
            num = CN_DIGIT[ch]
        elif ch in CN_UNIT:
            section += (num if num else 1) * CN_UNIT[ch]
            num = 0
        elif ch in CN_BIG:
            section = (section + num) if (section or num) else 1
            total += section * CN_BIG[ch]
            section = num = 0
        else:
            return None
    if s == '零':
        return 0.0
    v = total + section + num
    return float(v) if v else None


def cn_numeral_values(text):
    """把译文里的中文数字抽出来（三十四→34、一百→100、一百万→1000000、25 万→250000，
    `$3,000 万`→30000000、`3 千万`→30000000），否则「用中文数字或『万/亿』为单位写数」
    会被误报成数字缺失（实测多章如此，且译文常写带千位逗号的 `$3,000 万`）。
    """
    out = set()
    for m in re.finditer(r'(\d[\d,]*(?:\.\d+)?|[零一二两三四五六七八九十百千万亿]+)\s*([万亿千百]{1,2})?', text):
        s, unit = m.group(1), m.group(2)
        if not s:
            continue
        v = cn2num(s)
        if v is None:
            continue
        for ch in (unit or ''):
            v *= {'万': 10000, '亿': 100000000, '千': 1000, '百': 100}.get(ch, 1)
        if v >= 1:
            out.add(_fmt(v))
    return out


EN_WORDS = {
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80,
    'ninety': 90, 'hundred': 100, 'thousand': 1000, 'million': 1000000,
}
# 解析复合数词时需要的个位词；单独出现时不产出（与旧行为一致，避免小整数噪声）
EN_ONES = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
           'seven': 7, 'eight': 8, 'nine': 9}
EN_SCALE = {'hundred': 100, 'thousand': 1000, 'million': 1000000, 'billion': 1000000000,
            'grand': 1000}      # `$120-grand` / `a hundred and fifty grand` = 12 万 / 15 万
_EN_TOK = re.compile(
    r'(\d[\d,]*(?:\.\d+)?)|\b(' + '|'.join(sorted(set(list(EN_WORDS) + list(EN_ONES) + list(EN_SCALE)),
                                            key=len, reverse=True)) + r')\b', re.I)


def en_word_values(text):
    """英文数词 → 数值集合，**按短语整体解析**。

    为什么不能逐个词取：`seven thousand` 若拆成 7 与 1000，源文集合里就会多出一个
    1000，而译文写「七千」（=7000）对不上 1000，于是误报「数字缺失」（实测
    实测某章即由此误报）。这里按 CS 标准算法合并整段数词短语。

    两条降噪规则（都是实测误报源）：
    - 只产出**含数词**的短语：纯阿拉伯数字的短语交给 nums()，否则 `$23M`、`900AM`
      会被重复登记成裸值 23 / 900；
    - 量级 ≥ 百万时忽略小于 10 的尾数：`a million and one ways` 是「无数种」的习语，
      按字面解析成 1000001 必然误报。
    """
    out = set()
    cur = total = 0.0
    run_has_scale = False
    run_has_word = False
    run_has_number = False
    prev_was_digit = False
    prev_end = None
    gap_ok = re.compile(r'^[\s\-–—]*(?:and[\s\-–—]+)?$', re.I)

    def flush():
        nonlocal cur, total, run_has_scale, run_has_word, run_has_number
        if total >= 1e6 and 0 < cur < 10:
            cur = 0.0                          # a million and one → 一百万
        v = total + cur
        if run_has_word and run_has_number and v and (v >= 10 or run_has_scale):
            out.add(_fmt(v))
        cur = total = 0.0
        run_has_scale = False
        run_has_word = False
        run_has_number = False

    for m in _EN_TOK.finditer(text):
        digit, word = m.group(1), m.group(2)
        if prev_end is not None and not gap_ok.match(text[prev_end:m.start()]):
            flush()                            # 数词短语之间夹了普通单词 → 断段
            prev_was_digit = False
        if prev_was_digit and not (digit is None and word.lower() in EN_SCALE):
            # 阿拉伯数字后只允许接 hundred/thousand/million（1 billion / 2.5 million）；
            # 接别的数词就是两个独立短语（实测 `$39 six-week`→45、`13 four-week`→17）。
            flush()
        if digit is not None and run_has_word:
            # 数词与阿拉伯数字不混在同一短语里：`one 30 to 45 minute` 若累加会得 31
            # （实测 LOST ch23 误报）。
            flush()
        prev_end = m.end()
        if digit is not None:
            cur += float(digit.replace(',', ''))
            prev_was_digit = True
            run_has_number = True
            continue
        prev_was_digit = False
        w = word.lower()
        run_has_word = True
        if w in EN_SCALE:
            scale = EN_SCALE[w]
            run_has_scale = True
            if scale == 100:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * scale
                cur = 0.0
        else:
            if w in EN_ONES and cur and cur % 10:
                flush()                        # 个位词只能跟在十位词后：`seven eight-figure`≠15
            cur += EN_ONES.get(w, EN_WORDS.get(w, 0))
            run_has_number = True
    flush()
    out.discard('0')
    return out


def _fmt(v):
    """数值 → 统一字符串键（避免 0.001 / .001 / 001 三种写法各算一个数）。"""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(round(f, 6)).rstrip('0').rstrip('.')


def nums(text, significant_only=True):
    """抽数字（去千位逗号、统一全角数字），返回集合。

    significant_only=True 时只保留「有意义的数」：≥10、带小数点、或带货币/百分号前缀后缀。
    这样能滤掉列表编号（1. 2. 3.）与「one/two 写成数字」这类噪声——实测不过滤时
    31 章里有 28 章会被误报，全是小整数噪声。

    三类已知噪声在这里就地剔除（都是实测误报源，与具体书无关）：
    - 带量级后缀的数（`$1.7M`、`100k`）只登记展开值，否则译文写「170 万」会误报缺失；
    - 粘在字母上的数字（OCR 把数字认成字母或反之，如 `9OOSA`、`l2OO`）不是数；
    - 连字符紧跟在字母后的编号（`COVID-19`）视为专名，不参与比对；
    - `.001` 这类前导零小数与译文 `0.001` 归一成同一个键。
    """
    t = text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    out = set()
    for m in re.finditer(r'([$￥€])?\s*(\d[\d,]*(?:\.\d+)?)\s*(%)?', t):
        cur, raw, pct = m.group(1), m.group(2), m.group(3)
        v = raw.replace(',', '').rstrip('.')
        if not v:
            continue
        tail = t[m.end():m.end() + 12]
        if re.match(r'[A-Za-z]', tail[:1]) and not re.match(r'\s*[MKBm]', tail[:2]):
            continue                               # 数字粘字母：OCR 产物，不是数
        if re.search(r'[A-Za-z]-$', t[max(0, m.start() - 4):m.start() + 1]):
            continue                               # COVID-19 / H-1B：专名编号
        scale = re.match(r'\s*(million|thousand|billion|hundred)\b', tail, re.I)
        if scale:
            continue                               # 量级词交给 en_word_values 整体解析
        if re.match(r'[\s\-–]*grand\b', tail, re.I):
            out.add(_fmt(float(v) * 1000))         # `$120-grand` = 12 万
            continue
        suf = re.match(r'\s*([MKBmk])(?![A-Za-z])', tail)
        if suf:
            out.add(_fmt(float(v) * {'k': 1e3, 'm': 1e6, 'b': 1e9}[suf.group(1).lower()]))
            continue
        if not (cur or pct) and v.startswith('0') and len(v) > 1 and '.' not in v:
            out.add(_fmt(int(v) / 10 ** len(v)))   # 前导零小数：`.001` 抽成 "001" → 0.001
            continue
        if significant_only:
            digits = v.replace('.', '')
            # **后缀式货币/单位也算法「有意义的数」**（2026-10-07 实测误报）：
            # 源文 `$0` 带前缀算显著，译文把它写成「0 美元」（前缀变后缀）后，
            # 旧判据只看前缀 → 判成「无意义小整数」→ 报「数字缺失」。实测 5 章全属此类。
            cjk_suf = re.match(r'\s*(美元|美金|元|块钱|块|万|亿|千|百|美分|角|分|倍|个百分点|个|天|年|月|周)', tail)
            if not (cur or pct or cjk_suf or '.' in v or len(digits) >= 2):
                continue
        out.add(_fmt(v) if re.match(r'^\d+(\.\d+)?$', v) else v)
    return out


_BOILER = re.compile(r'(copyr|all\s*rights|not\s*for\s*distribut|isbn|printed\s*in'
                     r'|www\.|https?://|scan\s*me)', re.I)


def strip_repeated_lines(text, min_repeats=3, max_len=200):
    """丢弃页眉/页脚噪声行（含页码的那种）。

    为什么需要：扫描件/PDF 抽取出的源文常在每页页脚带「Copyright ... NOT FOR
    DISTRIBUTION 46」这类行，其中的页码会被当成正文数字报缺失（实测 P3 段落误报
    数字 46）。判据有两条，都不依赖具体哪本书：
      1. 同一行去掉数字后重复 ≥3 次 → 版式噪声；
      2. 行内含版权/网址/发行标记等套版词，且带数字 → 版式噪声（样本页数少时兜底）。
    """
    from collections import Counter
    keys = [re.sub(r'\s+', ' ', re.sub(r'\d+', '#', ln.strip().lower())) for ln in text.split('\n')]
    cnt = Counter(k for k in keys if k and len(k) <= max_len)
    keep = []
    for ln, k in zip(text.split('\n'), keys):
        if re.search(r'\d', ln) and ((k and len(k) <= max_len and cnt[k] >= min_repeats)
                                     or _BOILER.search(ln)):
            continue
        keep.append(ln)
    return '\n'.join(keep)


def strip_markers(text):
    """剔除页码/图片页标记与重复页眉页脚——这些数字不该参与比对（页码是正确的噪声）。"""
    text = re.sub(r'\[PDF 第 \d+ 页\]', ' ', text)
    text = re.sub(r'\[图片页[^\]]*\]', ' ', text)
    text = re.sub(r'(?m)^\s*\d+\s*$', ' ', text)          # 独占一行的页码
    text = re.sub(r'\S*figs?/\S*', ' ', text)              # 插图路径 figs/p125.png
    text = re.sub(r'\b[\w\-]+\.(?:png|jpe?g|gif|webp|svg)\b', ' ', text, flags=re.I)
    return strip_repeated_lines(text)


def ctx(text, value, n=2, width=60):
    """取该数字在源文中的出现片段，供人工一眼判定是真漏译还是页码/版式噪声。"""
    out = []
    for m in re.finditer(r'(?<!\d)' + re.escape(value) + r'(?!\d)', text):
        out.append(re.sub(r'\s+', ' ', text[max(0, m.start() - width): m.end() + width]).strip())
        if len(out) >= n:
            break
    return out


_PCT_OFF = re.compile(r'(\d+(?:\.\d+)?|[A-Za-z][A-Za-z\-]*)\s*[\-–]?\s*(?:%|percent)\s*off\b', re.I)


def percent_offs(source):
    """找出源文所有 `X% off` / `ninety percent off`，返回 [(match, 百分数)]。

    支持单词写的百分数：`sell the gift cards at ninety percent off` 若只按数字匹配，
    90 会被当成普通数字与译文「九折」对不上（实测某章误报）。
    """
    out = []
    for m in _PCT_OFF.finditer(source):
        tok = m.group(1)
        if re.match(r'^\d', tok):
            out.append((m, float(tok)))
            continue
        vals = en_word_values(tok)
        if len(vals) == 1:
            out.append((m, float(next(iter(vals)))))
    return out


def check(source, target):
    source = strip_markers(source)
    issues, hints = [], []
    # 1) 折扣方向
    for _m, pct in percent_offs(source):
        want_fold = 10 - pct / 10.0
        ok = False
        for tm in re.finditer(r'(\d+(?:\.\d+)?)\s*%|([零一二两三四五六七八九十]+|\d+(?:\.\d+)?)\s*折', target):
            if tm.group(1):
                if abs(float(tm.group(1)) - pct) < 0.01:
                    ok = True
            else:
                v = cn2num(tm.group(2))
                if v is not None and abs(v - want_fold) < 0.01:
                    ok = True
        if not ok:
            issues.append(dict(kind='折扣方向', source='%g%% off' % pct,
                               expect='降价 %g%% 或打 %g 折' % (pct, want_fold),
                               note='译文未找到等价的百分比或折数'))
    # 2) 数字对齐（「缺失」参与判定；「多出」只作提示——英文常用数词、译文常用数字，噪声大）
    sn = nums(source) | en_word_values(source)
    tn = nums(target) | cn_numeral_values(target)
    # `X% off` 的 X 已在检查 1 里单独判定方向，且译文合法地写成折数（60% off → 四折），
    # 从对齐集合里剔除，否则必然误报缺失（实测多章如此）。
    for _m, pct in percent_offs(source):
        sn.discard(_fmt(pct))
    miss = sorted(sn - tn, key=lambda x: float(x))
    extra = sorted(tn - sn, key=lambda x: float(x))
    if miss:
        issues.append(dict(kind='数字缺失', source=', '.join(miss[:12]),
                           expect='这些数字应在译文中出现',
                           note='原文有而译文无：可能漏译或改数（看下方原文片段自行判定）',
                           samples=[s for v in miss[:3] for s in ctx(source, v, n=1)]))
    if extra:
        hints.append(dict(kind='数字多出（仅提示）', source=', '.join(extra[:12]),
                          expect='—', note='译文有而原文无：多为数词换算或译者补充说明，需人工一眼扫过'))
    # 3) 倍数方向
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:x|times)\s+more\b', source, re.I):
        n = m.group(1)
        if re.search(r'高\s*%s\s*倍' % re.escape(n), target):
            issues.append(dict(kind='倍数方向', source='%sx more' % n,
                               expect='是……的 %s 倍（贵 %g%%）' % (n, (float(n) - 1) * 100),
                               note='译文写成「高 %s 倍」＝%g 倍，属 I 类' % (n, float(n) + 1)))
    return issues, hints


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source')
    ap.add_argument('--target')
    ap.add_argument('--pair-dir', help='目录：a.txt 与 a.md 同名配对')
    ap.add_argument('--book-dir', help='书目录：自动配对 source_en/{*.txt,*.md} 与 zh/<同名>.md')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    pairs = []
    if args.book_dir:
        # 源文可能是 `.txt`（PDF/EPUB 提取）或 `.md`（MD 转换产物，如《某商业书》系列）。
        # 2026-10-07 补：此前只有 --source/--target 与 --pair-dir（后者只认 .txt 源），
        # 对 .md 源文无路可走。
        srcs = {}
        for ext in ('.md', '.txt'):
            for p in sorted(glob.glob(os.path.join(args.book_dir, 'source_en', '*' + ext))):
                srcs[os.path.splitext(os.path.basename(p))[0]] = p
        for stem, s in sorted(srcs.items()):
            t = os.path.join(args.book_dir, 'zh', stem + '.md')
            if os.path.exists(t):
                pairs.append((s, t))
    elif args.pair_dir:
        for fn in sorted(os.listdir(args.pair_dir)):
            if fn.endswith('.txt'):
                src = os.path.join(args.pair_dir, fn)
                for ext in ('.md', '.markdown'):
                    tgt = os.path.join(args.pair_dir, fn[:-4] + ext)
                    if os.path.exists(tgt):
                        pairs.append((src, tgt))
    elif args.source and args.target:
        pairs.append((args.source, args.target))
    else:
        sys.exit('需要 --source/--target 或 --pair-dir')

    allbad = 0
    report = {}
    for src, tgt in pairs:
        iss, hints = check(open(src, encoding='utf-8').read(), open(tgt, encoding='utf-8').read())
        name = os.path.basename(src)
        report[name] = {'问题': iss, '提示': hints}
        if iss:
            allbad += 1
            print('✗ %s' % name)
            for i in iss:
                print('   [%s] %s → 期望：%s；%s' % (i['kind'], i['source'], i['expect'], i['note']))
                for s in i.get('samples', []):
                    print('        原文片段：…%s…' % s)
        else:
            print('✓ %s 数字/折扣/倍数核对通过%s' % (name, ('（提示 %d 项）' % len(hints)) if hints else ''))
        for h in hints[:2]:
            print('   · 提示：多出数字 %s（多为数词换算或译者补充，一眼扫过）' % h['source'])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if allbad else 0


if __name__ == '__main__':
    sys.exit(main())
