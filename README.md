# mbx-book-translation

把整本外文书（PDF / EPUB / DOCX / 扫描件）翻译成中文，或转成 Markdown 的 Agent Skill。包含扫描版 OCR、术语统一、目录与注释整理，以及一套零 token 的门禁脚本。

## 适用

- 整本书翻译：PDF / EPUB / DOCX。
- 扫描书 OCR：PDF 逐页 OCR → 按页 JSON / 合并 MD；需要本机有 PaddleOCR-json。
- 只转 Markdown：扫描书或文本层书，不翻译。
- 单页、短文、截图不属于本 skill。

## 安装

```bash
npx skills add kissfirembx/mbx-book-translation
```

或把仓库放进 Agent 的 skills 目录（例如 `~/.claude/skills/mbx-book-translation/`）。至少要保留 `SKILL.md`、`references/`、`scripts/`。

## 依赖

```bash
pip install -r requirements.txt
```

- Python 3.10+
- `pymupdf`：PDF 渲染/提取
- `jieba`：中文分词（仅用词 rarity 检查）
- 扫描版 OCR 另需 [PaddleOCR-json](https://github.com/hiroi-sora/PaddleOCR-json)（Umi-OCR 自带）；不随仓库分发。

## 配置

所有路径走环境变量，不写死个人目录：

| 变量 | 默认 | 说明 |
|---|---|---|
| `MBX_BOOKS_DIR` | `./books` | 书籍输出根 |
| `MBX_TERMS_DIR` | `<输出根>/_术语体系` | 术语库 |
| `MBX_OCR_EXE` | 空 | PaddleOCR-json 可执行文件 |
| `MBX_OCR_ENGINE_DIR` | exe 所在目录 | `PPOCR_api.py` 所在目录 |
| `MBX_USAGE_LEDGER` | `~/.dsh/dsh-usage/usage-ledger.json` | 可选；没有就只报 token |
| `MBX_VAULT_ROOT` | 空 | Obsidian 库根；可选 |

本机覆盖写到 `references/环境与配置.local.env`（不发布，已 gitignore），格式：

```text
MBX_BOOKS_DIR=D:/books/translation
MBX_OCR_EXE=D:/tools/PaddleOCR-json/PaddleOCR-json.exe
MBX_OCR_ENGINE_DIR=D:/tools/PaddleOCR-json
```

脚本会按「真实环境变量 > local.env > 公共默认」解析。

## 使用

对 Agent 说：

> 把 `<书>` 翻译成中文，输出到 `<目录>`。

Agent 会先确认输出目录、翻译还是只转 MD、质量档，然后按 `SKILL.md` 的 6 个阶段执行。详细规则在 `references/`：

- `mode-a-text.md`：文本层书翻译
- `mode-b-ocr.md`：扫描书 OCR
- `mode-c-format.md`：只做格式转换
- `翻译规范.md`、`译名规范.md`、`输出结构与命名.md`
- `executor-prompt-templates.md`：译者 prompt 模板
- `脚本索引.md`：脚本用途与入口

## 测试

```bash
python evals/gates/run_gate_tests.py
```

42 条断言，覆盖 13 个用例组。质量对照工具在 `evals/quality/`，不附语料；用自己的样本跑。

## 已知限制

- 扫描书 OCR 依赖本机 PaddleOCR-json；仓库不附带引擎，也未内置整本扫描书实测。
- `---` 默认按作者分段符保留；只有与页码/页标记明确对齐时才按分页断点处理。
- 段落门禁是机械检查，不能替代人工通读；Ⅰ 档容差 0，Ⅱ/Ⅲ 档按百分比并在项目 README 记录。
- 生僻字检查是字级启发式；专名可用 `--allow` 豁免，但要在项目里登记。
- 本 skill 主要在 Windows + Git Bash 下开发和实测；Linux/macOS 的 OCR 路径需自行配置。

## 许可

MIT。见 `LICENSE`；第三方数据与外部程序见 `THIRD_PARTY_NOTICES.md`。

仓库不含任何真实书译文、书摘或标准全文；测试语料属于私有过程文件，不随仓库分发。
