#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cost_report.py —— 从 DSH 用量账本读真实花费，拆成本三桶并给出每调用均值

为什么需要：翻译管线的成本主项是「模型调用次数 × 每次重发的上下文长度」加上
「输出（其中六成是推理 token）」，不是译文长度。凭印象优化会打偏，必须读账本。

数据来源：`~/.dsh/dsh-usage/usage-ledger.json`（DSH 本地记账，按天/provider/model 记
inputTokens / outputTokens / cacheReadTokens / reasoningTokens / calls / cost）。

用法：
    python cost_report.py                      # 最近 7 天汇总
    python cost_report.py --days 3             # 最近 3 天
    python cost_report.py --date 2026-09-15    # 单日明细 + 三桶拆分
    python cost_report.py --json               # 机器可读
退出码：0
"""
import argparse, json, os, sys

from mbx_config import usage_ledger

DEFAULT_LEDGER = usage_ledger()

# 单价（人民币 / 百万 token，DeepSeek 非峰时；峰时约 ×2）。仅用于拆分比例，绝对值以账本 cost 为准。
PRICE = {'cacheRead': 0.021, 'input': 1.05, 'output': 4.2}


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f).get('days', {})


def flatten(days):
    rows = []
    for day in sorted(days):
        for prov, models in days[day].items():
            for model, s in models.items():
                rows.append(dict(day=day, provider=prov, model=model, **s))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ledger', default=DEFAULT_LEDGER)
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--date', default='')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.ledger):
        sys.exit('账本不存在：%s' % args.ledger)
    rows = flatten(load(args.ledger))
    if args.date:
        rows = [r for r in rows if r['day'] == args.date]
    else:
        keep = sorted({r['day'] for r in rows})[-args.days:]
        rows = [r for r in rows if r['day'] in keep]
    if not rows:
        sys.exit('指定范围内没有记账数据')

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print('%-12s %-34s %6s %12s %12s %12s %9s' %
          ('日期', '模型', '调用', '未命中输入', '缓存读', '输出', '费用'))
    for r in rows:
        print('%-12s %-34s %6d %12d %12d %12d %9.4f' %
              (r['day'], r['model'][:34], r.get('calls', 0), r.get('inputTokens', 0),
               r.get('cacheReadTokens', 0), r.get('outputTokens', 0), r.get('cost', 0)))

    calls = sum(r.get('calls', 0) for r in rows)
    inp = sum(r.get('inputTokens', 0) for r in rows)
    cr = sum(r.get('cacheReadTokens', 0) for r in rows)
    out = sum(r.get('outputTokens', 0) for r in rows)
    rea = sum(r.get('reasoningTokens', 0) for r in rows)
    cost = sum(r.get('cost', 0) for r in rows)

    print('\n合计：%d 次调用，未命中输入 %d，缓存读 %d，输出 %d（其中推理 %d，占 %.0f%%），费用 %.4f'
          % (calls, inp, cr, out, rea, (rea / out * 100 if out else 0), cost))
    if calls:
        print('每次调用均值：缓存读 %.0f / 未命中 %.0f / 输出 %.0f'
              % (cr / calls, inp / calls, out / calls))

    # 三桶拆分（按单价估算，用于看结构而不是报账单）
    b_cr = cr / 1e6 * PRICE['cacheRead']
    b_in = inp / 1e6 * PRICE['input']
    b_out = out / 1e6 * PRICE['output']
    tot = b_cr + b_in + b_out
    if tot:
        print('\n成本结构（按单价估算）：缓存重发 %.0f%% / 未命中输入 %.0f%% / 输出 %.0f%%'
              % (b_cr / tot * 100, b_in / tot * 100, b_out / tot * 100))
    if out:
        print('输出里推理 token 占 %.0f%%（说明钱主要花在“想”，而非“写”）' % (rea / out * 100))
    print('\n优化对照点：调用次数（少一次往返就少重发一整段上下文）、未命中输入（每次新塞进来的内容）、'
          '每调用平均输出')


if __name__ == '__main__':
    main()
