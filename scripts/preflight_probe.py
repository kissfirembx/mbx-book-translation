#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight_probe.py —— 源文体检（阶段 2.5，任何源文类型都要跑）

产出：probe.json + probe_report.md

两条路径：
  --kind pdf    版面雷达：逐页字符数/图片数/描边线数/可疑字率 → 判「有无文字层」，决定走提取还是 OCR
  --kind text   成色体检：行末句末标点率/跨行半句率/粘连密度/空格密度/时间码与说话人行数
                → 判源文成色 Ⅰ/Ⅱ/Ⅲ 档，决定「段落边界能不能动」

为什么体检不能只服务 PDF（2026-10-05 实测教训）：
    源是 txt 字幕，就把整节体检跳过了——跳过的理由是「格式不对口」，不是「这一步不需要」。
    结果成色Ⅰ档（已人工校验的规整字幕）和Ⅲ档（粘连乱码的自动字幕）走进同一条管线，
    Ⅰ档本该「段落边界照抄」，却被按书籍规范并段重排，整本返工。

档位判定（阈值依据实测：某已校验 YouTube 讲座字幕 = end_punct 0.972 / cross_line 0.01 / glue 0.2）：
    Ⅲ 档：end_punct_rate < 0.60  或  cross_line_rate > 0.25  或  glue_per_kchar > 2.0
    Ⅰ 档：end_punct_rate ≥ 0.85  且  cross_line_rate ≤ 0.10  且  glue_per_kchar ≤ 1.0
    Ⅱ 档：其余

    （glue 门槛定 2.0 而非 3.0：健康英文的噪声底 ≈ 0.2，来自 YouTube/UChicago/PhD 这类专名；
      2.0 相当于每 500 字符就有一处粘连，已足以让译者误判词边界。）

用法：
    python preflight_probe.py <源文> [--kind auto|pdf|text] [--out OUT_DIR] [--json]
    python preflight_probe.py book.pdf --out ./probe
    python preflight_probe.py 字幕.txt --out ./probe
依赖：PDF 路径需 pymupdf (fitz)
"""
import argparse, json, os, re, sys

TEXT_EXT = {".txt", ".md", ".srt", ".vtt", ".ass", ".ssa", ".json", ".csv"}
PDF_EXT = {".pdf"}


def _need_fitz():
    try:
        import fitz  # noqa
        return fitz
    except ImportError:
        return None


def suspicious_text_rate(text: str) -> float:
    """启发式：文字层可信读度。识别含数字/字母混淆嫌疑的行占比。"""
    pat = re.compile(r"[a-zA-Z]\d|\d[a-zA-Z]|(?:l|I|O)\d|\d(?:l|I|O)")
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    hits = sum(1 for l in lines if pat.search(l))
    return round(hits / len(lines), 4)


# ---------------------------------------------------------------- PDF 路径

def probe_pdf(pdf_path: str):
    fitz = _need_fitz()
    if not fitz:
        raise SystemExit("PDF 路径需要 pip install pymupdf")
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        img_count = len(page.get_images(full=True))
        try:
            draws = page.get_drawings()
            line_cnt = sum(1 for d in draws if d.get("type") in ("l", "re"))
        except Exception:
            line_cnt = 0
        img_rects = []
        try:
            for d in page.get_image_info():
                img_rects.append([round(v) for v in d.get("bbox", [0, 0, 0, 0])])
        except Exception:
            pass
        pages.append({
            "page": i + 1,
            "chars": len(text),
            "images": img_count,
            "lines": line_cnt,
            "susp": suspicious_text_rate(text),
            "img_bboxes": img_rects,
        })
    doc.close()
    total_chars = sum(p["chars"] for p in pages)
    n = len(pages)
    per = total_chars / max(n, 1)
    scan = per < 50
    return {"kind": "pdf", "pages": n, "total_chars": total_chars,
            "chars_per_page": round(per, 1), "is_scan": scan, "page_data": pages}


# ---------------------------------------------------------------- 文本路径

_TS = re.compile(r'^\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->|^\s*\d{1,2}:\d{2}:\d{2}\s*-->')
_ONLY_NUM = re.compile(r'^\s*\d+\s*$')
_SPEAKER = re.compile(r'^\s*[A-Z][A-Za-z .\'\-]{0,24}:\s')


def _text_lines(text):
    """去掉 srt/vtt 的序号行与时间码行，返回正文行。"""
    out, timecodes = [], 0
    for l in text.splitlines():
        if _TS.search(l):
            timecodes += 1
            continue
        if _ONLY_NUM.match(l):
            continue
        if l.strip():
            out.append(l.rstrip())
    return out, timecodes


def probe_text(path: str):
    raw = open(path, encoding="utf-8", errors="replace").read()
    lines, timecodes = _text_lines(raw)
    n = len(lines)
    chars = sum(len(l) for l in lines)
    end_punct = sum(1 for l in lines if re.search(r'[.!?。！？…][”"\'’」』）)\]]*$', l))
    lower_start = 0
    for a, b in zip(lines, lines[1:]):
        if not re.search(r'[.!?。！？…][”"\'’」』）)\]]*$', a) and re.match(r'^[a-z]', b):
            lower_start += 1
    glue = len(re.findall(r'[a-z][A-Z]', " ".join(lines)))
    spaces = sum(l.count(" ") for l in lines)
    speakers = sum(1 for l in lines if _SPEAKER.match(l))
    # 段均行数：区分「段内硬折行」与「真粘连断句」——两者都让行末标点率低，但处置完全相反。
    # 硬折行：段落边界完好（空行分隔），只是段内换了行 → **照抄段落，什么都不用做**。
    # 真粘连：整篇挤成一块（段数极少），才需要按标点重组段落。
    paras = len([b for b in re.split(r'\n\s*\n', raw) if b.strip()])
    m = {
        "lines": n,
        "paras": paras,
        "lines_per_para": round(n / max(paras, 1), 1),
        "total_chars": chars,
        "avg_chars": round(chars / max(n, 1), 1),
        "end_punct_rate": round(end_punct / max(n, 1), 3),
        "cross_line_rate": round(lower_start / max(n - 1, 1), 3),
        "glue_per_kchar": round(glue * 1000 / max(chars, 1), 2),
        "space_density": round(spaces / max(chars, 1), 3),
        "timecode_lines": timecodes,
        "speaker_lines": speakers,
    }
    m["grade"], m["grade_reason"] = grade_of(m)
    return {"kind": "text", **m}


def grade_of(m):
    bad = (m["end_punct_rate"] < 0.60 or m["cross_line_rate"] > 0.25
           or m["glue_per_kchar"] > 2.0)
    # 硬折行判别（2026-10-07 实战补）：段落边界完好、只是段内换行时，
    # 行末标点率天然低，但**绝不能按Ⅲ档去重组段落**——那会把好书的段落边界改掉。
    # 判据：空行分段够多（≥50）且段均行数 ≤4，且不是字幕（无时间码）。
    # 段落已成形（一段一到两行）时，行末标点率天然会被**结构行**拉低——标题、页码标记、
    # 署名、`Pro Tip:` 这类行本来就不以句末标点收尾。此时 end_punct_rate 已经不是在量粘连，
    # 所以判据只看「段均行数」：段均 ≤4 行＝段落边界完好（2026-10-07《某商业书》实测：
    # 硬折行源文重组后 段均 1.2 行，却因 end_punct 0.53 被判 Ⅲ 档）。
    # 阈值取 8 行：真正的「整篇挤成一块」是**几十到上百行/段**（实测某章 141 行/段），
    # 而硬折行源文多在 1–5 行/段，两者相差一个数量级，中间留足余量避免卡边界误判。
    wrapped = (m.get("lines_per_para", 99) <= 8.0
               and m.get("timecode_lines", 0) == 0)
    if bad and wrapped:
        return "I", ("硬折行／段落已成形：段落边界完好（空行分段 %d 个、段均 %.1f 行），只是段内换了行 —— "
                     "**段落边界照抄，不做任何重组**（行末标点率低是折行或结构行造成的，不是粘连）"
                     % (m["paras"], m["lines_per_para"]))
    if bad:
        return "III", "行末标点不足 / 跨行半句过多 / 粘连过密 —— 需翻译前确定性重组段落"
    if (m["end_punct_rate"] >= 0.85 and m["cross_line_rate"] <= 0.10
            and m["glue_per_kchar"] <= 1.0):
        return "I", "分段完整、句末标点齐全、无粘连 —— 段落边界照抄，一段对一段"
    return "II", "介于两者之间 —— 照译，仅缝合「一句被切成两行」处"


GRADE_ADVICE = {
    "I": "成色Ⅰ档：源文段落边界是编辑成果，**照抄，不并不拆**。译者只在词句层工作；编排层不得在译文成形后并段。",
    "II": "成色Ⅱ档：照译；仅在「上一行无句末标点且下一行以小写开头」处做最小合并，其余段落边界不动。",
    "III": "成色Ⅲ档：**翻译前**先做确定性重组（按句末标点／`[n]` 标记把碎行拼成完整段落），过两级零改写校验后再逐行译。",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--kind", default="auto", choices=["auto", "pdf", "text"])
    ap.add_argument("--out", default=".")
    ap.add_argument("--json", action="store_true", help="只打印 JSON，不写文件")
    a = ap.parse_args()

    ext = os.path.splitext(a.src)[1].lower()
    kind = a.kind
    if kind == "auto":
        kind = "pdf" if ext in PDF_EXT else ("text" if ext in TEXT_EXT else "text")

    if kind == "pdf":
        data = probe_pdf(a.src)
    else:
        if ext in (".epub", ".docx"):
            raise SystemExit("EPUB/DOCX 先解包提取为 txt（见 A1 步骤 5–9），再跑 --kind text")
        data = probe_text(a.src)

    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    os.makedirs(a.out, exist_ok=True)
    json.dump(data, open(os.path.join(a.out, "probe.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    L = ["# 问题预案表（阶段 2.5 体检）\n", "- 源文：`%s`" % a.src]
    if data["kind"] == "pdf":
        L += ["- 总页 %d，字符 %d，每页 %s" % (data["pages"], data["total_chars"], data["chars_per_page"]),
              "- 判定：%s\n" % ("扫描（建议 OCR）" if data["is_scan"] else "有文字层（可提取）"),
              "| 页 | 字符 | 图 | 描边线 | 可疑字率 | 备注 |", "|---|---|---|---|---|---|"]
        for p in data["page_data"]:
            note = "可能图片数据图/装饰线" if p["lines"] > 8 else ""
            if p["susp"] > 0.3:
                note += " 文字层可疑"
            L.append("| %d | %d | %d | %d | %s | %s |" % (
                p["page"], p["chars"], p["images"], p["lines"], p["susp"], note))
    else:
        L += ["- 正文行 %d，字符 %d，平均每行 %s 字" % (data["lines"], data["total_chars"], data["avg_chars"]),
              "- 时间码行 %d，说话人标记行 %d" % (data["timecode_lines"], data["speaker_lines"]),
              "",
              "| 指标 | 实测 | 健康值（Ⅰ档） |",
              "|---|---|---|",
              "| 行末句末标点率 `end_punct_rate` | %s | ≥ 0.85 |" % data["end_punct_rate"],
              "| 跨行半句率 `cross_line_rate` | %s | ≤ 0.10 |" % data["cross_line_rate"],
              "| 粘连密度 `glue_per_kchar` | %s /千字符 | ≤ 1.0 |" % data["glue_per_kchar"],
              "| 空格密度 `space_density` | %s | ≥ 0.12 |" % data["space_density"],
              "",
              "**成色档位：%s 档** —— %s" % (data["grade"], data["grade_reason"]),
              "",
              "> %s" % GRADE_ADVICE[data["grade"]],
              "",
              "下一步：把档位写进《翻译任务规格.md》的阶段 2.6 冻结项，并跑 `check_paragraph_map.py` 做交付门禁。"]
    open(os.path.join(a.out, "probe_report.md"), "w", encoding="utf-8").write("\n".join(L))

    if data["kind"] == "pdf":
        print("OK probe.json + probe_report.md ; 分支=%s" % ("OCR" if data["is_scan"] else "提取"))
    else:
        print("OK probe.json + probe_report.md ; 成色=%s 档（%s）" % (data["grade"], data["grade_reason"]))
        print(GRADE_ADVICE[data["grade"]])


if __name__ == "__main__":
    main()
