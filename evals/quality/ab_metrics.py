#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_metrics.py —— 两个译文目录的翻译腔指标对比（零 token）

口径与 `scripts/check_fluency.py` 完全一致（直接复用它的 metrics()），
区别是这里算的是**跨段的加权均值**，用来做「版本 A vs 版本 B」的对照，
而不是单本书内部的 z-score 排序。

用法：
    python ab_metrics.py --a <目录A> --b <目录B> [--label-a A] [--label-b B]
"""
import argparse
import glob
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CF = os.path.join(HERE, os.pardir, os.pardir, "scripts", "check_fluency.py")
spec = importlib.util.spec_from_file_location("cf", CF)
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)

KEYS = ["de", "dbl", "pron_de", "sent_len", "long_rate", "bei", "light", "pair", "prep"]
PER_SENT = {"sent_len", "long_rate"}
LABEL = {
    "de": "的字/千字", "dbl": "双重修饰/百句", "pron_de": "代词+的/千字",
    "sent_len": "平均句长", "long_rate": "长句率", "bei": "被字句/千字",
    "light": "虚化动词/千字", "pair": "配对连词/千字", "prep": "介词框架/千字",
}


def measure(d):
    text = "\n\n".join(io.open(f, encoding="utf-8").read()
                       for f in sorted(glob.glob(os.path.join(d, "*.md"))))
    segs = [s for s in cf.segments(text) if cf.is_prose(s)]
    ms = [cf.metrics(s) for s in segs]
    ms = [m for m in ms if m]
    han = sum(m["han"] for m in ms)
    sent = sum(m["sent"] for m in ms)
    out = {"han": han, "segs": len(ms)}
    for k in KEYS:
        denom = sent if k in PER_SENT else han
        out[k] = sum(m[k] * (m["sent"] if k in PER_SENT else m["han"]) for m in ms) / denom if denom else 0.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()

    ra, rb = measure(args.a), measure(args.b)
    print("  %-16s %10s %10s %8s" % ("指标", args.label_a, args.label_b, "变化"))
    print("  " + "-" * 48)
    print("  %-16s %10d %10d" % ("中文字", ra["han"], rb["han"]))
    win = 0
    for k in KEYS:
        d = rb[k] - ra[k]
        mark = "↓ 更低" if d < 0 else ("↑ 更高" if d > 0 else "＝")
        if d < 0:
            win += 1
        print("  %-16s %10.2f %10.2f %8s" % (LABEL[k], ra[k], rb[k], mark))
    print("\n  %s 比 %s 更低的指标数：%d / %d（越低越不像翻译腔）"
          % (args.label_b, args.label_a, win, len(KEYS)))


if __name__ == "__main__":
    sys.exit(main())
