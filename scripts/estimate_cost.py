#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""estimate_cost.py —— 开工前的 **token 量预估**（钱由使用方自己折算）

为什么只估 token、不估钱（2026-10-07 改）：
  同一本书，用不同 Agent、不同模型，**单价可以差几十倍**，而且各家的缓存折扣、
  推理 token 计费口径都不同。把「元」写死在脚本里，对使用者就是错的。
  所以本脚本只算 **token 三桶**（缓存重发 / 未命中输入 / 输出），
  费用由**拥有单价的那一方**（你用的 Agent 或模型）自己折算——它才知道自己的价。

token 模型与出处（来自 2026-09-15 那次实测记账，见 `references/成本优化.md` 第一节）：
  - 中文字数 ≈ 英文**去空白**字符数 × 0.284（实测：211,082 → 59,987 汉字，误差 0.07%）
  - 调用次数 ≈ 章数 × 3；每次调用：缓存重发 10k、未命中输入 3k、输出 2.5k
    （2026-10-07 重标定：《某商业书》32 章实测合计约 1.2M token ⇒ 约 38k/章。
     **旧常数是 40 次/章 × 129k 重发——那是在「探索型译者」流程上量的**（会 grep 全书、
     反复自查、多轮重读）。本管线执行 P0 优化后（译者零文件阅读、禁探索、写完即止），
     实测每章只有 3–4 次工具调用。**旧模型把量级高估了约 40 倍。**）
  这几个数字是**本流水线的调用形态**，与用哪个模型无关；如你的 Agent 调用方式不同，
  用 --calls-per-ch / --resend / --miss / --out 覆盖。

用法：
    python estimate_cost.py --book-dir <书目录>                  # 只出 token（默认）
    python estimate_cost.py --book-dir <书目录> --rates cache=0.02,in=1.02,out=4.04
                                        # 自行提供单价（元/百万 token）时才出钱
选项：--en-chars、--chapters、--calls-per-ch、--optimized、--json
退出码恒 0。
"""
import argparse
import glob
import json
import os
import re
import sys

ZH_PER_EN_CHAR = 0.284         # 英文去空白字符 → 中文字数（实测比例）
CALLS_PER_CH = 3               # 2026-10-07 重标定（旧值 40 是探索型流程实测，本管线实际 3–4）
RESEND = 10_000                # 每次调用的缓存重发 token（旧值 129_000 高估约 13 倍）
MISS_IN = 3_000                # 每次调用的未命中输入 token
OUT = 2_500                    # 每次调用的输出 token


def en_chars(book_dir):
    d = os.path.join(book_dir, 'source_en')
    if not os.path.isdir(d):
        return None, None
    files = glob.glob(os.path.join(d, '*.txt'))
    n = sum(len(re.sub(r'\s', '', open(f, encoding='utf-8').read())) for f in files)
    return n, len(files)


def buckets(calls, resend=RESEND, miss=MISS_IN, out=OUT):
    r = calls * resend
    m = calls * miss
    o = calls * out
    return r, m, o, r + m + o


def parse_rates(s):
    """--rates cache=0.02,in=1.02,out=4.04（元/百万 token）"""
    if not s:
        return None
    out = {}
    for part in s.split(','):
        k, _, v = part.partition('=')
        k = k.strip().lower()
        if k not in ('cache', 'in', 'out'):
            sys.exit('--rates 只认 cache / in / out 三个键')
        out[k] = float(v) / 1e6          # 元/百万 → 元/token
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-dir')
    ap.add_argument('--en-chars', type=int)
    ap.add_argument('--chapters', type=int)
    ap.add_argument('--calls-per-ch', type=int, default=CALLS_PER_CH)
    ap.add_argument('--resend', type=int, default=RESEND)
    ap.add_argument('--miss', type=int, default=MISS_IN)
    ap.add_argument('--out', type=int, default=OUT)
    ap.add_argument('--optimized', action='store_true', help='按精校档 12 次/章算')
    ap.add_argument('--provider', default=None, help='API 提供方 key，如 deepseek（读 references/data/api-pricing.json）')
    ap.add_argument('--model', default=None, help='模型名，如 deepseek-flash')
    ap.add_argument('--rates', help='单价（元/百万 token）：cache=..,in=..,out=..（不给则只出 token）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.book_dir:
        n, ch = en_chars(args.book_dir)
        if n is None:
            sys.exit('目录下没有 source_en/：%s' % args.book_dir)
    else:
        n, ch = args.en_chars, args.chapters
    if not n:
        sys.exit('需要 --book-dir 或 --en-chars')
    if args.optimized:
        args.calls_per_ch = 12
    ch = ch or 1
    rate = parse_rates(args.rates)

    RS, MI, OT = args.resend, args.miss, args.out

    zh = n * ZH_PER_EN_CHAR
    c_all = ch * args.calls_per_ch
    c_smp = args.calls_per_ch
    r, m, o, t_all = buckets(c_all, RS, MI, OT)
    _r, _m, _o, t_smp = buckets(c_smp, RS, MI, OT)

    def fmt(x):
        return ('%.2fM' % (x / 1e6)) if x >= 1e6 else ('%.0fk' % (x / 1e3))

    def money(rr, mm, oo):
        if not rate:
            return ''
        f = rr * rate.get('cache', 0) + mm * rate.get('in', 0) + oo * rate.get('out', 0)
        return ' ｜ 约 %.2f（按你给的单价）' % f

    print('token 消耗方式预估（依据 references/成本优化.md 的实测调用形态）')
    print('─' * 60)
    print('原文字符（去空白）：%s ｜ 章数：%d' % ('{:,}'.format(n), ch))
    print('估算中文字数：%s 字' % '{:,.0f}'.format(zh))
    print('每次调用形态：重发 %s ／ 未命中 %s ／ 输出 %d' % (fmt(RS), fmt(MI), OT))
    print('   ↑ 这三项的**单价各不相同**（缓存命中的通常便宜一个量级），')
    print('     所以消耗方式按三桶报，不合并成一个数——合并了就没法折算。')
    print('─' * 60)
    print('【小样】1 章：调用 %d 次 ｜ token 合计 %s%s'
          % (c_smp, fmt(t_smp), money(*buckets(c_smp, RS, MI, OT)[:3])))
    print('【整本】%d 章：调用 %d 次 ｜ token 合计 %s%s' % (ch, c_all, fmt(t_all), money(r, m, o)))
    print('     拆分：缓存重发 %s ／ 未命中输入 %s ／ 输出 %s' % (fmt(r), fmt(m), fmt(o)))
    if not args.optimized and args.calls_per_ch == CALLS_PER_CH:
        # 两个档位的差别不在「译者读几个文件」，而在**档位要不要跑 A4 三层审校**：
        #   自读档：每章只有翻译 1 个 agent（实测 3–4 次调用）→ 就是上面的【整本】。
        #   精校档：翻译 agent + 双语审校 + 定向审校 + 一致性扫描 ≈ 每章 12 次调用量级。
        b12 = buckets(ch * 12, RS, MI, OT)
        print('【精校档】翻译 + A4 三层审校（约 12 次/章）：token 合计 %s%s'
              % (fmt(b12[3]), money(*b12[:3])))
        print('     ↑ **自读档就是上面的【整本】**；两档的差在「要不要跑三层审校」，不在译者读几个文件。')
    print('─' * 60)
    if not rate:
        print('⚠️ 本脚本**不预设单价**——计费口径因 Agent / 模型 / 套餐而异，差异极大：')
        print('   · 有的按 coding plan / token plan 包月；')
        print('   · 有的买会员送积分（如豆包按月送额度）；')
        print('   · 有的按 token 阶梯计价，缓存命中与未命中、推理与正文价不同。')
        print('   👉 **正确的下一步是问使用者**：你用哪个 Agent、哪个模型、什么套餐？')
        print('      把上面**三桶 token** 交给那一方，由它按自己的口径折算——它才知道自己的价。')
        print('      （想让本脚本直接出钱：传 --rates cache=..,in=..,out=..，单位元/百万 token）')
    # 单价：**只从缓存文件读，不猜**（见 references/data/api-pricing.json）
    if args.provider:
        import json, os as _os
        cache = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                              _os.pardir, 'references', 'data', 'api-pricing.json')
        try:
            data = json.load(open(cache, encoding='utf-8'))[args.provider]
            cur, models = data['currency'], data.get('models', {})
            print('\n单价（来源：%s，抓取于 %s，币种 %s）：'
                  % (data.get('source', '本地缓存'), data.get('fetched_at', '?'), cur))
            for name, m in models.items():
                if args.model and name != args.model:
                    continue
                print('   %-18s 缓存命中 %.4g／未命中 %.4g／输出 %.4g（优惠时段，每百万 token）'
                      % (name, m['input_cache_hit']['off_peak'],
                         m['input_cache_miss']['off_peak'], m['output']['off_peak']))
            print('   → 把上面三桶交给使用者按其套餐折算；换 API 或换计费方式时更新该文件。')
        except Exception as e:
            print('\n⚠️ 未读到单价缓存（%s）：%s' % (args.provider, e))
            print('   → 请让使用者提供价目，或去该家官方计费页查后写入 references/data/api-pricing.json。')
    print('   这只是**按调用形态的推算**，不是账单。')
    print('   ⚠️ 两个最大的误差来源，按此自检：')
    print('      ① **调用形态**：上面「调用次数/每次重发」是本书型源的实测值。你的 Agent 若会 grep 全书、'
          '反复自查，实际可能是它的 10 倍以上（用 --calls-per-ch 校正）。')
    print('      ② **单价**：**不许凭记忆填价**——去该家官方计费页查，**注意币种**（如 DeepSeek 官方页是 USD）。')

    if args.json:
        print(json.dumps(dict(en_chars=n, chapters=ch, zh_chars=round(zh),
                              tokens_sample=round(t_smp), tokens_all=round(t_all),
                              resend=round(r), miss=round(m), out=round(o),
                              rate_used=bool(rate)), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
