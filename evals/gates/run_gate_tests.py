#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_gate_tests.py —— 门禁／闸门脚本**自己的**回归测试（零 token）

为什么必须有（2026-10-07，一天之内改了四个门禁脚本）：
    这一轮我改了 `check_markup`／`check_paragraph_map`／`preflight_probe`／`check_idiom`，
    每次都是「临时拿一本真书看看报不报」——那不是测试，是赌。
    **修一个门禁而它自己没有测试，等于把「修 bug」换成「换 bug」。**
    本文件给每个脚本配「已知好样本 + 已知坏样本」的固定用例，改脚本必跑。

用法：
    python evals/gates/run_gate_tests.py            # 跑全部
    python evals/gates/run_gate_tests.py -k markup  # 只跑名字含 markup 的用例
退出码：有失败 1，全过 0。
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, "scripts"))
PY = sys.executable


def run(script, args, cwd=None):
    p = subprocess.run([PY, os.path.join(SCRIPTS, script)] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


# ----------------------------------------------------------------- 用例
def t_markup(tmp):
    good = os.path.join(tmp, "markup_good.md")
    bad = os.path.join(tmp, "markup_bad.md")
    esc = os.path.join(tmp, "markup_esc.md")
    lat = os.path.join(tmp, "markup_latin_tag.md")
    w(good, "# 标题\n\n他强调过**重点**。\n\n- 第一项\n- 第二项\n\n选项 \\#1 与 \\#2。\n\n---\n\n结束。\n")
    w(bad, "# 标题\n\n他赚更多，*同时*成本更低。\n\n***粗斜体***\n\n选项 #1：把价格翻倍\n\n<table><tr><td>x</td></tr></table>\n")
    w(esc, "他显示的是字面的 \\*\\*星号\\*\\*，不是强调。\n")
    # 2026-10-07 漏网：`#` + **拉丁字母** 也会被 Obsidian 索引成标签（实测漏了 `#Mozination`）
    w(lat, "欢迎来到 #Mozination。\n\n而 \\#Mozination 转义过，不算。\n\n#1 纯数字不成标签，也不算。\n")
    out = []
    rc, s = run("check_markup.py", ["--target", good])
    out.append(("markup 好样本应通过", rc == 0, s.strip()[:80]))
    rc, s = run("check_markup.py", ["--target", bad])
    kinds = [k for k in ["落单星号", "奇数长游程", "井号会成标签", "HTML 表格残留"] if k in s]
    out.append(("markup 坏样本应报 4 类", rc == 1 and len(kinds) == 4, "报出：" + "、".join(kinds)))
    rc, s = run("check_markup.py", ["--target", esc])
    out.append(("markup 转义星号不误报", rc == 0, s.strip()[:80]))
    rc, s = run("check_markup.py", ["--target", lat])
    out.append(("拉丁字母井号应报标签（纯数字与转义的不报）",
                rc == 1 and s.count("井号会成标签") == 1, s.strip()[:90]))
    return out


def t_unit(tmp):
    bad = os.path.join(tmp, "unit_bad.md")
    good = os.path.join(tmp, "unit_good.md")
    w(bad, "每周要花 $1,000/wk，总量到 $3.5B。\n")
    w(good, "他读的是《100M 商业书》。\n")
    out = []
    rc, s = run("check_unit_residue.py", ["--target", bad])
    out.append(("单位残渣应报出", rc == 1, s.strip().splitlines()[-1][:80]))
    rc, s = run("check_unit_residue.py", ["--target", good])
    out.append(("书名里的 100M 不误报", rc == 0, s.strip()[:80]))
    model = os.path.join(tmp, "unit_model.md")
    w(model, "MQ-9B 死神无人机。\n")
    rc, s = run("check_unit_residue.py", ["--target", model])
    out.append(("型号 MQ-9B 中的 9B 不误报", rc == 0, s.strip()[:80]))
    return out


def t_numbers(tmp):
    s = os.path.join(tmp, "num.txt")
    b = os.path.join(tmp, "num_bad.md")
    g = os.path.join(tmp, "num_good.md")
    w(s, "Price is 80% off today.\n")
    w(b, "今天打 8 折。\n")          # 方向错：80% off = 打 2 折
    w(g, "今天打 2 折。\n")
    out = []
    rc, s2 = run("check_numbers.py", ["--source", s, "--target", b])
    out.append(("折扣方向错应报警", rc == 1, s2.strip().splitlines()[-1][:80]))
    rc, s2 = run("check_numbers.py", ["--source", s, "--target", g])
    out.append(("折扣方向对应通过", rc == 0, s2.strip().splitlines()[-1][:80]))
    return out


def t_paragraph(tmp):
    s = os.path.join(tmp, "p.txt")
    ok = os.path.join(tmp, "p_ok.md")
    merged = os.path.join(tmp, "p_merged.md")
    w(s, "第一段结束。\n\n第二段结束。\n\n第三段结束。\n")
    w(ok, "第一段结束。\n\n第二段结束。\n\n第三段结束。\n")
    w(merged, "第一段结束。第二段结束。第三段结束。\n")
    out = []
    rc, s2 = run("check_paragraph_map.py", ["--source", s, "--target", ok])
    out.append(("段数一致应通过", rc == 0, s2.strip().splitlines()[-1][:80]))
    rc, s2 = run("check_paragraph_map.py", ["--source", s, "--target", merged])
    out.append(("并段应报错", rc == 1, s2.strip().splitlines()[-1][:80]))
    rc, s2 = run("check_paragraph_map.py", ["--source", s, "--target", merged, "--tolerance", "50%"])
    out.append(("容差放宽后应通过", rc == 0, s2.strip().splitlines()[-1][:80]))
    # 2026-10-24 修：--tolerance 0.25 过去直接抛 ValueError traceback，现在应是 argparse 友好报错
    rc, s2 = run("check_paragraph_map.py", ["--source", s, "--target", merged,
                                            "--tolerance", "0.25"])
    out.append(("--tolerance 小数应友好报错、不抛 traceback",
                rc == 2 and "只接受整数或百分比" in s2 and "Traceback" not in s2,
                s2.strip()[-100:]))
    # 反作弊：源文页码标记被搬进译文时，段数可能仍然一致；必须单独报错
    srcmeta = os.path.join(tmp, "p_src_meta.txt")
    tgtmeta = os.path.join(tmp, "p_tgt_meta.md")
    w(srcmeta, "[PDF 第 1 页]\n\n第一段结束。\n\n[PDF 第 2 页]\n\n第二段结束。\n")
    w(tgtmeta, "[PDF 第 1 页]\n\n第一段结束。\n\n[PDF 第 2 页]\n\n第二段结束。\n")
    rc, s2 = run("check_paragraph_map.py", ["--source", srcmeta, "--target", tgtmeta])
    out.append(("译文含页码标记应报错",
                rc == 1 and "元数据标记" in s2,
                s2.strip().splitlines()[-1][:80]))
    # 强调标记收尾的正文段：`*increase LTV.*` 应以 `.*` 判为句末，不能当标签排除
    emsrc = os.path.join(tmp, "p_em_src.txt")
    emtgt = os.path.join(tmp, "p_em_tgt.md")
    w(emsrc, "*increase LTV.*\n")
    w(emtgt, "**提升 LTV。**\n")
    rc, s2 = run("check_paragraph_map.py", ["--source", emsrc, "--target", emtgt, "--json"])
    em_ok = rc == 0 and '"src_paras": 1' in s2
    out.append(("强调标记收尾的正文段应计入", em_ok, s2.strip()[:80]))
    return out


def t_idiom(tmp):
    td = os.path.join(tmp, "terms")
    bd = os.path.join(tmp, "book")          # check_idiom 需要 source_en/ 与 zh/ 同时在
    w(os.path.join(td, "x.md"),
      "# 类型库\n\n## 习语与句式\n\n| 英文 | 中文 | 出处 | 备注 |\n|---|---|---|---|\n"
      "| race to the bottom | 杀价到底 | 测试 | 不写「向下比烂的比赛」 |\n")
    w(os.path.join(bd, "source_en", "a.txt"), "Competition becomes a race to the bottom.\n")
    w(os.path.join(bd, "source_en", "b.txt"), "Competition becomes a race to the bottom.\n")
    w(os.path.join(bd, "zh", "a.md"), "竞争最后变成一场向下比烂的比赛。\n")
    w(os.path.join(bd, "zh", "b.md"), "竞争最后变成一场杀价到底的比拼。\n")
    out = []
    rc, s = run("check_idiom.py", ["--dir", bd, "--terms-dir", td])
    out.append(("习语错译应命中", rc == 1 and "向下比烂的比赛" in s, s.strip().splitlines()[-1][:80]))
    # 术语库为空时应优雅提示、不崩；显式给空目录，避免受本机 MBX_TERMS_DIR 影响
    empty_td = os.path.join(tmp, "terms_empty")
    os.makedirs(empty_td, exist_ok=True)
    rc2, s2 = run("check_idiom.py", ["--dir", bd, "--terms-dir", empty_td])
    out.append(("术语库缺失时应优雅提示不崩", rc2 == 0 and "习语表为空" in s2, s2.strip().splitlines()[-1][:80]))
    return out


def t_preflight(tmp):
    wrapped = os.path.join(tmp, "wrapped.txt")
    glued = os.path.join(tmp, "glued.txt")
    lines = []
    for i in range(60):
        lines.append("this paragraph continues on")
        lines.append("the next line because it is hard wrapped")
        lines.append("")
    w(wrapped, "\n".join(lines))
    lines = ["line %d of one giant glued block without any paragraph break at all" % i
             for i in range(200)]
    w(glued, "\n".join(lines))
    out = []
    rc, s = run("preflight_probe.py", [wrapped, "--json"])
    out.append(("硬折行/段落已成形应判 Ⅰ 档", '"grade": "I"' in s, s.strip()[:90]))
    rc, s = run("preflight_probe.py", [glued, "--json"])
    out.append(("整篇粘连应判 Ⅲ 档", '"grade": "III"' in s, s.strip()[:90]))
    return out


def t_unwrap(tmp):
    """`unwrap_paragraphs.py --no-split` 的页码断段规则（2026-10-07 实战补）。

    病灶：PDF 提取把 `[PDF 第 X 页]` 单独放一行、前后都不空行，一个「空行块」里
    常夹着两段正文。判据（印刷事实）：跨页续接时页末行几乎排满；段落末尾才留白。
    """
    import re
    f = os.path.join(tmp, "pm.txt")
    body = ["p" * 66, "q" * 64, "r" * 65, "s" * 63]      # 撑出满行宽 W≈65
    body += ["short line that ends here."]                # 段落末行：短 + 有句末标点
    body += ["[PDF 第 1 页]"]
    body += ["Brand new paragraph after the break."]
    body += [""]
    body += ["another near full line without any ending punctuation mark at all xxx"]  # 近满行、无句末标点
    body += ["[PDF 第 2 页]"]
    body += ["continued mid sentence text"]
    w(f, "\n".join(body) + "\n")

    rc, s = run("unwrap_paragraphs.py", ["--file", f, "--no-split", "--apply"])
    txt = open(f, encoding="utf-8").read()
    blks = [b for b in re.split(r"\n\s*\n", txt) if b.strip()]
    out = []
    out.append(("--no-split 应通过零改写自检", rc == 0 and "零改写校验失败" not in s,
                s.strip().splitlines()[-1][:80]))
    # 期望 3 块：第 1 组在页码处断成 2 块，第 2 组跨页续接保持 1 块
    out.append(("块数应为 3（1 处断段 + 1 处续接）", len(blks) == 3,
                "块数=%d" % len(blks)))
    out.append(("页前段末行 + 页码标记应同居首块",
                len(blks) == 3 and "short line that ends here." in blks[0]
                and "[PDF 第 1 页]" in blks[0],
                repr(blks[0][-60:]) if blks else ""))
    out.append(("新段应与页前段分开（短行+句末标点 → 断段）",
                len(blks) == 3 and blks[1].strip() == "Brand new paragraph after the break.",
                repr(blks[1][:70]) if len(blks) > 1 else ""))
    out.append(("跨页续接不应断段（满行+无句末标点 → 同块）",
                len(blks) == 3 and "another near full line" in blks[2]
                and "continued mid sentence" in blks[2] and "[PDF 第 2 页]" in blks[2],
                repr(blks[2][:70]) if len(blks) > 2 else ""))
    out.append(("页码标记本应保留在文内（零改写）",
                "[PDF 第 1 页]" in txt and "[PDF 第 2 页]" in txt, ""))
    return out


def t_patch(tmp):
    """闸门 `patch_preview.py` 自己：它是最危险的一个脚本，三道保险必须都在。"""
    d = os.path.join(tmp, "patchbook", "zh")
    f = os.path.join(d, "01.md")
    w(f, "他赚更多，**同时**成本更低。\n")
    out = []
    # ① 不给 --expect 就落盘 → 拒绝，且文件不变
    rc, s = run("patch_preview.py", ["--book-dir", os.path.dirname(d),
                                     "--find", "同时", "--replace", "同时地", "--apply"])
    out.append(("缺 --expect 应被拒", rc == 1 and "必须同时给" in s, s.strip().splitlines()[-1][:80]))
    out.append(("被拒后文件未被改", open(f, encoding="utf-8").read().startswith("他赚更多，**同时**"), ""))
    # ② 危险正则（会把 **粗体** 吃成 ***粗体***）→ 校验变差 → 回滚
    rc, s = run("patch_preview.py", ["--book-dir", os.path.dirname(d),
                                     "--find", r"\*([^*\n]{1,60})\*", "--replace", r"**\1**",
                                     "--expect", "1", "--apply"])
    body = open(f, encoding="utf-8").read()
    out.append(("危险正则应被回滚", rc == 1 and "回滚" in s and "***" not in body,
                "rc=%d 回滚字样=%s 文件=%r" % (rc, "回滚" in s, body[:40])))
    # ③ 安全替换 → 落盘
    rc, s = run("patch_preview.py", ["--book-dir", os.path.dirname(d),
                                     "--find", "同时", "--replace", "同时也", "--expect", "1", "--apply"])
    body = open(f, encoding="utf-8").read()
    out.append(("安全替换应落盘", rc == 0 and "同时也" in body, "rc=%d 文件=%r" % (rc, body[:40])))
    return out


def t_slice(tmp):
    """`build_slice.py`：类型库标题 `## 类型术语表` 旧正则认不出来（2026-10-24 修），这里钉住。

    另钉两条：类型库习语照常命中；`## 语义不变量` 栏不参与切片（它走 FORMAT_BLOCK）。
    """
    d = os.path.join(tmp, "slice", "_术语体系")
    w(os.path.join(d, "alex.md"),
      "# 作者档案\n\n## 术语表（作者统一译法）\n\n"
      "| 英文 | 中文 | 备注 |\n|------|------|------|\n| offer | 方案 | 销售语境 |\n\n"
      "## 术语例外清单（书级例外）\n\n"
      "| 书名 | 术语 | 本书译法 | 作者标准 | 原因 |\n|------|------|---------|---------|------|\n"
      "| 《某书》 | lead | 潜在客户 | 潜在客户 | 书级例外 |\n")
    w(os.path.join(d, "business.md"),
      "# 类型术语库\n\n## 类型术语表\n\n"
      "| 英文 | 中文 | 备注 |\n|------|------|------|\n| lead | 潜在客户 | |\n\n"
      "## 习语与句式（本类型通用）\n\n"
      "| 英文习语／句式 | 中文现成说法 | 出处 | 备注 |\n|------|------|------|------|\n"
      "| race to the bottom | 逐底竞赛 | business | 不写「向下比烂的比赛」 |\n\n"
      "## 语义不变量（本类型的意译边界）\n\n"
      "| 英文 | 中文 |\n|------|------|\n| offer | 不该出现的切片 |\n")
    ch = os.path.join(tmp, "slice", "source_en", "01.md")
    w(ch, "The lead made an offer, and the race to the bottom followed.\n")
    rc, s = run("build_slice.py", ["--chapter", ch, "--author", "alex",
                                   "--type", "business", "--terms-dir", d])
    out = []
    out.append(("类型库术语应被解析（作者 1 + 类型 1）", "术语 2 / 2 条" in s, s.strip()[:120]))
    out.append(("术语备注（语境条件）应进切片", "（销售语境）" in s, s.strip()[:120]))
    out.append(("类型库习语应命中", "race to the bottom→逐底竞赛" in s, s.strip()[:120]))
    out.append(("语义不变量表不应进切片", "不该出现的切片" not in s, s.strip()[:120]))
    return out


def t_clean_flat_lists(tmp):
    """`clean_flat_lists.py` 默认后缀必须命中现行 `zh/NN_名字.md`。

    2026-10-24 修：旧默认 `_重译版.md` 在现行命名下匹配 0 个文件并退出 0（静默失效）。
    这里钉住四件事：默认处理 .md、默认 dry-run 不落盘、--apply 真删、无匹配时非 0 退出。
    """
    zh = os.path.join(tmp, "flatbook", "zh")
    items = ["- 这是第一条重复清单内容，长度足够触发阈值。",
             "- 这是第二条重复清单内容，长度足够触发阈值。",
             "- 这是第三条重复清单内容，长度足够触发阈值。"]
    text = ("正文第一段，长度也足够。\n\n" + "\n".join(items) +
            "\n\n正文第二段，长度也足够。\n\n" + "\n".join(items) +
            "\n\n正文第三段，长度也足够。\n")
    f = os.path.join(zh, "01.md")
    w(f, text)
    out = []
    rc, s = run("clean_flat_lists.py", ["--dir", zh, "--min-len", "8"])
    before = open(f, encoding="utf-8").read()
    out.append(("clean_flat_lists 默认后缀应处理 .md（不是只认 _重译版.md）",
                rc == 0 and "合计：1 个文件" in s, s.strip()[-120:]))
    out.append(("clean_flat_lists 默认 dry-run 不落盘", before == text, "文件被改动"))
    rc, s = run("clean_flat_lists.py", ["--dir", zh, "--min-len", "8", "--apply"])
    after = open(f, encoding="utf-8").read()
    out.append(("clean_flat_lists --apply 应删除重复清单",
                rc == 0 and after.count("这是第一条") == 1,
                "剩余第一条 %d 次" % after.count("这是第一条")))
    empty = os.path.join(tmp, "flatbook", "empty")
    os.makedirs(empty, exist_ok=True)
    rc, s = run("clean_flat_lists.py", ["--dir", empty])
    out.append(("clean_flat_lists 没有匹配文件应报错而非静默退出 0",
                rc == 2 and "未匹配到任何文件" in s, "rc=%d" % rc))
    return out


def t_normalize(tmp):
    src = os.path.join(tmp, "norm_in.md")
    out = os.path.join(tmp, "norm_out.md")
    w(src, '"你好" 和 "世界"\n')
    rc, s = run("normalize_symbols.py", [src, out])
    txt = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
    return [("ASCII 引号应成对转中文引号",
             rc == 0 and "「你好」 和 「世界」" in txt, txt.strip()[:80])]


def t_ocr(tmp):
    rc, s = run("ocr_pdf.py", ["--help"])
    return [("OCR 驱动 --help 应通过", rc == 0 and "--md-out" in s, s.strip()[:80])]


def t_rare(tmp):
    good = os.path.join(tmp, "rare_good.md")
    bad = os.path.join(tmp, "rare_bad.md")
    w(good, "这是一段普通中文。\n")
    w(bad, "宏碁是一家公司。\n")
    out = []
    rc, s = run("check_rare_chars.py", ["--target", good])
    out.append(("普通中文应通过", rc == 0, s.strip()[:80]))
    rc, s = run("check_rare_chars.py", ["--target", bad])
    out.append(("专名字符应报出", rc == 1, s.strip()[:80]))
    rc, s = run("check_rare_chars.py", ["--target", bad, "--allow", "碁"])
    out.append(("--allow 后专名不报", rc == 0, s.strip()[:80]))
    return out


def t_plan(tmp):
    bd = os.path.join(tmp, "planbook")
    se = os.path.join(bd, "source_en")
    os.makedirs(se, exist_ok=True)
    w(os.path.join(se, "01.txt"), ("word " * 100) + "\n")
    w(os.path.join(se, "02.txt"), ("word " * 120) + "\n")
    rc, s = run("plan_batches.py", ["--book-dir", bd, "--context-window", "200000",
                                    "--fixed-overhead", "10000", "--json"])
    return [("按上下文窗口分派任务应输出任务组", rc == 0 and '"total_chapters": 2' in s
             and '"batches"' in s, s.strip()[:90])]


ALL = [("markup", t_markup), ("unit", t_unit), ("numbers", t_numbers),
       ("paragraph", t_paragraph), ("normalize", t_normalize), ("idiom", t_idiom),
       ("preflight", t_preflight), ("unwrap", t_unwrap), ("patch", t_patch),
       ("slice", t_slice), ("clean_flat_lists", t_clean_flat_lists), ("ocr", t_ocr),
       ("rare", t_rare), ("plan", t_plan)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="只跑名字含该串的用例")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="gatetest_")
    fails, checks, groups = 0, 0, 0
    try:
        for name, fn in ALL:
            if a.k and a.k not in name:
                continue
            groups += 1
            print("== %s ==" % name)
            for label, ok, note in fn(tmp):
                checks += 1
                print("   %s %s%s" % ("✓" if ok else "✗", label, "" if ok else "   ← " + note))
                if not ok:
                    fails += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n结果：%s（%d 条断言 / %d 个用例组）"
          % ("全部通过" if fails == 0 else "%d 条断言失败" % fails, checks, groups))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
