import SwiftUI

struct TestJobsView: View {
    let openJob: (TestJob) -> Void
    @StateObject private var controller = TestJobsController()
    @State private var page = 1
    @State private var pageInput = "1"
    @State private var selectedJobIDs = Set<String>()
    private let pageSize = 20

    init(openJob: @escaping (TestJob) -> Void = { _ in }) {
        self.openJob = openJob
    }

    private var pageCount: Int {
        max(1, Int(ceil(Double(controller.jobs.count) / Double(pageSize))))
    }

    private var pageJobs: ArraySlice<TestJob> {
        let start = min((page - 1) * pageSize, controller.jobs.count)
        let end = min(start + pageSize, controller.jobs.count)
        return controller.jobs[start..<end]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            if controller.isLoading && controller.jobs.isEmpty {
                ProgressView("正在读取测试任务…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if controller.jobs.isEmpty {
                emptyState(controller.error == nil ? "暂无测试任务" : "暂时无法读取测试任务")
            } else {
                jobsTable
                Divider()
                pagination
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task { await controller.refresh() }
        .onChange(of: controller.jobs.count) { _ in clampPage() }
        .onChange(of: selectedJobIDs) { ids in
            guard let id = ids.first,
                  let job = controller.jobs.first(where: { $0.id == id }) else { return }
            selectedJobIDs.removeAll()
            openJob(job)
        }
        .alert("任务错误", isPresented: errorBinding) {
            Button("好") { controller.error = nil }
        } message: {
            Text(controller.error ?? "")
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("测试").font(.title2.weight(.semibold))
                Text(verbatim: L10n.format("共 %lld 个任务，每页 %lld 个", controller.jobs.count, pageSize))
                    .font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            if controller.isLoading { ProgressView().controlSize(.small) }
            SettingsRefreshButton("刷新", isWorking: controller.isLoading) {
                Task { await controller.refresh() }
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var jobsTable: some View {
        Table(Array(pageJobs), selection: $selectedJobIDs) {
            TableColumn("任务") { job in
                Button {
                    openJob(job)
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(verbatim: ProfilePresentationText.jobKind(job.kind))
                            .font(.callout.weight(.medium))
                        Text(job.id).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .buttonStyle(.plain)
            }
            TableColumn("端口") { job in
                Text(job.port > 0 ? String(job.port) : "—")
                    .font(.callout.monospacedDigit())
            }
            TableColumn("时间") { job in
                Text(job.updatedAt.map(formatDate) ?? "—")
                    .font(.callout.monospacedDigit())
            }
            TableColumn("状态") { job in
                VStack(alignment: .leading, spacing: 3) {
                    Text(LocalizedStringKey(TestJobPresentation.statusLabel(job.status)))
                        .foregroundStyle(statusColor(job.status))
                    if ["running", "planning"].contains(job.status) {
                        ProgressView().controlSize(.mini).frame(maxWidth: 70)
                    }
                }
            }
            TableColumn("Profile") { job in
                Text(job.profile.isEmpty ? "—" : job.profile)
                    .lineLimit(1)
            }
            TableColumn("生成物") { job in
                Text("\(job.artifactCount)")
                    .font(.callout.monospacedDigit())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 12)
    }

    private var pagination: some View {
        HStack(spacing: 10) {
            Button("上一页") { page = max(1, page - 1); pageInput = String(page) }
                .disabled(page <= 1)
            Text(verbatim: L10n.format("第 %lld / %lld 页", page, pageCount))
                .font(.callout.monospacedDigit())
            Button("下一页") { page = min(pageCount, page + 1); pageInput = String(page) }
                .disabled(page >= pageCount)
            Divider().frame(height: 16)
            Text("跳转").foregroundStyle(.secondary)
            TextField("页码", text: $pageInput)
                .textFieldStyle(.roundedBorder)
                .frame(width: 54)
                .onSubmit { jumpToPage() }
            Button("确定") { jumpToPage() }
                .buttonStyle(.bordered)
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { controller.error != nil },
            set: { if !$0 { controller.error = nil } }
        )
    }

    private func jumpToPage() {
        page = min(max(Int(pageInput) ?? page, 1), pageCount)
        pageInput = String(page)
    }

    private func clampPage() {
        page = min(max(page, 1), pageCount)
        pageInput = String(page)
    }

    private func formatDate(_ date: Date) -> String {
        date.formatted(.dateTime.year().month().day().hour().minute())
    }

    private func statusColor(_ value: String) -> Color {
        switch value {
        case "succeeded": return .green
        case "failed", "cancelled": return .red
        case "running", "planning": return .blue
        case "submitted", "created", "queued": return .orange
        default: return .secondary
        }
    }

    private func emptyState(_ title: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "checklist").font(.largeTitle).foregroundStyle(.secondary)
            Text(LocalizedStringKey(title)).foregroundStyle(.secondary)
            if let error = controller.error {
                Text(error).font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
