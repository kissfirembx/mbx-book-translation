# Third-party notices

本仓库的代码与文档以 MIT 许可发布（见 `LICENSE`）。以下内容有单独来源，使用时注意各自条款。

## 数据

- `references/data/常用字表.json`
  用于字级生僻字检查，字表源自《通用规范汉字表》（2013）的常用字范围。字表本身用于事实性比对；如再分发，请保留来源说明。
- `references/data/api-pricing.json`
  供应商价格的示例缓存，不是权威报价；实际计费以供应商官方页面与账单为准。使用前核对币种、单位、日期与优惠时段。
- `references/data/confusions.json`、`footers.json`、`symbols.json`
  本管线维护的表驱动规则，随本仓库以 MIT 发布。

## 外部程序

- PaddleOCR-json / Umi-OCR
  扫描书 OCR 的外部依赖，不随本仓库分发。安装与使用遵循其各自许可证。
- PyMuPDF、jieba
  Python 依赖，见 `requirements.txt`；遵循各自许可证。

## 标准文本

本仓库不包含 GB/T 19682-2005、GB/T 19363.1-2003 等国家标准全文，只在规则文档中引用标准编号与条款位置。需要逐条核对时，请查阅正式标准文本。

## 测试语料

本仓库不包含真实书译文、书摘或 OCR 输出；`evals/` 只提供通用 harness 与门禁自测，语料由使用者自备。
