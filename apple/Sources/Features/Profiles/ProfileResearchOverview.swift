import SwiftUI

struct ResearchDirectoryItem: Identifiable {
    let serverURL: URL
    let workspaceID: String
    let workspaceRef: String
    let profileIDs: [String]
    let profileNames: [String]
    let summary: ProfileResearchSummary

    var id: String {
        "\(serverURL.absoluteString)|\(workspaceRef)|\(summary.workPackageRef)"
    }
}

@MainActor
final class ResearchDirectoryController: ObservableObject {
    typealias Loader = @MainActor (
        _ serverURL: URL,
        _ workspaceRef: String
    ) async throws -> ProfileResearchListResponse

    @Published private(set) var items: [ResearchDirectoryItem] = []
    @Published private(set) var isLoading = false
    @Published private(set) var error: String?

    private var profiles: [LocalProfileModel]
    private let load: Loader

    init(profiles: [LocalProfileModel], load: Loader? = nil) {
        self.profiles = profiles
        self.load = load ?? { serverURL, workspaceRef in
            try await ProfileResearchService(baseURL: serverURL).list(
                workspaceRef: workspaceRef
            )
        }
    }

    func replaceProfiles(_ profiles: [LocalProfileModel]) {
        self.profiles = profiles
    }

    func refresh() async {
        isLoading = true
        error = nil
        defer { isLoading = false }
        var loaded: [ResearchDirectoryItem] = []
        var failures: [String] = []
        for binding in uniqueBindings() {
            do {
                let page = try await load(
                    binding.serverURL,
                    binding.workspaceRef
                )
                loaded += page.items.map { summary in
                    ResearchDirectoryItem(
                        serverURL: binding.serverURL,
                        workspaceID: binding.workspaceID,
                        workspaceRef: binding.workspaceRef,
                        profileIDs: binding.profiles.map(\.id),
                        profileNames: binding.profiles.map(\.displayName),
                        summary: summary
                    )
                }
            } catch {
                failures.append(error.localizedDescription)
            }
        }
        items = loaded.sorted {
            if $0.summary.updatedAt != $1.summary.updatedAt {
                return $0.summary.updatedAt > $1.summary.updatedAt
            }
            return $0.id < $1.id
        }
        if !failures.isEmpty {
            error = failures.joined(separator: " · ")
        }
    }

    private func uniqueBindings() -> [ResearchWorkspaceBinding] {
        var values: [String: ResearchWorkspaceBinding] = [:]
        for profile in profiles where profile.status == "active" {
            guard let serverURL = canonicalServerURL(profile.serverURL) else {
                continue
            }
            for workspace in profile.workspaces
            where !workspace.serverWorkspaceRef.isEmpty {
                let workspaceRef = normalized(workspace.serverWorkspaceRef)
                let key = "\(serverURL.absoluteString)|\(workspaceRef)"
                if var existing = values[key] {
                    if !existing.profiles.contains(where: {
                        $0.id == profile.id
                    }) {
                        existing.profiles.append(profile)
                        existing.profiles.sort { $0.id < $1.id }
                        values[key] = existing
                    }
                } else {
                    values[key] = ResearchWorkspaceBinding(
                        serverURL: serverURL,
                        workspaceID: workspace.id,
                        workspaceRef: workspaceRef,
                        profiles: [profile]
                    )
                }
            }
        }
        return values.values.sorted {
            "\($0.serverURL.absoluteString)|\($0.workspaceRef)"
                < "\($1.serverURL.absoluteString)|\($1.workspaceRef)"
        }
    }

    private func normalized(_ value: String) -> String {
        value.hasPrefix("workspace:") ? value : "workspace:\(value)"
    }

    private func canonicalServerURL(_ value: String) -> URL? {
        guard var components = URLComponents(string: value),
              let scheme = components.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              components.host != nil else { return nil }
        components.scheme = scheme
        components.host = components.host?.lowercased()
        components.path = components.path == "/" ? "" : components.path
        components.query = nil
        components.fragment = nil
        return components.url
    }
}

private struct ResearchWorkspaceBinding {
    let serverURL: URL
    let workspaceID: String
    let workspaceRef: String
    var profiles: [LocalProfileModel]
}

struct ProfileResearchOverview: View {
    let profiles: [LocalProfileModel]
    let openProfile: (LocalProfileModel) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("研究进度").font(.largeTitle.weight(.semibold))
                Text("按 Profile 查看当前研究步骤与已生成报告。")
                    .foregroundStyle(.secondary)
                ForEach(profiles) { profile in
                    Button { openProfile(profile) } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "person.crop.rectangle")
                                .font(.title2)
                                .foregroundStyle(.tint)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(profile.displayName).font(.headline)
                                Text(summary(profile))
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .foregroundStyle(.secondary)
                        }
                        .padding(16)
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                }
                if profiles.isEmpty {
                    Label(
                        "尚未注册 Profile，因此没有可展示的研究进度。",
                        systemImage: "chart.xyaxis.line"
                    )
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 40)
                }
            }
            .padding(24)
        }
    }

    private func summary(_ profile: LocalProfileModel) -> String {
        guard !profile.researchRecords.isEmpty else {
            return "等待研究记录"
        }
        let ready = profile.researchRecords.filter { $0.status == "ready" }.count
        return "\(profile.researchRecords.count) 项研究 · \(ready) 份报告可用"
    }
}
