#!/usr/bin/env python3
"""qa_report.py —— 末端「人在回路」质检报告（六类：①②③④⑤⑥）

扫描 draft MD，按六类问题汇总「数量 + 行号 + 类型 + 示例」，生成 problem_report.md。
不贴全文，供用户复核 + 触发预设修复。
用法：python qa_report.py <IN_MD> <OUT_REPORT.md>

注：报告定位用「行号」（当前不解析 PDF 页码）。
注：第 ⑦ 类「段落边界/形态错配」不由本脚本负责，由 check_paragraph_map.py 单独门禁。
"""
import argparse, re, os

TERM = "。！？；：”》）」』…"   # 含省略号：以「……」结尾视为语义完整

# ② 断句候选的排除规则：标题/表格/引用/列表/图注/短行不是断句
SKIP_PREFIX = ("#", "|", ">", "-", "*", "+", "!", "```", "~~~", "<", "©", "（", "(")
CAPTION_RE = re.compile(r"^(图|表|图\s*\d|表\s*\d|注[:：]|数据来源|资料来源|来源)")
# 引用 + 署名（如 「……」——Ernest Hemingway）
ATTRIB_RE = re.compile(r'[」』”"’\']\s*—{1,2}\s*\S+$')
# 列表式标题（报价 #1 xxx / 第N分部：xxx）
LISTTITLE_RE = re.compile(r'^.{0,12}(#\s*\d+|第[一二三四五六七八九十百零\d]+[分部件])')
# 版权/出版信息行、算式行——都不是断句
COPYRIGHT_RE = re.compile(r'(版权|©|ISBN|封面设计|All rights reserved|\bLLC\b|Lane|TX \d{5})')
FORMULA_RE = re.compile(r'[=×÷]|\$\d')

# ⑤ 非书籍内容：翻译时把会话上下文写进译文（历史案例：某书成品标题被会话文本污染）
# 只保留强特征词，避免「你需要」「我们来看」等正常表述误报
CHAT_PAT = re.compile(r"(我的项目|我跟你说|请帮我|接下来我|根据你|你可以看到|综上所述，我|首先，我的)")

# ⑥ 图片引用：必须带前缀 ./figs/（章节在书根）或 ../figs/（章节在 zh/ 下）
# 历史案例：4 本书共 415 处裸文件名断链；2026-09 起章节文件放 zh/ 子目录，只放行 ./figs/ 会把正确引用全部误报
FIG_BARE_RE = re.compile(r'!\[[^\]]*\]\((?!\.{1,2}/figs/)[^)]+\.(png|jpg|jpeg|webp|gif)\)', re.I)


def is_break_candidate(line: str) -> bool:
    s = line.strip()
    if not s or s[-1] in TERM:
        return False
    if s.startswith(SKIP_PREFIX):
        return False
    if CAPTION_RE.match(s):
        return False
    if ATTRIB_RE.search(s):                       # 引用 + 署名
        return False
    if LISTTITLE_RE.match(s):                     # 列表式标题
        return False
    if s.startswith("—"):                          # 推荐语署名
        return False
    if COPYRIGHT_RE.search(s) or FORMULA_RE.search(s):
        return False
    if set(s) <= set("_—-·.． \t"):                 # 填空下划线行（练习作答区）
        return False
    if "→" in s or "->" in s:                       # 结构对照行（如「问题 → 解决方案」）
        return False
    if s[0] in "「『“" and s[-1] in "」』”":        # 纯引用行
        return False
    if re.match(r"^(\d+[.、)）]|第[一二三四五六七八九十百零\d]+[章节部篇]|[（(]?\d+[)）])", s):
        return False
    if len(s) <= 8:          # 短行多为标题/标签/图注
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_md")
    ap.add_argument("out_report")
    a = ap.parse_args()
    text = open(a.in_md, encoding="utf-8").read()
    lines = text.splitlines()

    # ② 换行/断句：句尾无终结标点，且不是标题/表格/引用/列表/短行
    break_c = [[i + 1, l] for i, l in enumerate(lines) if is_break_candidate(l)]
    # ③ 排版混乱：疑似假表格（行内大量竖线但多为空）
    fake_t = [[i + 1, l] for i, l in enumerate(lines)
              if l.strip().startswith("|") and sum(1 for c in l if c == "|") > 8]
    # ① 识别错误：可疑字形（排除图片引用行——`p33.png` 这类文件名会误报）
    susp = [[i + 1, l] for i, l in enumerate(lines)
            if not l.strip().startswith("![")
            and re.search(r"[a-zA-Z]\d|\d[a-zA-Z]|(?:l|I|O)\d|\d(?:l|I|O)", l)]
    # ④ 图注未绑定：`> ` 行内容像图注（图/表/来源/注）但前一行不是图片
    cap_orphan = [[i + 1, l] for i, l in enumerate(lines)
                  if l.strip().startswith("> ")
                  and CAPTION_RE.match(l.strip()[2:].strip())
                  and (i == 0 or not lines[i - 1].strip().startswith("!["))]
    # ⑤ 非书籍内容：标题行含会话强特征词，或极端超长标题（>120 字符）
    chat_leak = [[i + 1, l] for i, l in enumerate(lines)
                 if l.strip().startswith("#")
                 and (CHAT_PAT.search(l) or len(l.strip()) > 120)]
    # ⑥ 图片引用缺前缀（./figs/ 或 ../figs/）
    fig_bare = [[i + 1, l] for i, l in enumerate(lines) if FIG_BARE_RE.search(l)]

    rep = ["# QA 问题报告（人在回路）", "",
           f"- 检查文件：`{os.path.basename(a.in_md)}`",
           f"- ①识别错误疑似：**{len(susp)}** 处",
           f"- ②换行/断句疑似：**{len(break_c)}** 处",
           f"- ③排版混乱疑似：**{len(fake_t)}** 处",
           f"- ④图片注释疑似：**{len(cap_orphan)}** 处",
           f"- ⑤非书籍内容疑似：**{len(chat_leak)}** 处",
           f"- ⑥图片引用缺前缀（./figs/ 或 ../figs/）：**{len(fig_bare)}** 处", "",
           "## ② 换行/断句（前 15）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in break_c[:15]:
        rep.append(f"| {ln} | {c[:60]} |")
    rep += ["", "## ③ 排版混乱（前 10）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in fake_t[:10]:
        rep.append(f"| {ln} | {c[:60]} |")
    rep += ["", "## ① 识别错误（前 15）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in susp[:15]:
        rep.append(f"| {ln} | {c[:60]} |")
    rep += ["", "## ④ 图片注释（前 10）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in cap_orphan[:10]:
        rep.append(f"| {ln} | {c[:60]} |")
    rep += ["", "## ⑤ 非书籍内容（前 10）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in chat_leak[:10]:
        rep.append(f"| {ln} | {c[:60]} |")
    rep += ["", "## ⑥ 图片引用缺前缀（前 10）", "| 行 | 内容 |", "|---|---|"]
    for ln, c in fig_bare[:10]:
        rep.append(f"| {ln} | {c[:60]} |")
    open(a.out_report, "w", encoding="utf-8").write("\n".join(rep))
    print(f"OK qa_report -> {a.out_report}")


if __name__ == "__main__":
    main()
