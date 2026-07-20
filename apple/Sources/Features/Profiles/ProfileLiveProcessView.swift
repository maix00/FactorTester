import SwiftUI

private enum LiveProjectionState {
    case disconnected
    case loading
    case connected([ProfileResearchSummary])
    case failed(String)
}

struct ProfileLiveProcessView: View {
    let profile: LocalProfileModel
    @State private var state = LiveProjectionState.disconnected

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("实时过程").font(.title2.weight(.semibold))
                Text("只读取有界 projection；后续更新使用 SSE 或 ETag，不轮询完整 trace。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                switch state {
                case .disconnected:
                    status(
                        "等待实时过程连接",
                        "Profile 尚无可映射的服务器工作区。",
                        "antenna.radiowaves.left.and.right.slash"
                    )
                    localIndex
                case .loading:
                    ProgressView("正在连接实时过程…")
                case .connected(let items):
                    if items.isEmpty {
                        status("尚无运行中研究", "服务器返回了空的有界列表。", "clock")
                    }
                    ForEach(items) { item in researchRow(item) }
                case .failed(let message):
                    status("实时过程暂不可用", message, "exclamationmark.triangle")
                    localIndex
                }
            }
            .padding(20)
        }
        .task(id: workspaceRef) { await load() }
    }

    private var workspaceRef: String? {
        profile.workspaces.lazy
            .map(\.serverWorkspaceRef)
            .first { !$0.isEmpty }
            .map { $0.hasPrefix("workspace:") ? $0 : "workspace:\($0)" }
    }

    private var localIndex: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(profile.researchRecords.flatMap(\.timeline)) { link in
                GroupBox {
                    LabeledContent(link.kind, value: link.targetRef)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func researchRow(_ item: ProfileResearchSummary) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text(item.label).font(.headline)
                    Spacer()
                    Text(item.status)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                Label(item.currentNode, systemImage: "point.topleft.down.curvedto.point.bottomright.up")
                    .font(.callout)
                if let trial = item.trialPlanRef {
                    LabeledContent("Trial Plan", value: trial)
                        .font(.caption)
                }
            }
            .textSelection(.enabled)
        }
    }

    private func status(
        _ title: String,
        _ detail: String,
        _ image: String
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: image).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 16)
    }

    private func load() async {
        guard let workspaceRef else {
            state = .disconnected
            return
        }
        state = .loading
        do {
            let response = try await APIClient.shared.profileResearchList(
                workspaceRef: workspaceRef
            )
            state = .connected(response.items)
        } catch {
            state = .failed(
                (error as? APIError)?.errorDescription
                    ?? error.localizedDescription
            )
        }
    }
}
