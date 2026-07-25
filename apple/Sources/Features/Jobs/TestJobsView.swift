import SwiftUI

@MainActor
final class TestJobsController: ObservableObject {
    @Published private(set) var jobs: [TestJob] = []
    @Published private(set) var detail: TestJobDetail?
    @Published private(set) var isLoading = false
    @Published var error: String?
    @Published var notice: String?
    @Published var portText = ""

    private let service = TestJobsService()

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            var loaded: [TestJob] = []
            for port in ports { loaded += try await service.list(port: port) }
            jobs = loaded.sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
            error = nil
        }
        catch let failure { self.error = failure.localizedDescription }
    }

    func select(_ job: TestJob) async {
        do { detail = try await service.detail(jobID: job.id, port: job.port); error = nil }
        catch let failure { self.error = failure.localizedDescription }
    }

    func clear(_ job: TestJob) async {
        do { try await service.clearArtifacts(jobID: job.id, port: job.port); notice = "已清空 \(job.id) 的生成物"; await select(job); await refresh() }
        catch let failure { self.error = failure.localizedDescription }
    }

    func download(_ artifact: TestJobArtifact, from job: TestJob) async {
        do {
            let url = try await service.download(jobID: job.id, port: job.port, artifact: artifact)
            notice = "已下载到 \(url.path)"
        } catch let failure { self.error = failure.localizedDescription }
    }

    var ports: [Int] {
        let current = Int(ServerConfig.shared.port) ?? 0
        let saved = UserDefaults.standard.string(forKey: "factortester.jobPorts")?.split(separator: ",").compactMap { Int($0) } ?? []
        return Array(Set([current] + saved).filter { 1...65535 ~= $0 }).sorted()
    }

    func addPort() {
        guard let port = Int(portText), 1...65535 ~= port else { return }
        let values = Set(ports + [port]).sorted().map(String.init).joined(separator: ",")
        UserDefaults.standard.set(values, forKey: "factortester.jobPorts")
        portText = ""
        Task { await refresh() }
    }
}

struct TestJobsView: View {
    @StateObject private var controller = TestJobsController()
    @State private var selectedID: String?

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
                    TextField("端口", text: $controller.portText).frame(width: 70)
                    Button("添加端口") { controller.addPort() }
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
                    disclosure("输出声明", detail.outputRequests.joined(separator: "\n"))
                    disclosure("研究绑定", detail.researchBindingText)
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

    private func emptyState(_ title: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "checklist").font(.largeTitle).foregroundStyle(.secondary)
            Text(title).foregroundStyle(.secondary)
        }
    }

    private func statusLabel(_ value: String) -> String {
        ["succeeded": "成功", "failed": "失败", "running": "运行中", "queued": "排队中", "planning": "规划中", "paused": "已暂停", "cancelled": "已取消"][value] ?? value
    }
}
