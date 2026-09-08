import SwiftUI
import AppKit

/// Open a local profile workspace folder in Finder, revealing its contents.
func revealWorkspace(_ path: String) {
    guard !path.isEmpty else { return }
    let url = URL(fileURLWithPath: path, isDirectory: true)
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    NSWorkspace.shared.activateFileViewerSelecting([url])
}

struct ProfileOverviewSection: View {
    let profile: LocalProfileModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("工作区") {
                    VStack(alignment: .leading, spacing: 8) {
                        Label(
                            "独立可写研究工作区",
                            systemImage: "pencil.and.list.clipboard"
                        )
                        .font(.headline)
                        Text(profile.workspaceRoot)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                        if !profile.workspaceRoot.isEmpty {
                            Button {
                                revealWorkspace(profile.workspaceRoot)
                            } label: {
                                Label("打开访达", systemImage: "folder")
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        }
                        Text("Agent 的因子修改、过程文件和报告写入这里。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                }
                GroupBox("共享只读初始化来源") {
                    VStack(alignment: .leading, spacing: 8) {
                        if profile.initializationSources.isEmpty {
                            Text("尚未绑定已授权的个人因子库。")
                                .foregroundStyle(.secondary)
                        }
                        ForEach(profile.initializationSources) { source in
                            HStack {
                                Label(
                                    source.ownerRef,
                                    systemImage: "books.vertical"
                                )
                                Spacer()
                                Text(verbatim: L10n.format(
                                    "只读 · %@",
                                    ProfilePresentationText.initializationSourceMode(source.mode)
                                ))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Text("初始化来源只提供引用，不是 Agent 的可写源码目录。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                }
                GroupBox("研究身份") {
                    HStack {
                        LabeledContent(
                            "Agents", value: "\(profile.agents.count)"
                        )
                        Spacer()
                        LabeledContent(
                            "研究记录",
                            value: "\(profile.researchRecords.count)"
                        )
                    }
                    .padding(8)
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
                Text(LocalizedStringKey(title)).font(.title2.weight(.semibold))
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
