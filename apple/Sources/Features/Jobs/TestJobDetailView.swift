import SwiftUI

struct TestJobDetailView: View {
    let job: TestJob
    @ObservedObject var tabSession: ClientTabSession
    @StateObject private var controller = TestJobsController()
    @State private var showPriceViewer = false
    @State private var loadedPriceBars: [PriceBar] = []
    @State private var isLoadingPriceBars = false
    @State private var priceViewerError: String?
    @State private var priceLoadGeneration = 0
    @State private var priceLoadTask: Task<Void, Never>?
    @State private var expandedResultIDs: Set<String> = []
    @State private var artifactTables: [String: TestJobArtifactTable] = [:]
    @State private var loadingArtifactIDs: Set<String> = []
    @State private var artifactTableErrors: [String: String] = [:]
    @State private var presentedReference: ResearchDocumentTypedLink?

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
                    Button("重试") { Task { await load(job) } }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task {
            if let cached = tabSession.jobDetails[job.id] {
                controller.restore(cached)
            } else {
                await load(job)
            }
            controller.watchProgress(job)
        }
        .onDisappear {
            cancelPriceLoad()
            controller.stopProgress()
        }
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
        .sheet(item: $presentedReference) { reference in
            ResearchDocumentReferenceOverlay(
                reference: reference,
                binding: nil,
                asset: nil,
                reportRef: "",
                serverURL: serverURL(for: job),
                objectHref: nil,
                openJobSource: { _, _, _ in }
            )
        }
    }

    private func detailContent(_ detail: TestJobDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text(L10n.format("%@ · %@", ProfilePresentationText.jobKind(detail.job.kind), detail.job.id))
                        .font(.title2.bold())
                    Spacer()
                    Button("刷新详情") { Task { await load(detail.job) } }
                }
                jobProgress
                HStack {
                    if detail.artifacts.contains(where: { $0.state == "active" }) {
                        Button("下载全部生成物") {
                            Task { await controller.downloadAll(from: detail.job) }
                        }
                    }
                    Button("清空生成物", role: .destructive) {
                        Task {
                            await controller.clear(detail.job)
                            if let refreshed = controller.detail {
                                tabSession.jobDetails[detail.job.id] = refreshed
                            }
                        }
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

    private func load(_ value: TestJob) async {
        await controller.select(value)
        if let loaded = controller.detail {
            tabSession.jobDetails[value.id] = loaded
        }
    }

    @ViewBuilder
    private var jobProgress: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("任务进度").font(.headline)
            if let progress = controller.liveProgress {
                if let fraction = progress.fraction {
                    ProgressView(value: fraction)
                } else {
                    ProgressView()
                }
                Text(progress.label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if ["running", "planning"].contains(job.status) {
                ProgressView()
            } else {
                Text(LocalizedStringKey(TestJobPresentation.statusLabel(job.status)))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
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
            ForEach(detail.outputDeclarations) { declaration in
                if let artifact = TestJobResultArtifactResolver.table(
                    for: declaration, in: detail.artifacts
                ) {
                    artifactTablePreview(
                        declaration: declaration,
                        artifact: artifact,
                        detail: detail
                    )
                } else if let artifact = TestJobResultArtifactResolver.image(
                    for: declaration, in: detail.artifacts
                ) {
                    artifactImagePreview(
                        declaration: declaration,
                        artifact: artifact,
                        detail: detail
                    )
                }
            }
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
                } else if isLoadingPriceBars {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("正在后台解析行情数据…")
                        Button("取消加载") { cancelPriceLoad() }
                    }
                } else {
                    Button("加载行情查看器") {
                        loadPriceViewer(detail.priceResultData ?? Data())
                    }
                    .disabled(detail.priceResultData == nil)
                }
                if let priceViewerError {
                    Text(priceViewerError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                Text("行情查看器：仅在点击后后台读取 OHLCV 数据；上限 64 MB / 250,000 根 K 线")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func artifactTablePreview(
        declaration: TestJobOutputDeclaration,
        artifact: TestJobArtifact,
        detail: TestJobDetail
    ) -> some View {
        let expansionID = "artifact-table:\(declaration.id)"
        return DisclosureGroup(
            isExpanded: Binding(
                get: { expandedResultIDs.contains(expansionID) },
                set: { expanded in
                    if expanded {
                        expandedResultIDs.insert(expansionID)
                        loadArtifactTable(artifact, detail: detail)
                    } else {
                        expandedResultIDs.remove(expansionID)
                    }
                }
            )
        ) {
            if let table = artifactTables[artifact.id] {
                TestJobArtifactTableView(
                    table: table,
                    openReference: { presentedReference = $0 }
                )
            } else if loadingArtifactIDs.contains(artifact.id) {
                ProgressView("正在读取表格生成物…")
            } else if let error = artifactTableErrors[artifact.id] {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        } label: {
            Text(declaration.label).font(.headline)
        }
    }

    private func artifactImagePreview(
        declaration: TestJobOutputDeclaration,
        artifact: TestJobArtifact,
        detail: TestJobDetail
    ) -> some View {
        let expansionID = "artifact-image:\(declaration.id)"
        return DisclosureGroup(
            isExpanded: Binding(
                get: { expandedResultIDs.contains(expansionID) },
                set: { expanded in
                    if expanded { expandedResultIDs.insert(expansionID) }
                    else { expandedResultIDs.remove(expansionID) }
                }
            )
        ) {
            TestJobArtifactImagePreview(artifact: artifact) {
                try await controller.artifactData(artifact, from: detail.job)
            }
        } label: {
            Text(declaration.label).font(.headline)
        }
    }

    private func loadArtifactTable(
        _ artifact: TestJobArtifact,
        detail: TestJobDetail
    ) {
        guard artifactTables[artifact.id] == nil,
              !loadingArtifactIDs.contains(artifact.id) else { return }
        loadingArtifactIDs.insert(artifact.id)
        artifactTableErrors[artifact.id] = nil
        Task {
            do {
                artifactTables[artifact.id] = try await controller.artifactTable(
                    artifact, from: detail.job
                )
            } catch {
                artifactTableErrors[artifact.id] = error.localizedDescription
            }
            loadingArtifactIDs.remove(artifact.id)
        }
    }

    private func serverURL(for job: TestJob) -> URL {
        var components = URLComponents(
            url: ServerConfig.shared.baseURL
                ?? ManagerConfig.bakedPublicBootstrapEndpoint,
            resolvingAgainstBaseURL: false
        )!
        if job.port > 0 { components.port = job.port }
        return components.url ?? ManagerConfig.bakedPublicBootstrapEndpoint
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

    private func loadPriceViewer(_ data: Data) {
        priceLoadTask?.cancel()
        priceLoadGeneration &+= 1
        let generation = priceLoadGeneration
        isLoadingPriceBars = true
        priceViewerError = nil
        priceLoadTask = Task {
            do {
                let bars = try await PriceBarDecoder.decodeJSONInBackground(data)
                try Task.checkCancellation()
                guard generation == priceLoadGeneration else { return }
                loadedPriceBars = bars
                showPriceViewer = !bars.isEmpty
                isLoadingPriceBars = false
                if bars.isEmpty {
                    priceViewerError = L10n.text("未找到可绘制的 OHLCV 数据")
                }
            } catch is CancellationError {
                return
            } catch let error as PriceBarDecodingError {
                guard generation == priceLoadGeneration else { return }
                isLoadingPriceBars = false
                priceViewerError = priceViewerMessage(for: error)
            } catch {
                guard generation == priceLoadGeneration else { return }
                isLoadingPriceBars = false
                priceViewerError = L10n.text("行情数据无法解析")
            }
        }
    }

    private func cancelPriceLoad() {
        priceLoadGeneration &+= 1
        priceLoadTask?.cancel()
        priceLoadTask = nil
        isLoadingPriceBars = false
    }

    private func priceViewerMessage(for error: PriceBarDecodingError) -> String {
        switch error {
        case .inputTooLarge, .rowLimitExceeded:
            return L10n.text("行情数据超过本地查看器容量上限")
        case .invalidJSON, .missingOHLCVRows:
            return L10n.text("行情数据格式无法识别")
        }
    }
}
