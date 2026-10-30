# TradeResearch 项目文档 PDF

该模块从显式登记的 Markdown 文档源生成一个中文 PDF。正文仍以 `product_docs/`、
`docs/` 中的原始文件为准；本目录只保存编译入口、章节清单和合集说明，不复制正文。

## 构建

需要 Pandoc 3.12.x、TeX Live 2026（含 XeLaTeX、latexmk、ctexbook、longtable、
booktabs、xurl 和 listings）。构建会在 PDF 中写入当前 Git revision、Pandoc/XeLaTeX
版本和每份源文档的 Git 最后修改日期。脏工作区会生成包含工作树内容摘要的快照标识，
并对每份改动中的源文件记录 SHA-256；编译期间工作树若变化，构建会失败并要求重试。
对同一源码快照、同一工具链与字体构建可复现；字体与 TeX 发行版不同可能改变 PDF
字节。

macOS 可用 Homebrew 安装 Pandoc；TeX Live 可使用 MacTeX。Linux 可安装发行版 Pandoc
和 TeX Live 的 XeTeX、ctex、latexmk、recommended/extra collections。构建脚本不会
自动下载工具或修改系统环境。

```bash
python scripts/docs/build_project_pdf.py --check
python scripts/docs/build_project_pdf.py
```

默认输出到 `.artifacts/docs-pdf/TradeResearch-project-docs.pdf`，不会提交 PDF 或
临时转换文件。可用 `--output /path/to/file.pdf` 指定其他位置。

## 文档范围与准确性

`manifest.toml` 是 PDF 的唯一章节白名单；未登记的内部审计、临时交接和研究记录不会
自动进入。新增章节必须登记来源、标题和所属读者章节。对于 `product_docs/` 中的实现
页，构建还会校验其文档清单登记的 canonical paths 仍存在。每章显示源文件最后修改
日期和未提交状态，帮助读者判断内容时点；这些检查不代替对文档事实与当前代码的人工
审阅。若源文档本身陈旧，应先修正文档源，再构建 PDF。

新增链接只有在目标文档也登记到合集时才会改写为 PDF 内章节链接；其他本地 Markdown
链接保留为源路径文字，避免在 PDF 中产生无法打开的相对链接。

## 图示与图例

`figures.md` 是图示的权威源，使用 XeLaTeX/TikZ 绘制网络拓扑、身份层级、RunSpec
执行链路和因子到交易结果的流程。每张图均带图注与图例；实线、虚线、颜色和禁用
符号在合集内保持一致。图中虚线标为规划或待验收，不能当作当前已部署能力。

## 章节组成

当前清单覆盖用户指南、技术与架构设计、API/字段参考、数据与数据库、部署运维、测试
验收以及发布和客户端安装。目录会说明每份文档面向谁、解决什么问题，并标注它在 Git
中的最后更新时间。
