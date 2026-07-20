import SwiftUI

struct ProfileOverviewSection: View {
    let profile: LocalProfileModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("工作区") {
                    LabeledContent("服务器", value: profile.serverURL)
                    LabeledContent("本地目录", value: profile.workspaceRoot)
                }
                GroupBox("初始化与 Agent") {
                    LabeledContent(
                        "因子库授权", value: "\(profile.initializationSources.count)"
                    )
                    LabeledContent("Agents", value: "\(profile.agents.count)")
                    LabeledContent("研究记录", value: "\(profile.researchRecords.count)")
                }
                if profile.initializationSources.isEmpty {
                    Label(
                        "尚未从已授权的个人因子库初始化。",
                        systemImage: "books.vertical"
                    )
                    .foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
    }
}

struct ProfileReferenceSection: View {
    let profile: LocalProfileModel
    let kind: String?
    let title: String
    let empty: String

    private var links: [ResearchDeepLinkModel] {
        let all = profile.researchRecords.flatMap(\.timeline)
        guard let kind else { return all }
        return all.filter { $0.kind.localizedCaseInsensitiveContains(kind) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(title).font(.title2.weight(.semibold))
                Text("仅展示本地索引和有界 projection 引用；不轮询完整 trace。")
                    .font(.caption).foregroundStyle(.secondary)
                if links.isEmpty {
                    Label(empty, systemImage: "clock.badge.questionmark")
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 36)
                }
                ForEach(links) { link in
                    GroupBox {
                        LabeledContent(link.kind, value: link.targetRef)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(20)
        }
    }
}

struct ProfileReportsSection: View {
    let profile: LocalProfileModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("报告").font(.title2.weight(.semibold))
                Text("报告按步骤关联显示；原始 Markdown 仅作为辅助入口。")
                    .foregroundStyle(.secondary)
                ResearchHistoryView(profile: profile)
            }
            .padding(20)
        }
    }
}
