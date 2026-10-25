#!/usr/bin/env python3
"""normalize_symbols.py —— 符号规范化（问题①③）

书名号/引号/破折号/全半角统一；英文对话/英文词引号白名单保留。规则表默认读 references/data/symbols.json。
用法：python normalize_symbols.py <IN_MD> <OUT_MD> [--data symbols.json]
"""
import argparse, json, re, os

# 规则表默认路径：skill 根目录下的 references/data/symbols.json（可用 --data 覆盖）
DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'data', 'symbols.json')

DEFAULT = {
    "replace": {"一一－": "——", "＞＞": "》", "＇": "」", "｀": "「",
                "--": "——", "…": "……"},
    "quotes_cn": ["「", "」"],
    "quotes_en_whitelist": ['"Thank you"', '"Money"', '"Incredible India"', '"monsoon"', '"One India, One rupee"'],
}


def load_cfg(path):
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    if path:
        print(f"提示：规则表 {path} 不存在，改用脚本内建基线表")
    return DEFAULT


def norm(text, cfg):
    for bad, good in cfg.get("replace", {}).items():
        text = text.replace(bad, good)
    # 英文引号白名单保护
    for q in cfg.get("quotes_en_whitelist", []):
        text = text.replace(q, q.replace('"', "\u0001"))
    # 其余 ASCII 双引号按出现顺序配对为中文开/闭引号
    quotes = cfg.get("quotes_cn", ["「", "」"])
    q_open, q_close = (quotes + ["「", "」"])[:2]
    buf = []
    open_q = True
    for ch in text:
        if ch == '"':
            buf.append(q_open if open_q else q_close)
            open_q = not open_q
        else:
            buf.append(ch)
    text = "".join(buf)
    text = text.replace("\u0001", '"')
    # 半角标点 -> 全角（数字/英文保留半角）
    text = re.sub(r"([^A-Za-z0-9\s])[\.,;:!?]", r"\1。", text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_md")
    ap.add_argument("out_md")
    ap.add_argument("--data", default=DEFAULT_DATA, help="规则表路径（默认 data/symbols.json）")
    a = ap.parse_args()
    text = open(a.in_md, encoding="utf-8").read()
    cfg = load_cfg(a.data)
    open(a.out_md, "w", encoding="utf-8").write(norm(text, cfg))
    print("OK normalize_symbols ->", a.out_md)


if __name__ == "__main__":
    main()
