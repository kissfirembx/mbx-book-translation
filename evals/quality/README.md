# quality —— 质量对照 harness

只放工具，不附语料、不附真实书译稿。

## run_quality_checks.py

按 `expectations.json` 的 `min` / `max` 正则断言，逐份译稿统计命中率。

```bash
python evals/quality/run_quality_checks.py --expect <expectations.json> --dir <译文目录>
```

`expectations.json` 格式：

```json
{
  "suite": "my_suite",
  "cases": [
    {"id": "idiom-x", "why": "这条在验什么",
     "min": {"规定说法": 1},
     "max": {"错误说法": 0},
     "file": "可选：只作用于文件名含该串的译稿"}
  ]
}
```

## ab_metrics.py

两个译文目录的翻译腔指标对比；口径与 `scripts/check_fluency.py` 一致。

```bash
python evals/quality/ab_metrics.py --a <目录A> --b <目录B> --label-a A --label-b B
```

样本量不足时不要下流畅度结论；先看 `evals/README.md` 的分层规则。
