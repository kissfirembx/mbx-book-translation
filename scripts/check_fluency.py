#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_fluency.py —— 翻译腔指纹扫描（中文单语，零依赖、零 token）

为什么需要
----------
整条管线里只有「流畅度」这一格没有机器可达路径：A4 的「单语通读」靠 AI 逐章
读完 10% 的稿子，按比例烧 token，且没有任何判定标准。本脚本把「中文读起来像
不像翻译」拆成 10 项**可计算的形式指标**（其中 9 项参与排序；第 10 项「句长标准差」
只报告、不排序，因为方向不明），逐段算分、按全书自身分布排序，
把最可疑的一小撮挑出来，交给一次定向审校（人读或 AI 读）复核。

为什么是排序器，不是判定器
--------------------------
翻译腔**没有权威阈值**。同一指标的绝对值随语料、文体、作者变——「的」字密度
原创 4.7% vs 译文 5.97% 出自特定语料库（LCMC vs ZCTC），换一本书即失效；
「平均句长」「长句率」只有分文体的经验区间，没有合格线。所以本脚本：
  - 不输出「合格 / 不合格」，也不设退出码门禁（退出码恒为 0）；
  - 只做**全书内 z-score 排序**，输出「哪几段偏离全书最多」。
这样绕开「没有阈值」的死结，也让复核成本从「读全书的 10%」降到「读 top N%」。

指标来源
--------
- Koppel & Ordan (ACL 2011)「Translationese and Its Dialects」：只用功能词频率
  即可 96.7% 区分人工翻译与原创——证明翻译腔是**可计算**的。
- 中文侧量化：PLOS ONE《Entropy-based discrimination between translated Chinese
  and original Chinese》用 LCMC(原创) 与 ZCTC(译文) 两个百万词平衡语料库实证。
- 各指标的出处与「有无权威阈值」逐条标注见 references/关于流畅度质检.md。

用法
----
    python check_fluency.py --book-dir <书目录>          # 自动用 <书目录>/zh/*.md
    python check_fluency.py --dir <含 md 的目录>
    python check_fluency.py --file <单篇.md>
    python check_fluency.py --book-dir <书目录> --suffix _重译版
选项：--top-seg N（默认 20）、--top-pct P（默认 0.05）、--min-han（段入选下限，默认 40）、
     --out <报告.md>、--json
"""
import argparse
import json
import os
import re
import sys
from statistics import mean, pstdev

# ---------- 文本规整 ----------

HAN = re.compile(r'[一-鿿]')
SENT_SPLIT = re.compile(r'[。！？!?]+|…{2,}')


def clean(s):
    """去掉 Markdown 装饰与非正文块，只留可计量的中文句子。"""
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)          # 注释/完成标记
    s = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', s)            # 图片
    s = re.sub(r'\[PDF 第 \d+ 页\]', '', s)                # 页码标记
    s = re.sub(r'\[图片页[^\]]*\]', '', s)
    s = re.sub(r'\[([^\]]{0,20})\]\([^)]*\)', r'\1', s)    # 链接保留文字
    s = re.sub(r'^\s*>\s?', '', s, flags=re.M)             # 引用符号
    s = s.replace('**', '').replace('　', '')              # 加粗标记、全角缩进
    s = re.sub(r'`{1,3}', '', s)                           # 行内/围栏代码标记
    return s


def segments(text):
    """按空行切段，丢掉标题/表格/代码块行；返回 [(段序, 段文本)]。

    只保留含汉字 ≥ min_han 的段：太短的段（标签、单句）会让密度类指标爆炸。
    """
    out = []
    for blk in re.split(r'\n\s*\n', text):
        keep = []
        for ln in blk.splitlines():
            if re.match(r'^\s*(#{1,6}\s|!\[|\||```|~~~|<!--|<\w)', ln):
                continue                                   # 标题/图/表/代码/注释
            keep.append(ln)
        body = clean('\n'.join(keep)).strip()
        if body:
            out.append(body)
    return out


def han_len(s):
    return len(HAN.findall(s))


def is_prose(s):
    """是不是「散文段」——把公式段、编号行、图表残行挡在排序之外。

    噪声比真信号多时，报告等于没报（本 skill 已知坑）。实测噪声有两类：
      1. 拉丁/数字占比过高的段（算式 `A) 每笔支付 X 美元（$…`、清单编号串）；
      2. 公式标点（括号/美元/百分号/等号）密集的段。
    这两类的「的字密度」「双重修饰」天然偏高，会挤掉真正可疑的散文段。
    """
    h = han_len(s)
    if h == 0:
        return False
    if len(re.findall(r'[A-Za-z0-9]', s)) > 0.25 * h:
        return False
    if len(re.findall(r'[（()）$%=→]', s)) > 0.03 * h + 2:
        return False
    return True


def sentences(s):
    """切句：以 。！？ 或 …… 为界，清空后只留含汉字的句。"""
    return [x.strip() for x in SENT_SPLIT.split(s) if han_len(x) >= 1]


# ---------- 10 项指标（9 项参与排序，sent_sd 只报告） ----------

# 虚化动词（「进行/作出/予以」类）——英式中文的典型特征（语言学定性，无阈值）
LIGHT_VERB = re.compile(r'进行|作出|做出|加以|予以|具有|存在|实现|完成|给予|造成|产生|成为|获得')
# 配对连接词（点状连词被拉成线状的欧化特征）
PAIRED_CONJ = re.compile(
    r'因为[^。！？；\n]{0,40}所以|虽然[^。！？；\n]{0,40}但是|尽管[^。！？；\n]{0,40}但是'
    r'|如果[^。！？；\n]{0,40}那么|当[^。！？；\n]{0,20}的时候|对于[^。！？；\n]{0,20}而言'
    r'|由于[^。！？；\n]{0,40}(?:因此|所以)')
# 介词框架（dbs-ai-check 特征 #19 点名的几个）
PREP_FRAME = re.compile(r'作为|关于|基于|通过|由于|围绕|针对')
# 双重/多重修饰：「……的……的」（语料库实测译文 ≈ 原创的两倍）
DBL_MOD = re.compile(r'的[^，。！？；：、\n]{1,12}的')
# 人称代词 + 的（译文显著高于原创）
PRON_DE = re.compile(r'(?:我们|你们|他们|她们|它们|咱们|我|你|他|她|它|您)的')
BEI = re.compile(r'被')

LONG_SENT = 40          # 「超 40 字拆句」是编辑惯例；无权威阈值，仅作参考列


def metrics(s):
    """单段（或单章）的指标字典。密度类统一「每千汉字」，比值类「每百句」。"""
    n = han_len(s)
    if n == 0:
        return None
    sents = sentences(s)
    lens = [han_len(x) for x in sents] or [0]
    n1000 = n / 1000.0
    nsent = len(lens) / 100.0
    return {
        'han': n,
        'sent': len(lens),
        # 参与排序的 9 项（方向统一：越高越像翻译腔）
        'de': len(re.findall('的', s)) / n1000,
        'dbl': len(DBL_MOD.findall(s)) / nsent,
        'pron_de': len(PRON_DE.findall(s)) / n1000,
        'sent_len': mean(lens),
        'long_rate': sum(1 for x in lens if x > LONG_SENT) / len(lens),
        'bei': len(BEI.findall(s)) / n1000,
        'light': len(LIGHT_VERB.findall(s)) / n1000,
        'pair': len(PAIRED_CONJ.findall(s)) / n1000,
        'prep': len(PREP_FRAME.findall(s)) / n1000,
        # 只报告、不进排序（方向不明：AI 文本句长过匀偏低，人类高）
        'sent_sd': pstdev(lens) if len(lens) > 1 else 0.0,
    }


def total_han(rows):
    return sum(m['han'] for m in rows)


# ---------- 排序 ----------

# metrics() 共算 10 项；这里只列参与排序的 9 项。第 10 项 sent_sd（句长标准差）只报告。
COMPOSITE_KEYS = ['de', 'dbl', 'pron_de', 'sent_len', 'long_rate', 'bei', 'light', 'pair', 'prep']
LABELS = {
    'de': '的/千字', 'dbl': '双重修饰/百句', 'pron_de': '代词+的/千字',
    'sent_len': '平均句长', 'long_rate': '长句率', 'bei': '被/千字',
    'light': '虚化动词/千字', 'pair': '配对连词/千字', 'prep': '介词框架/千字',
    'sent_sd': '句长标准差',
}


def zscores(rows, keys):
    """对每个指标算全书 z-score。std=0 时 z 记 0（该指标全书无差异）。"""
    z = [dict() for _ in rows]
    for k in keys:
        vals = [r[k] for r in rows]
        mu = mean(vals)
        sd = pstdev(vals)
        for i, r in enumerate(rows):
            z[i][k] = 0.0 if sd == 0 else (r[k] - mu) / sd
    return z


def suspicious(rows):
    """可疑度 = Σ max(z, 0)：只累计「比全书更偏翻译腔」的方向，不看偏低项。"""
    z = zscores(rows, COMPOSITE_KEYS)
    return [sum(max(zi[k], 0.0) for k in COMPOSITE_KEYS) for zi in z], z


# ---------- 主流程 ----------

def collect(args):
    files = []
    if args.file:
        files = [args.file]
    else:
        d = args.dir
        if args.book_dir:
            d = os.path.join(args.book_dir, 'zh')
        if not d or not os.path.isdir(d):
            sys.exit('需要 --book-dir / --dir / --file 之一，且目录存在')
        names = [f for f in sorted(os.listdir(d)) if f.endswith('.md')]
        if args.suffix:
            names = [f for f in names if args.suffix in f]
        if args.exclude:
            names = [f for f in names if args.exclude not in f]
        files = [os.path.join(d, f) for f in names]
    if not files:
        sys.exit('未找到 .md 文件')
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir', help='书目录；自动取 <书目录>/zh/*.md')
    ap.add_argument('--dir', help='直接指定含 md 的目录')
    ap.add_argument('--file', help='单篇 md')
    ap.add_argument('--suffix', default='', help='只看带该后缀的文件，如 _重译版')
    ap.add_argument('--exclude', default='', help='排除含该串的文件（如 _重译版）')
    ap.add_argument('--top-seg', type=int, default=20, help='输出最可疑的段数（默认 20）')
    ap.add_argument('--top-pct', type=float, default=0.05, help='可疑段占比上限（默认 5%%）')
    ap.add_argument('--min-han', type=int, default=40, help='段入选的最少汉字数（默认 40）')
    ap.add_argument('--min-han-chap', type=int, default=400,
                    help='章级排名的最少汉字数（默认 400；0.3KB 的分部引言不足此数，不参与排名）')
    ap.add_argument('--out', help='写出 Markdown 报告')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    files = collect(args)

    # 逐章 + 逐段
    chap_rows, chap_names = [], []
    seg_rows, seg_where = [], []      # where = (文件名, 段序, 段首 40 字)
    for fp in files:
        text = open(fp, encoding='utf-8').read()
        segs = [s for s in segments(text)
                if han_len(s) >= args.min_han and is_prose(s)]
        if han_len(text) >= args.min_han_chap:
            m = metrics(clean(text))
            if m:
                chap_rows.append(m)
                chap_names.append(os.path.basename(fp))
        for i, s in enumerate(segs, 1):
            m = metrics(s)
            if m:
                seg_rows.append(m)
                seg_where.append((os.path.basename(fp), i, re.sub(r'\s+', '', s)[:40]))

    if not seg_rows:
        sys.exit('可用段落不足（试试调小 --min-han）')

    # 章级排名
    cz, _ = suspicious(chap_rows)
    chap_rank = sorted(range(len(chap_rows)), key=lambda i: -cz[i])

    # 段级排名
    sz, szd = suspicious(seg_rows)
    order = sorted(range(len(seg_rows)), key=lambda i: -sz[i])
    n_top = max(1, min(args.top_seg, int(len(seg_rows) * args.top_pct) or args.top_seg))
    top = order[:n_top]
    # 只保留「确实偏离」的段：可疑度 > 1.0（相当于平均每项高出 1 个标准差）
    top = [i for i in top if sz[i] > 1.0] or top[:3]

    print('翻译腔指纹扫描（排序器，不做合格判定）')
    print('语料：%d 章 / %d 段 / %d 汉字' % (len(chap_rows), len(seg_rows), total_han(seg_rows)))
    print('说明：指标无权威阈值，只按全书内 z-score 排序；方向统一为「越高越像翻译腔」。')
    print()
    print('== 章级偏离排名（可疑度 = Σ max(z,0)）==')
    for r, i in enumerate(chap_rank[:10], 1):
        m = chap_rows[i]
        print('  %2d. %-34s 可疑度 %5.2f | 的 %5.1f/k  句长 %5.1f  配对连词 %4.1f/k'
              % (r, chap_names[i][:34], cz[i], m['de'], m['sent_len'], m['pair']))
    print()
    print('== 最可疑段落 top %d（送给定向审校的就是这些）==' % len(top))
    for r, i in enumerate(top, 1):
        fn, si, head = seg_where[i]
        m = seg_rows[i]
        hot = sorted(COMPOSITE_KEYS, key=lambda k: -szd[i][k])[:3]
        why = '、'.join('%s z=%+.1f' % (LABELS[k], szd[i][k]) for k in hot)
        print('  %2d. [%s 段%d] 可疑度 %4.2f  %s' % (r, fn, si, sz[i], why))
        print('      %s' % head)

    if args.out:
        rep = ['# 翻译腔指纹扫描（排序器）', '',
               '- 语料：%d 章 / %d 段 / %d 汉字' % (len(chap_rows), len(seg_rows), total_han(seg_rows)),
               '- 说明：指标无权威阈值，只按全书内 z-score 排序，不判合格与否。',
               '- 用途：把下列段落交一次「定向审校」复核，替代逐章 AI 通读。', '',
               '## 章级偏离排名', '', '| 名次 | 章 | 可疑度 | ' +
               ' | '.join(LABELS[k] for k in COMPOSITE_KEYS) + ' |',
               '|---|---|---|' + '---|' * len(COMPOSITE_KEYS)]
        for r, i in enumerate(chap_rank, 1):
            m = chap_rows[i]
            rep.append('| %d | %s | %.2f | ' % (r, chap_names[i], cz[i]) +
                       ' | '.join('%.1f' % m[k] for k in COMPOSITE_KEYS) + ' |')
        rep += ['', '## 最可疑段落', '', '| 名次 | 位置 | 可疑度 | 主要偏离 | 段首 |',
                '|---|---|---|---|---|']
        for r, i in enumerate(top, 1):
            fn, si, head = seg_where[i]
            hot = sorted(COMPOSITE_KEYS, key=lambda k: -szd[i][k])[:3]
            why = '、'.join('%s %+.1f' % (LABELS[k], szd[i][k]) for k in hot)
            rep.append('| %d | %s 段%d | %.2f | %s | %s |' % (r, fn, si, sz[i], why, head))
        open(args.out, 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
        print('\n报告已写出：%s' % args.out)

    if args.json:
        print(json.dumps({
            'chapters': [dict(file=chap_names[i], score=round(cz[i], 3),
                              **{k: round(chap_rows[i][k], 3) for k in COMPOSITE_KEYS})
                         for i in chap_rank],
            'segments': [dict(file=seg_where[i][0], seg=seg_where[i][1],
                              head=seg_where[i][2], score=round(sz[i], 3),
                              z={k: round(szd[i][k], 2) for k in COMPOSITE_KEYS})
                         for i in top],
        }, ensure_ascii=False, indent=1))

    return 0          # 排序器不做门禁，恒返回 0


if __name__ == '__main__':
    sys.exit(main())
