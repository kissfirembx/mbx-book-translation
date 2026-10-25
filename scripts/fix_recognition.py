#!/usr/bin/env python3
"""fix_recognition.py —— 识别错误自动修正（问题①）

按混淆表定点替换（字面整词），报告低置信/需人工项。规则表默认读 references/data/confusions.json。
用法：python fix_recognition.py <IN_MD> <OUT_MD> [--data confusions.json]
"""
import argparse, json, os

# 规则表默认路径：skill 根目录下的 references/data/confusions.json（可用 --data 覆盖）
DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'data', 'confusions.json')

DEFAULT = {
    "replace": {"IO": "10", "l993": "1993", "ll.8": "1.8", "Ai1tel": "Airtel",
                "fnd1a": "India", "!nd1a": "India", "进人": "进入", "自已": "自己",
                "既使": "即使", "竞然": "竟然", "贷币": "货币", "像征": "象征",
                "一且": "一旦", "日的": "目的", "博土": "博士", "收人": "收入",
                "投人": "投入", "介人": "介入"},
    "manual": ["货款/贷款(看语义，不自动替换)"],
}


def load_cfg(path):
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    if path:
        print(f"提示：规则表 {path} 不存在，改用脚本内建基线表")
    return DEFAULT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_md")
    ap.add_argument("out_md")
    ap.add_argument("--data", default=DEFAULT_DATA, help="规则表路径（默认 data/confusions.json）")
    a = ap.parse_args()
    text = open(a.in_md, encoding="utf-8").read()
    cfg = load_cfg(a.data)
    applied = 0
    for bad, good in cfg.get("replace", {}).items():
        n = text.count(bad)
        if n:
            text = text.replace(bad, good)
            applied += n
    open(a.out_md, "w", encoding="utf-8").write(text)
    print(f"OK fix_recognition -> {a.out_md}；自动替换 {applied} 处")
    for m in cfg.get("manual", []):
        print("  [需人工确认] " + m)


if __name__ == "__main__":
    main()
