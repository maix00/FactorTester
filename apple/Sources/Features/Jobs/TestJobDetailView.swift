import SwiftUI

struct TestJobDetailView: View {
    let job: TestJob
    @StateObject private var controller = TestJobsController()
    @State private var showPriceViewer = false
    @State private var loadedPriceBars: [PriceBar] = []
    @State private var expandedResultIDs: Set<String> = []

    var body: some View {
        Group {
            if let detail = controller.detail {
                detailContent(detail)
            } else if controller.isLoading {
                ProgressView("正在读取任务详情…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.largeTitle).foregroundStyle(.secondary)
                    Text("任务详情暂不可用")
                    Button("重试") { Task { await controller.select(job) } }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await controller.select(job) }
        .alert("任务提示", isPresented: noticeBinding) {
            Button("好") { controller.notice = nil }
        } message: {
            Text(controller.notice ?? "")
        }
        .alert("任务错误", isPresented: errorBinding) {
            Button("好") { controller.error = nil }
        } message: {
            Text(controller.error ?? "")
        }
    }

    private func detailContent(_ detail: TestJobDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("测试任务详情").font(.title2.bold())
                    Spacer()
                    Button("刷新详情") { Task { await controller.select(detail.job) } }
                }
                HStack {
                    if detail.artifacts.contains(where: { $0.state == "active" }) {
                        Button("下载全部生成物") {
                            Task { await controller.downloadAll(from: detail.job) }
                        }
                    }
                    Button("清空生成物", role: .destructive) {
                        Task { await controller.clear(detail.job) }
                    }
                }
                TestJobFieldTable(title: "任务字段", rows: detail.fieldRows)
                configuration(detail)
                outputDeclarations(detail)
                resultPreview(detail)
                artifacts(detail)
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func configuration(_ detail: TestJobDetail) -> some View {
        TestJobFieldTable(title: "测试配置", rows: detail.configurationFields)
        if !detail.configurationJSON.isEmpty {
            ClientCodeBlock(
                source: detail.configurationJSON, language: "json", maximumHeight: 180
            )
        }
        if !detail.researchBindingFields.isEmpty {
            TestJobFieldTable(title: "研究绑定", rows: detail.researchBindingFields)
        }
        if !detail.researchBindingJSON.isEmpty {
            ClientCodeBlock(
                source: detail.researchBindingJSON, language: "json", maximumHeight: 180
            )
        }
        if !detail.submissionContextFields.isEmpty {
            TestJobFieldTable(title: "调用方", rows: detail.submissionContextFields)
        }
        if !detail.submissionContextJSON.isEmpty {
            ClientCodeBlock(
                source: detail.submissionContextJSON, language: "json", maximumHeight: 180
            )
        }
    }

    private func outputDeclarations(_ detail: TestJobDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("结果展示声明").font(.headline)
            if detail.outputDeclarations.isEmpty {
                Text("该任务没有声明可视化输出；以下为结果原始预览。")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                TestJobFieldTable(title: "展示方式", rows: detail.outputDeclarations.map {
                    TestJobField(
                        id: $0.id,
                        name: $0.label,
                        value: L10n.format(
                            "%@ · %@ · %@",
                            presentationLabel($0.presentation),
                            $0.viewer,
                            $0.formats.joined(separator: ", ")
                        )
                    )
                })
            }
        }
    }

    @ViewBuilder
    private func resultPreview(_ detail: TestJobDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("结果预览").font(.headline)
            ForEach(detail.resultSections) { section in
                TestJobResultSectionView(
                    section: section,
                    isExpanded: expandedResultIDs.contains(section.id),
                    onExpansionChanged: { expanded in
                        if expanded { expandedResultIDs.insert(section.id) }
                        else { expandedResultIDs.remove(section.id) }
                    }
                )
            }
            if detail.outputDeclarations.contains(where: isPriceViewer) {
                if showPriceViewer && !loadedPriceBars.isEmpty {
                    PriceChartView(bars: loadedPriceBars)
                } else {
                    Button("加载行情查看器") {
                        loadedPriceBars = PriceBarDecoder.decodeJSON(detail.priceResultData ?? Data())
                        showPriceViewer = !loadedPriceBars.isEmpty
                    }
                    .disabled(detail.priceResultData == nil)
                    Text("行情查看器：仅在点击后读取 OHLCV 数据")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func artifacts(_ detail: TestJobDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("生成物").font(.headline)
            let active = detail.artifacts.filter { $0.state == "active" }
            if active.isEmpty {
                Text("暂无生成物").font(.caption).foregroundStyle(.secondary)
            } else {
                TestJobArtifactGrid(artifacts: active) { artifact in
                    Task { await controller.download(artifact, from: detail.job) }
                }
            }
        }
    }

    private var noticeBinding: Binding<Bool> {
        Binding(get: { controller.notice != nil }, set: { if !$0 { controller.notice = nil } })
    }

    private var errorBinding: Binding<Bool> {
        Binding(get: { controller.error != nil }, set: { if !$0 { controller.error = nil } })
    }

    private func presentationLabel(_ value: String) -> String {
        let key = ["chart": "图表", "table": "表格", "data": "数据", "text": "文本"][value] ?? value
        return L10n.text(key)
    }

    private func isPriceViewer(_ declaration: TestJobOutputDeclaration) -> Bool {
        ["price_chart", "kline_volume", "order_flow"].contains(declaration.viewer)
    }
}
