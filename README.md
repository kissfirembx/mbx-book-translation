# mbx-book-translation

把整本书或长篇文章翻译成中文，或转成 Markdown 的 Agent Skill。支持文本层 PDF、EPUB、DOCX、扫描件，也支持 Markdown、HTML、剪藏长文。

## 能做什么

| 源文 | 翻译 | 只转 Markdown |
|---|---|---|
| 文本层 PDF / EPUB / DOCX | ✓ | ✓ |
| 扫描书 | OCR 后翻译 | OCR 后只转 Markdown |
| 长篇文章 / 连载 / 作者自媒体长文 | ✓ | ✓ |

扫描书不是只能转 MD：先 OCR，之后可以继续翻译，也可以停在 Markdown。

不接：短句、截图识字、单页短文、Obsidian 库整体翻译。

## 安装

```bash
npx skills add kissfirembx/mbx-book-translation
```

或把仓库放进 Agent 的 skills 目录，至少保留 `SKILL.md`、`references/`、`scripts/`。

## 依赖

```bash
pip install -r requirements.txt
```

- Python 3.10+
- `pymupdf`：PDF 渲染与提取
- `jieba`：中文分词
- 扫描书另需 [PaddleOCR-json](https://github.com/hiroi-sora/PaddleOCR-json)，外部程序，不随仓库分发

## 配置

路径走环境变量，不写死个人目录：

| 变量 | 默认 | 说明 |
|---|---|---|
| `MBX_BOOKS_DIR` | `./books` | 书籍/长文输出根 |
| `MBX_TERMS_DIR` | `<输出根>/_术语体系` | 术语库 |
| `MBX_OCR_EXE` | 空 | PaddleOCR-json 可执行文件 |
| `MBX_OCR_ENGINE_DIR` | `MBX_OCR_EXE` 所在目录 | `PPOCR_api.py` 所在目录 |
| `MBX_USAGE_LEDGER` | `~/.dsh/dsh-usage/usage-ledger.json` | 可选 |
| `MBX_VAULT_ROOT` | 空 | Obsidian 库根，可选 |

本机覆盖写到 `references/环境与配置.local.env`（不发布），格式：

```text
MBX_BOOKS_DIR=D:/books/translation
MBX_OCR_EXE=D:/tools/PaddleOCR-json/PaddleOCR-json.exe
MBX_OCR_ENGINE_DIR=D:/tools/PaddleOCR-json
```

## 使用

直接对 Agent 说：

> 把这本书翻译成中文。

> 把这篇长文翻译成中文。

> 这本扫描书先 OCR，再翻译。

> 这本只转 Markdown，不翻译。

不用套固定句式。输出目录、是否翻译、质量档，Agent 会按流程确认；如果你有自己的目录习惯，直接告诉它。

详细规则在 `references/`：

- `mode-a-text.md`：文本层书与长文翻译
- `mode-b-ocr.md`：扫描书 OCR，可翻译或只转 MD
- `mode-c-format.md`：只做格式转换
- `翻译规范.md`、`译名规范.md`、`输出结构与命名.md`
- `executor-prompt-templates.md`：译者 prompt 模板
- `脚本索引.md`：脚本用途与入口

## 许可

MIT。见 `LICENSE`。
