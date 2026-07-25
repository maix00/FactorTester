import SwiftUI
import Charts

@MainActor
final class TestJobsController: ObservableObject {
    @Published private(set) var jobs: [TestJob] = []
    @Published private(set) var detail: TestJobDetail?
    @Published private(set) var isLoading = false
    @Published private(set) var discoveredPorts: [Int] = []
    @Published var error: String?
    @Published var notice: String?

    private let service = TestJobsService()

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        if let found = try? await service.visiblePorts() {
            discoveredPorts = Array(Set(found + [currentPort])).sorted()
        }
        var loaded: [TestJob] = []
        var listError: Error?
        do {
            loaded = try await service.list()
        } catch {
            listError = error
        }
        if loaded.isEmpty {
            // Older deployments may not understand port=all. Keep the
            // explicit-port path as a compatibility fallback.
            for port in ports where port != currentPort {
                loaded += (try? await service.list(port: port)) ?? []
            }
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
            let url: URL
            do {
                url = try await service.download(jobID: job.id, port: job.port, artifact: artifact)
            } catch where job.port != currentPort {
                url = try await service.download(jobID: job.id, port: currentPort, artifact: artifact)
            }
            notice = "已下载到 \(url.path)"
        } catch let failure { self.error = failure.localizedDescription }
    }

    var ports: [Int] {
        let current = currentPort
        let saved = UserDefaults.standard.string(forKey: "factortester.jobPorts")?.split(separator: ",").compactMap { Int($0) } ?? []
        return Array(Set([current] + saved + discoveredPorts).filter { 1...65535 ~= $0 }).sorted()
    }

    var currentPort: Int { Int(ServerConfig.shared.port) ?? 0 }

    func discoverPorts() async {
        do {
            discoveredPorts = try await service.visiblePorts()
            notice = "已发现端口：\(ports.map(String.init).joined(separator: ", "))"
            await refresh()
        } catch let failure { error = failure.localizedDescription }
    }

}

struct TestJobsView: View {
    @StateObject private var controller = TestJobsController()
    @State private var selectedID: String?
    @State private var showPriceViewer = false
    @State private var loadedPriceBars: [PriceBar] = []

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
                    Text("端口 \(controller.ports.map(String.init).joined(separator: ", "))")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("发现端口") { Task { await controller.discoverPorts() } }
                    Button { Task { await controller.refresh() } } label: { Label("刷新", systemImage: "arrow.clockwise") }
                }
            }
        } detail: {
            detailView
        }
        .task {
            while !Task.isCancelled {
                await controller.refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
        .onChange(of: selectedID) { value in
            guard let value, let job = controller.jobs.first(where: { $0.id == value }) else { return }
            showPriceViewer = false
            loadedPriceBars = []
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
                    Text("\(detail.job.id) · \(statusLabel(detail.job.status)) · 端口 \(detail.job.port) · Profile \(detail.job.profile)").foregroundStyle(.secondary)
                    HStack {
                        Button("刷新详情") { Task { await controller.select(detail.job) } }
                        Button("清空生成物", role: .destructive) { Task { await controller.clear(detail.job) } }
                    }
                    disclosure("配置", detail.configurationText)
                    outputDeclarations(detail)
                    disclosure("研究绑定", detail.researchBindingText)
                    disclosure("调用方", detail.submissionContextText)
                    resultPreview(detail)
                    Text("生成物").font(.headline)
                    ForEach(detail.artifacts.filter { $0.state == "active" }) { artifact in
                        HStack {
                            VStack(alignment: .leading) { Text(artifact.description); Text("\(artifact.sizeBytes) bytes").font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            Button("下载") { Task { await controller.download(artifact, from: detail.job) } }
                        }
                        Divider()
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            emptyState("选择一个测试任务")
        }
    }

    private func disclosure(_ title: String, _ value: String) -> some View {
        DisclosureGroup(title) { Text(value).font(.system(.body, design: .monospaced)).textSelection(.enabled).padding(.top, 6) }
    }

    private func outputDeclarations(_ detail: TestJobDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("结果展示声明").font(.headline)
            if detail.outputDeclarations.isEmpty {
                Text("该任务没有声明可视化输出；以下为结果原始预览。")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(detail.outputDeclarations) { declaration in
                    HStack {
                        Text(declaration.label)
                        Spacer()
                        Text(presentationLabel(declaration.presentation))
                            .font(.caption).foregroundStyle(.secondary)
                        Text(declaration.formats.joined(separator: ", "))
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func resultPreview(_ detail: TestJobDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("结果预览").font(.headline)
            if !detail.chartPoints.isEmpty {
                Chart(detail.chartPoints) { point in
                    LineMark(x: .value("时点", point.id), y: .value("数值", point.value))
                }
                .frame(height: 180)
            }
            if let first = detail.previewRows.first {
                let columns = first.keys.sorted().prefix(24)
                ScrollView(.horizontal) {
                    Grid(horizontalSpacing: 12, verticalSpacing: 6) {
                        GridRow { ForEach(columns, id: \.self) { Text($0).font(.caption.bold()) } }
                        ForEach(detail.previewRows.prefix(30).indices, id: \.self) { index in
                            GridRow { ForEach(columns, id: \.self) { Text(detail.previewRows[index][$0] ?? "—").font(.caption) } }
                        }
                    }
                    .padding(8)
                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 6))
                }
            } else {
                Text(detail.resultText).font(.system(.body, design: .monospaced)).textSelection(.enabled)
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
