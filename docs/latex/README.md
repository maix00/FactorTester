# TradeResearch 项目文档 PDF

该模块从显式登记的 Markdown 文档源生成一个中文 PDF。正文仍以 `product_docs/`、
`docs/` 中的原始文件为准；本目录只保存编译入口、章节清单和合集说明，不复制正文。

## 构建

需要 Pandoc 3.13.x、TeX Live 2026（含 XeLaTeX、latexmk、ctexbook、longtable、
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
本合集记录产品功能、架构、实现方式与通用运维方法。它不是一次变更的操作记录，
不收录具体服务器的迁移方案、备份目录、对象数量、执行 SHA 或验收日志。

## 文档范围与准确性

`manifest.toml` 是 PDF 的唯一内容白名单，按“部分 → 章节 → 源文档”三级组织；
未登记的内部审计、临时交接和研究记录不会自动进入。新增内容必须说明读者、章节目标
和源文件。对于 `product_docs/` 中的实现页，构建会校验文档清单登记的 canonical paths
仍然存在。来源路径、Git 状态和 SHA-256 前缀统一列在附录，正文不重复贴版本元数据。
这些检查帮助定位内容时点，但不代替对文档事实与当前代码的人工审阅。若源文档陈旧，
应先修正文档源，再构建 PDF。

新增链接只有在目标文档也登记到合集时才会改写为 PDF 内章节链接；其他本地 Markdown
链接保留为源路径文字，避免在 PDF 中产生无法打开的相对链接。

## 图示与图例

`figures.md` 收录系统拓扑、权限层级和组件职责图；`flows/` 中的流程图分别放在登录、
任务运行、报告发布、因子目录同步和部署回退章节。业务流程按泳道标出实际客户端、发起
Manager、目标/来源 Manager、队列、执行节点和对象存储，给出数据类别、端点/端口、方向、
权威与返回路径。流程图还要说明权限检查、成功结果和失败分支；跨服务路径须分别标明
控制面与字节数据面，未实现链路用虚线并写清当前限制，不得只画脱离部署拓扑的抽象业务框。
网络拓扑的唯一图源为 `network-topology.tex`：
PDF 直接引用该图源，网页使用同一图源生成的静态 SVG
（中、英文各一张）。修改拓扑后运行 `python scripts/docs/build_network_topology.py`
更新网页图片；需要 XeLaTeX、Poppler 的 pdftocairo、TikZ、ctex 和 Font Awesome 5。
如 `pdftocairo` 不在 PATH 中，可通过环境变量 `PDFTOCAIRO` 指定可执行文件。每张图均带图注
与图例；虚线标为规划或待验收，不能当作当前已部署能力。

## 章节组成

当前清单按研究人员使用流程、领域模型与系统架构、接口与文档参考、验收与运行维护
四部分组织。用户流程先说明操作顺序和异常结果；领域章节再解释对象及其实现边界；
参考章节列出接口和字段；验收与运维章节汇总检查、备份、恢复和回退要求。具体迁移计划
与现场执行记录仍在独立运维档案中维护，不编入 PDF。ADR 是决策与历史上下文，也不直接
拼入手册。
