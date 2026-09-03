# 第四周验收样例说明

本目录说明 `tests/fixtures/week04/` 中的可复现测试素材。所有内容均为本地合成，不来自公司、客户或真实业务文档，不包含账号、密码、内部地址和个人信息。

## 正常样例

| 文件 | 来源 | 预期页数 | 预期文本（人工核对） | 应触发 OCR |
|---|---|---:|---|---|
| `sample_utf8.txt` | 手工编写的 UTF-8 文本 | 1 | `Week four text fixture. Parser should preserve this sentence.` | 否 |
| `sample_markdown.md` | 手工编写的 Markdown | 1 | `Semantic retrieval starts with reliable parsing.` | 否 |
| `sample_two_page.pdf` | ReportLab 本地生成的文本型 PDF | 2 | 第 1 页：`Native PDF page one: parsing keeps page numbers.`；第 2 页：`Native PDF page two: chunks retain source metadata.` | 否 |
| `sample_document.docx` | python-docx 本地生成的 DOCX | 1 | `DOCX fixture body: headings and paragraphs become ordered text.` | 否 |
| `sample_ocr.png` | Pillow 本地生成的 PNG 文本图片 | 1 | `OCR IMAGE FIXTURE 2026` | 是 |
| `sample_ocr.jpg` | 由同一合成图片导出的 JPEG | 1 | `OCR IMAGE FIXTURE 2026` | 是 |
| `sample_ocr_chinese.png` | Pillow 与系统中文字体本地生成 | 1 | `知识助手 OCR`、`中文扫描样例 2026` | 是 |
| `sample_scanned.pdf` | 将合成文本图片嵌入 PDF，页面不含文本层 | 1 | `SCANNED PDF FIXTURE 2026` | 是 |

## 异常样例

| 文件 | 来源 | 预期行为 |
|---|---|---|
| `empty.txt` | 本地创建的 0 字节文件 | 解析阶段拒绝空文件，返回可识别的业务错误 |
| `corrupt.pdf` | 手工构造的非 PDF 字节 | PDF 解析失败，错误被转换为统一的解析错误 |

## 使用约定

- 正常样例的预期文本用于后续 parser、OCR、chunk 和端到端测试断言。
- “应触发 OCR”表示该样例没有可直接使用的文本层，或本身就是图片输入。
- 样例均保持小体积，可提交 Git；模型权重、真实上传文件和任何敏感材料不得放入该目录。
- 若更新样例内容，必须同步更新本说明中的预期文本和页数。
