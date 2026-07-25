import SwiftUI
import Charts
#if os(macOS)
import AppKit
#endif

@MainActor
final class TestJobsController: ObservableObject {
    @Published private(set) var jobs: [TestJob] = []
    @Published private(set) var detail: TestJobDetail?
    @Published private(set) var isLoading = false
    @Published var error: String?
    @Published var notice: String?

    private let service = TestJobsService()

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        var loaded: [TestJob] = []
        var listError: Error?
        do {
            loaded = try await service.list()
        } catch {
            listError = error
        }
        if !loaded.isEmpty || listError == nil {
            jobs = loaded.sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
            error = nil
        } else if jobs.isEmpty {
            // Keep a useful error for an unauthenticated/temporarily offline
            // server, instead of silently turning history into an empty page.
            error = listError?.localizedDescription
        }
    }

    func select(_ job: TestJob) async {
        do {
            do {
                detail = try await service.detail(
                    jobID: job.id,
                    port: job.port,
                    fallbackJob: job
                )
            } catch where job.port != currentPort {
                // Terminal history may outlive its original listener.
                detail = try await service.detail(
                    jobID: job.id,
                    port: currentPort,
                    fallbackJob: job
                )
            }
            error = nil
        }
        catch let failure { self.error = failure.localizedDescription }
    }

    func clear(_ job: TestJob) async {
        do {
            do {
                try await service.clearArtifacts(jobID: job.id, port: job.port)
            } catch where job.port != currentPort {
                try await service.clearArtifacts(jobID: job.id, port: currentPort)
            }
            notice = "已清空 \(job.id) 的生成物"
            await select(job)
            await refresh()
        }
        catch let failure { self.error = failure.localizedDescription }
    }

    func download(_ artifact: TestJobArtifact, from job: TestJob) async {
        do {
            let destination: URL
            do {
                destination = try await service.download(jobID: job.id, port: job.port, artifact: artifact)
            } catch where job.port != currentPort {
                destination = try await service.download(jobID: job.id, port: currentPort, artifact: artifact)
            }
            openFile(destination)
        } catch let failure { self.error = failure.localizedDescription }
    }

    func downloadAll(from job: TestJob) async {
        do {
            let destination: URL
            do {
                destination = try await service.downloadAll(jobID: job.id, port: job.port)
            } catch where job.port != currentPort {
                destination = try await service.downloadAll(jobID: job.id, port: currentPort)
            }
            openFile(destination)
        } catch let failure { self.error = failure.localizedDescription }
    }

    private func openFile(_ url: URL) {
#if os(macOS)
        NSWorkspace.shared.open(url)
#endif
    }

    private var currentPort: Int { Int(ServerConfig.shared.port) ?? 0 }

}

struct TestJobsView: View {
    @StateObject private var controller = TestJobsController()
    @State private var selectedID: String?
    @State private var showPriceViewer = false
    @State private var loadedPriceBars: [PriceBar] = []
    @State private var expandedResultIDs: Set<String> = []

    var body: some View {
        NavigationSplitView {
            List(controller.jobs, selection: $selectedID) { job in
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(job.kind) · \(statusLabel(job.status))").font(.headline)
                    Text("\(job.id) · 端口 \(job.port) · Profile \(job.profile)")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("生成物 \(job.artifactCount) 个").font(.caption2).foregroundStyle(.secondary)
                }
                .tag(job.id)
                .accessibilityIdentifier("test-job.\(job.id)")
            }
            .overlay { if controller.jobs.isEmpty && !controller.isLoading { emptyState("暂无测试任务") } }
            .navigationTitle("测试任务")
            .toolbar {
                ToolbarItemGroup {
                    Button { Task { await controller.refresh() } } label: { Label("刷新", systemImage: "arrow.clockwise") }
                }
            }
        } detail: {
            detailView
        }
        .task {
            await controller.refresh()
        }
        .onChange(of: selectedID) { value in
            guard let value, let job = controller.jobs.first(where: { $0.id == value }) else { return }
            showPriceViewer = false
            loadedPriceBars = []
            expandedResultIDs = []
            Task { await controller.select(job) }
        }
        .alert("任务提示", isPresented: Binding(get: { controller.notice != nil }, set: { if !$0 { controller.notice = nil } })) { Button("好") {} } message: { Text(controller.notice ?? "") }
        .alert("任务错误", isPresented: Binding(get: { controller.error != nil }, set: { if !$0 { controller.error = nil } })) { Button("好") {} } message: { Text(controller.error ?? "") }
    }

    @ViewBuilder private var detailView: some View {
        if let detail = controller.detail {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("测试任务详情").font(.title2.bold())
                    HStack {
                        Button("刷新详情") { Task { await controller.select(detail.job) } }
                        if !detail.artifacts.filter({ $0.state == "active" }).isEmpty {
                            Button("下载全部生成物") { Task { await controller.downloadAll(from: detail.job) } }
                        }
                        Button("清空生成物", role: .destructive) { Task { await controller.clear(detail.job) } }
                    }
                    TestJobFieldTable(title: "任务字段", rows: detail.fieldRows)
                    configuration(detail)
                    outputDeclarations(detail)
                    resultPreview(detail)
                    Text("生成物").font(.headline)
                    let activeArtifacts = detail.artifacts.filter { $0.state == "active" }
                    if activeArtifacts.isEmpty {
                        Text("暂无生成物").font(.caption).foregroundStyle(.secondary)
                    } else {
                        TestJobArtifactGrid(artifacts: activeArtifacts) { artifact in
                            Task { await controller.download(artifact, from: detail.job) }
                        }
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            emptyState("选择一个测试任务")
        }
    }

    @ViewBuilder private func configuration(_ detail: TestJobDetail) -> some View {
        TestJobFieldTable(title: "测试配置", rows: detail.configurationFields)
        if !detail.configurationJSON.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("配置 JSON").font(.subheadline.weight(.semibold))
                TestJobCodeBlock(text: detail.configurationJSON)
            }
        }
        if !detail.researchBindingFields.isEmpty {
            TestJobFieldTable(title: "研究绑定", rows: detail.researchBindingFields)
        }
        if !detail.researchBindingJSON.isEmpty {
            TestJobCodeBlock(text: detail.researchBindingJSON)
        }
        if !detail.submissionContextFields.isEmpty {
            TestJobFieldTable(title: "调用方", rows: detail.submissionContextFields)
        }
        if !detail.submissionContextJSON.isEmpty {
            TestJobCodeBlock(text: detail.submissionContextJSON)
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
                    TestJobField(id: $0.id, name: $0.label, value: "\(presentationLabel($0.presentation)) · \($0.viewer) · \($0.formats.joined(separator: ", "))")
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

    private func emptyState(_ title: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "checklist").font(.largeTitle).foregroundStyle(.secondary)
            Text(title).foregroundStyle(.secondary)
        }
    }

    private func statusLabel(_ value: String) -> String {
        ["succeeded": "成功", "failed": "失败", "running": "运行中", "queued": "排队中", "planning": "规划中", "paused": "已暂停", "cancelled": "已取消"][value] ?? value
    }

    private func presentationLabel(_ value: String) -> String {
        ["chart": "图表", "table": "表格", "data": "数据", "text": "文本"][value] ?? value
    }

    private func isPriceViewer(_ declaration: TestJobOutputDeclaration) -> Bool {
        ["price_chart", "kline_volume", "order_flow"].contains(declaration.viewer)
    }
}
