---
name: mbx-book-translation
description: 把整本外文书（PDF/EPUB/DOCX/扫描件）或长篇文章翻译成中文或转为 Markdown，含扫描版 OCR、术语统一、目录与注释整理。当用户要翻译整本书、长文/连载、扫描书 OCR 或整本书转 MD 时使用；短句、截图、单页短文不接。
---

# 书籍与长文翻译转 MD

把一本外文书或一篇长文完整转换为中文 Markdown，或按原语言转成高质量 Markdown。三种模式：**A 文本层翻译**、**B 扫描 OCR**（可翻译，也可只转 MD）、**C 纯格式转 MD**。

本入口只放流程、停止条件与用户门。条件性细节在 `references/`，确定性操作在 `scripts/`。

## 1. 用途与边界

适用于整本书（PDF、EPUB、DOCX、扫描件）和长篇文章（Markdown、HTML、连载、作者自媒体长文）。

不接：短句、截图识字、单页短文、Obsidian 库整体翻译。

## 2. 入口判定

先问两件事：源文路径；这次是翻译，还是只转 MD。再判源文类型：有文字层走 A/C，无文字层（扫描）走 B。

| | 要翻译 | 不翻译 |
|---|---|---|
| 有文字层 | A 文本层翻译 | C 纯格式转 MD |
| 无文字层 | B + 翻译 | B 只转 MD |

EPUB / DOCX 按文本层处理；DOCX 解包读 `word/document.xml`。加密 PDF 走 S2。判定命令与阈值见 `references/源文体检.md`。

长文/连载按标题或自然小节切，不强行套书级目录；没有书级目录就跳过目录页解析，其余仍走 A2–A5。

## 3. 开工门 G1

一条消息最多三问：

1. 输出目录：默认 `$MBX_BOOKS_DIR/<书名或标题>/`；未设置时 `./books/<书名或标题>/`。用户给路径就用给的；本机值见 `references/环境与配置.local.env`。
2. 翻译，还是只转 MD。
3. 质量档：默认**自读**；要精确翻译说一声。

小样默认先跑，只告知，不单独提问；不想跑说「跳过」，记入规格。

成本：提取完成后跑 `scripts/estimate_cost.py --book-dir <书目录>`，在紧接着的消息里报 **token 三桶**；不问套餐、不报钱、不报总价。

已有成品：走 G0。

## 4. 主线 6 步 × 3 模式

| 步骤 | A 文本层翻译 | B 扫描 OCR | C 纯格式 |
|---|---|---|---|
| 1 提取 | `extract_pdf_text.py` / `extract_epub_text.py` | OCR（`ocr_pdf.py`，B1–B3）→ `rebuild_source_from_ocr.py` 或 `--md-out` | `extract_pdf_text.py` / `extract_epub_text.py` |
| 2 体检 | `preflight_probe.py` + 覆盖率 + `rewrap_source_lines.py` + 成本预估 | 同左 | `preflight_probe.py`（覆盖率可选） |
| 3 冻结 | 术语 / 格式 / 图锚点 / 文种 | 同左 | 格式 / 命名 |
| 4 翻译 | 批量 + 审校 | 同左 | — |
| 5 质检 | 审校 + 人在回路 | 同左 | 格式 QA |
| 6 交付 | 清单 + 沉淀 + 记账 | 同左 | 清单 + 命名 |

B 分两格：**B + 翻译**（步骤 4 正常）；**B 只转 MD**（步骤 4 跳过，产物用 `_原文版.md`）。

每步的详细步骤、参数与阈值：

- 1 提取：`references/mode-a-text.md` A1、`references/mode-b-ocr.md` B1–B3、`references/mode-c-format.md` C1
- 2 体检：`references/源文体检.md`
- 3 冻结：`references/mode-a-text.md` A2 + `references/executor-prompt-templates.md`
- 4 翻译：`references/executor-prompt-templates.md` + `references/编排与分发.md`
- 5 质检：`references/mode-a-text.md` A4 + `references/关于流畅度质检.md`
- 6 交付：`references/输出结构与命名.md` + `references/成本优化.md`

**段落**：源文一个空行块译一个段落；翻译后不并段、不拆段。要整理只能在翻译前做，成品名加 `_书面整理版`。

## 5. 硬停止（5 条）

| # | 条件 | 判定 | 停下后 |
|---|---|---|---|
| S1 | 目标目录已有成品且未获覆盖同意 | 文件存在 + 无授权 | 另存，交付后再决定是否替换 |
| S2 | 源文不可用：加密无密码，或翻译路径覆盖率非 0 | `authenticate` / 覆盖率退出码 | 要密码，或补提取后重跑 |
| S3 | 成色 Ⅲ 档未在翻译前重组 | `preflight_probe` 判 Ⅲ | 先重组，过零改写校验 |
| S4 | 批量前门：规范未冻结；精确档还要术语 + 小样已确认 | 规格 + 术语表 + 小样产物 | 冻结、补确认，再进批量 |
| S5 | 交付门：段落边界、I 类差错、图片引用、成品唯一（明确要求的形态变体除外）任一未过；数字/结构/标记等退出码 2，或退出码 1 未逐条定性 | 脚本退出码 + 清单 | 回修对应阶段，重跑 |

## 6. 验证循环（3 个）

| # | 循环 | 跑什么 | 通过条件 |
|---|---|---|---|
| V1 | 提取与体检 | 提取 → 覆盖率 → 体检 → 长行预折 | 覆盖率 0；档位已定；长行 ≤ 上限 |
| V2 | 批量前 | 冻结规格 → 建术语表 → 生成切片 → 跑小样 | 规格齐全；切片含译名与语境；小样落盘 |
| V3 | 交付前 | 审校 → 质检报告 → 修复 → 复查 | 脚本退出码 0；问题清零或已登记 |

## 7. 用户门

| 门 | 时机 | 问什么 | 默认 |
|---|---|---|---|
| G0 | 目标已有成品 | 覆盖、另存还是只补缺失 | 另存；旧稿不读、不比对 |
| G1 | 开工 | 目录、翻译或只转 MD、质量档 | 目录默认；自读；小样跑 |
| G2 | 术语 + 小样已落盘 | 术语有无要改；小样能否开批量 | 自读不强制等；精确档硬门 |
| G3 | 精确档审校完成 | 是否接受差错清单与抽检结果 | 精确档硬门 |
| G4 | 批量改稿 ≥2 处 | 先改 1 处；≥3 处再抽 2 处，是否照此批量 | 不通过就停 |

自读档只跑零 token 确定性项，不产出要人逐条看的候选清单；精确档才加 `check_fluency` / `check_word_rarity` 与三层审校。

## 8. 参考文件

| 文件 | 什么时候读 |
|---|---|
| `references/mode-a-text.md` / `mode-b-ocr.md` / `mode-c-format.md` | 进入对应模式时 |
| `references/源文体检.md` | 提取后、批量前；体检与覆盖率卡口 |
| `references/翻译规范.md` / `译名规范.md` | 加载规范、验收与译名裁决 |
| `references/executor-prompt-templates.md` | 批量翻译与审校，逐字复用模板 |
| `references/编排与分发.md` | 多章 / 多本分发前 |
| `references/输出结构与命名.md` | 建目录、命名、轮次归档 |
| `references/成本优化.md` | 每本书开工前 |
| `references/脚本索引.md` | 查脚本用途与入口 |
| `references/已知坑.md` | 遇提取、标记、门禁误报 |
| `references/经验与事故.md` | 想查「为什么有这条规则」时；正常流程不读 |
| `references/环境与配置.md` | 换机器、换 OCR 引擎、换价格时 |
| `references/data/` | 表驱动规则与符号 / 混淆表 |
| `GB/T 19682-2005` / `GB/T 19363.1-2003` | 条款争议时按标准编号查正式文本（本仓库不附全文） |

## 9. 本机默认值

- 先读 `references/环境与配置.local.env`（存在则优先）；公共默认见 `references/环境与配置.md`。
- 输出根：`$MBX_BOOKS_DIR`（默认 `./books`）；术语体系：`$MBX_TERMS_DIR`（默认 `<输出根>/_术语体系`）。
- OCR 引擎：`$MBX_OCR_EXE` / `$MBX_OCR_ENGINE_DIR`；DSH 账本：`$MBX_USAGE_LEDGER`；价格缓存见环境配置。
- Obsidian 复核：只在改动涉及 `#`、`*`、`[[…]]`、图片路径时做；非 Obsidian 环境跳过。

## 10. 交付物

- 翻译：`<书名> 中文全译.md`；C 与 B 只转：`<书名>_原文版.md`。
- 每本书一份 `README.md` 与 `翻译任务规格.md`；质检产物在 `_过程/`。
- 形态变体：`_书面整理版` / `_逐行版`，只在明确要求时并存。
- 交付前过 S5；报告问题数、门禁结果、token 与实际耗时。
