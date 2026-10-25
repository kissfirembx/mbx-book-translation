#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""综合差错率计算与验收判定（GB/T 19682-2005 第 7.4 条 + 附录 A）

**国标口径**（GB/T 19682-2005《翻译服务译文质量要求》）：
  - 附录 A.1  四类差错定义与系数（重复性错误按一次计算）
  - 附录 A.2  综合差错率公式与 K、CA、Cᵢ 取值
  - 4.1 条    「无核心语义差错」——I 类差错为硬门，不参与差错率稀释
  - 7.4 条    译文综合差错率一般不超过 1.5‰
  - 8 条      万字以上抽检 10%~30%；万字以下全检

**内部收紧线**（自定，严于国标，用于本书翻译的实际验收；国标线仍是不可逾越的硬线）：
  - 综合差错率 ≤ 0.3‰（国标 1.5‰ 的 1/5）
  - II 类差错 ≤ 3 处/万字符
  - III 类差错 ≤ 5 处/万字符

用法：
    python error_rate.py --errors 审校差错清单.json --chars 210000 --purpose 自读 --k 0.7
    python error_rate.py --errors errors.csv --chars 210000 --ca 0.75 --k 0.8
    python error_rate.py --errors errors.json --chars 12000 --rate-limit 0.0002   # 逐章验收

差错清单格式（JSON 数组或 CSV，class 列必填，取值 I / II / III / IV）：
    {"class": "I", "chapter": "03", "location": "p.45",
     "source": "原文片段", "target": "译文片段", "note": "说明"}

退出码：0 = 全部通过；1 = 未达内部收紧线；2 = 不合格（I 类未清零或超国标线）
"""
import argparse
import csv
import json
import os
import sys

# 附录 A.2：各类差错系数
COEF = {"I": 3.0, "II": 1.0, "III": 0.5, "IV": 0.25}

# 7.1 a) 译文使用目的分类 → 附录 A.2 的 CA 系数
PURPOSE_CA = {
    "出版级": 1.0,      # I 类：正式文件、法律文书或出版文稿
    "分享他人": 0.75,   # II 类：一般文件和材料
    "自读": 0.5,        # III 类：参考资料
    "内容概要": 0.25,   # IV 类：内容概要
    "1": 1.0, "2": 0.75, "3": 0.5, "4": 0.25,
}

NATIONAL_LIMIT = 0.0015   # 7.4 条：国标合格线 1.5‰
INTERNAL_LIMIT = 0.0003   # 内部收紧线 0.3‰
II_DENSITY_MAX = 3.0      # II 类每万字符上限
III_DENSITY_MAX = 5.0     # III 类每万字符上限


def normalize_class(raw):
    """把 'I' / 'i' / '1' / '一类' 等写法统一为 I/II/III/IV。"""
    s = str(raw).strip().upper().replace("类", "").replace("第", "")
    roman = {"1": "I", "2": "II", "3": "III", "4": "IV"}
    if s in roman:
        s = roman[s]
    if s not in COEF:
        raise ValueError("未知差错类别: %r（应为 I/II/III/IV）" % raw)
    return s


def load_errors(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("errors", [])
    elif ext == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            data = list(csv.DictReader(f))
    else:
        raise ValueError("只支持 .json 或 .csv 差错清单")
    out = []
    for i, item in enumerate(data, 1):
        if not item:
            continue
        try:
            cls = normalize_class(item.get("class") or item.get("类别"))
        except ValueError as e:
            raise ValueError("第 %d 条：%s" % (i, e))
        out.append({
            "class": cls,
            "chapter": str(item.get("chapter") or item.get("章节") or "").strip(),
            "location": str(item.get("location") or item.get("位置") or "").strip(),
            "source": str(item.get("source") or item.get("原文") or "").strip(),
            "target": str(item.get("target") or item.get("译文") or "").strip(),
            "note": str(item.get("note") or item.get("说明") or "").strip(),
            "status": str(item.get("status") or item.get("状态") or "").strip().lower(),
        })
    return out


def split_fixed(errors):
    """审校后清单中 status=fixed 的项视为已修正，不计入差错率；返回 (未修正, 已修正数)。"""
    FIXED = ("fixed", "已修正", "fixed.", "done", "resolved")
    open_items = [e for e in errors if e.get("status") not in FIXED]
    return open_items, len(errors) - len(open_items)


def dedupe(errors):
    """附录 A.1：重复性错误按一次计算。同类别 + 同原文 + 同译文视为同一错误。"""
    seen, kept = set(), []
    for e in errors:
        key = (e["class"], e["source"], e["target"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(e)
    return kept, len(errors) - len(kept)


def mark(ok):
    return "通过" if ok else "不通过"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="综合差错率计算与验收判定（GB/T 19682-2005）")
    ap.add_argument("--errors", required=True, help="差错清单 .json / .csv")
    ap.add_argument("--chars", type=int, required=True, help="译文字符数 W（全书或单章）")
    ap.add_argument("--purpose", choices=list(PURPOSE_CA), help="译文用途（出版级/分享他人/自读/内容概要）")
    ap.add_argument("--ca", type=float, help="直接指定 CA 系数（与 --purpose 二选一）")
    ap.add_argument("--k", type=float, default=0.7, help="综合难度系数 K，0.5~1.0（默认 0.7）")
    ap.add_argument("--rate-limit", type=float, default=INTERNAL_LIMIT,
                    help="内部综合差错率上限（默认 %.4f，即 0.3‰）" % INTERNAL_LIMIT)
    ap.add_argument("--ii-density", type=float, default=II_DENSITY_MAX,
                    help="II 类每万字符上限（默认 %.1f）" % II_DENSITY_MAX)
    ap.add_argument("--iii-density", type=float, default=III_DENSITY_MAX,
                    help="III 类每万字符上限（默认 %.1f）" % III_DENSITY_MAX)
    args = ap.parse_args()

    if args.ca is None and args.purpose is None:
        ap.error("须给出 --purpose 或 --ca")
    ca = args.ca if args.ca is not None else PURPOSE_CA[args.purpose]
    ca_label = "%.2f" % ca + ("（%s）" % args.purpose if args.purpose else "")
    if not 0.5 <= args.k <= 1.0:
        print("警告：K 建议取值范围 0.5~1.0，当前 %.2f" % args.k)

    errors = load_errors(args.errors)
    errors, fixed_n = split_fixed(errors)
    errors, dup = dedupe(errors)
    counts = {c: 0 for c in COEF}
    for e in errors:
        counts[e["class"]] += 1
    weighted = sum(COEF[c] * counts[c] for c in COEF)
    rate = args.k * ca * weighted / args.chars if args.chars else 0.0
    per_10k = args.chars / 10000.0
    dens_ii = counts["II"] / per_10k if per_10k else 0.0
    dens_iii = counts["III"] / per_10k if per_10k else 0.0

    print("差错统计（附录 A.1，重复性错误按一次计算）")
    if fixed_n:
        print("  已跳过 status=fixed 的已修正项: %d 条" % fixed_n)
    for c in ("I", "II", "III", "IV"):
        print("  %-4s 类: %3d 次 × %.2f = %.2f" % (c, counts[c], COEF[c], COEF[c] * counts[c]))
    if dup:
        print("  已按重复性错误去重: %d 条" % dup)
    print("  加权和 Σ(Cᵢ·Dᵢ) = %.2f" % weighted)
    print("")
    print("参数：W = %d 字符，CA = %s，K = %.2f" % (args.chars, ca_label, args.k))
    print("综合差错率 = %.2f × %.2f × %.2f / %d = %.4f‰"
          % (args.k, ca, weighted, args.chars, rate * 1000))
    print("")

    gate_i = counts["I"] == 0
    gate_national = rate <= NATIONAL_LIMIT
    gate_internal = rate <= args.rate_limit
    gate_ii = dens_ii <= args.ii_density
    gate_iii = dens_iii <= args.iii_density

    print("验收判定")
    print("  %-16s %-14s %-12s %-12s %s" % ("项目", "实测", "内部线", "国标线", "结果"))
    print("  %-16s %-14s %-12s %-12s %s"
          % ("I 类差错", "%d 处" % counts["I"], "0 处", "0 处（4.1 条）", mark(gate_i)))
    print("  %-16s %-14s %-12s %-12s %s"
          % ("II 类差错密度", "%.2f/万" % dens_ii, "%.1f/万" % args.ii_density, "—", mark(gate_ii)))
    print("  %-16s %-14s %-12s %-12s %s"
          % ("III 类差错密度", "%.2f/万" % dens_iii, "%.1f/万" % args.iii_density, "—", mark(gate_iii)))
    print("  %-16s %-14s %-12s %-12s %s"
          % ("综合差错率", "%.4f‰" % (rate * 1000), "%.4f‰" % (args.rate_limit * 1000),
             "%.4f‰（7.4 条）" % (NATIONAL_LIMIT * 1000), mark(gate_internal)))
    print("")

    if not gate_i:
        print("结论：不合格 —— I 类差错 %d 处未清零（4.1 条硬门），该章退回重译后重跑" % counts["I"])
        return 2
    if not gate_national:
        print("结论：不合格 —— 综合差错率超国标 1.5‰（7.4 条），按类别定位高频差错后重跑")
        return 2
    if not (gate_internal and gate_ii and gate_iii):
        unmet = []
        if not gate_internal:
            unmet.append("综合差错率未达内部线 %.4f‰" % (args.rate_limit * 1000))
        if not gate_ii:
            unmet.append("II 类密度超标（%.2f/万 > %.1f/万）" % (dens_ii, args.ii_density))
        if not gate_iii:
            unmet.append("III 类密度超标（%.2f/万 > %.1f/万）" % (dens_iii, args.iii_density))
        print("结论：未达内部收紧线 —— " + "；".join(unmet))
        print("        符合国标但未达本书验收标准，建议修正后重跑（可交付的最低线是国标线）")
        return 1
    print("结论：合格 —— 全部通过（I 类清零、内部线与国标线均达标）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
