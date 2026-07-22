import SwiftUI

struct ResearchDirectoryItem: Identifiable {
    let serverURL: URL
    let workspaceID: String
    let workspaceRef: String
    let profileIDs: [String]
    let profileNames: [String]
    let displayTitle: String
    let scopeSummary: String
    let summary: ProfileResearchSummary

    var id: String {
        "\(serverURL.absoluteString)|\(workspaceRef)|\(summary.workPackageRef)"
    }
}

/// Empty states are deliberately separate from a confirmed empty server
/// result.  In particular, an empty local snapshot while the bundled CLI is
/// still starting must never be rendered as "no Profile".
enum ProfileResearchEmptyState: Equatable {
    case loadingResearch
    case loadingProfiles
    case profileLoadFailed
    case noProfiles
    case noWorkPackages

    var message: String {
        switch self {
        case .loadingResearch:
            return "正在读取研究目录…"
        case .loadingProfiles:
            return "正在读取本地 Profile；暂不判断为空。"
        case .profileLoadFailed:
            return "本地 Profile 读取失败；暂不判断为空。"
        case .noProfiles:
            return "尚未注册 Profile，因此没有可展示的研究。"
        case .noWorkPackages:
            return "已读取本地 Profile，但其绑定的工作区尚无 Work Package。"
        }
    }

    var systemImage: String {
        switch self {
        case .profileLoadFailed:
            return "exclamationmark.triangle"
        case .loadingProfiles, .noProfiles:
            return "person.crop.circle"
        case .loadingResearch, .noWorkPackages:
            return "chart.xyaxis.line"
        }
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
                    let owners = authoritativeOwners(
                        for: summary,
                        in: binding.profiles
                    )
                    let record = owners
                        .flatMap(\.researchRecords)
                        .first { $0.graphInstanceRef == summary.workPackageRef }
                    return ResearchDirectoryItem(
                        serverURL: binding.serverURL,
                        workspaceID: binding.workspaceID,
                        workspaceRef: binding.workspaceRef,
                        profileIDs: owners.map(\.id),
                        profileNames: owners.map(\.displayName),
                        displayTitle: record?.preferredResearchTitle
                            ?? ResearchDisplayText.productGroup(
                                summary.productGroup
                            ),
                        scopeSummary: record?.researchScopeTitle ?? "",
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

    /// The server owns the current Work Package ownership projection.  Local
    /// research records remain useful for resolving report artifacts, but an
    /// Agent's mutable execution scope must not hide historical ownership.
    private func authoritativeOwners(
        for summary: ProfileResearchSummary,
        in profiles: [LocalProfileModel]
    ) -> [LocalProfileModel] {
        let reference = summary.currentOwnerProfileRef
            ?? summary.createdByProfileRef
        guard let reference, let profileID = profileID(from: reference) else {
            return profiles.filter {
                $0.owns(workPackageRef: summary.workPackageRef)
            }
        }
        let authoritative = profiles.filter { $0.id == profileID }
        if !authoritative.isEmpty { return authoritative }
        return profiles.filter {
            $0.owns(workPackageRef: summary.workPackageRef)
        }
    }

    private func profileID(from reference: String) -> String? {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        if value.hasPrefix("profile:") {
            let id = String(value.dropFirst("profile:".count))
            return id.isEmpty ? nil : id
        }
        return value
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
    let profileLoadState: LocalProfileLoadState
    let openWorkPackage: (ResearchDirectoryItem) -> Void
    @StateObject private var controller: ResearchDirectoryController

    init(
        profiles: [LocalProfileModel],
        profileLoadState: LocalProfileLoadState = .loaded,
        openWorkPackage: @escaping (ResearchDirectoryItem) -> Void
    ) {
        self.profiles = profiles
        self.profileLoadState = profileLoadState
        self.openWorkPackage = openWorkPackage
        _controller = StateObject(
            wrappedValue: ResearchDirectoryController(profiles: profiles)
        )
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("研究进度").font(.largeTitle.weight(.semibold))
                Text("按 Work Package 查看跨 Profile 的阶段、义务、证据与报告。")
                    .foregroundStyle(.secondary)
                if let error = controller.error {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }
                ForEach(controller.items) { item in
                    workPackageCard(item)
                }
                if let emptyState {
                    if emptyState == .loadingResearch {
                        ProgressView(emptyState.message)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 48)
                    } else {
                        Label(emptyState.message, systemImage: emptyState.systemImage)
                            .foregroundStyle(
                                emptyState == .profileLoadFailed
                                    ? .orange : .secondary
                            )
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 40)
                    }
                }
                if !controller.items.isEmpty {
                    Button("刷新") { Task { await controller.refresh() } }
                        .buttonStyle(.bordered)
                }
            }
            .padding(24)
        }
        .task(id: bindingSignature) {
            controller.replaceProfiles(profiles)
            await controller.refresh()
        }
    }

    private func workPackageCard(_ item: ResearchDirectoryItem) -> some View {
        Button { openWorkPackage(item) } label: {
            HStack(spacing: 16) {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                    .font(.title2)
                    .foregroundStyle(.tint)
                    .frame(width: 34)
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 8) {
                        Text(item.displayTitle)
                        .font(.headline)
                        statusBadge(item.summary)
                    }
                    if !item.scopeSummary.isEmpty,
                       item.scopeSummary != item.displayTitle {
                        Text(item.scopeSummary)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Text(
                        "\(ResearchDisplayText.productGroup(item.summary.productGroup)) · "
                            + "\(item.summary.branchCount) 个分支 · "
                            + "\(item.summary.runningBranchCount) 个进行中"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    Label {
                        Text(
                            item.profileNames.isEmpty
                                ? "Profile 归属不可用"
                                : "关联 Profile：\(item.profileNames.joined(separator: "、"))"
                        )
                    } icon: {
                        Image(systemName: item.profileNames.isEmpty
                            ? "person.crop.circle.badge.questionmark"
                            : "person.2")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    Text(item.serverURL.host ?? item.serverURL.absoluteString)
                    Text(item.summary.workPackageRef)
                }
                .font(.caption.monospaced())
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                Image(systemName: "chevron.right")
                    .foregroundStyle(.secondary)
            }
            .padding(16)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(.separator, lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
    }

    private func statusBadge(_ summary: ProfileResearchSummary) -> some View {
        Text(summary.runningBranchCount > 0 ? "进行中" : summary.status)
            .font(.caption.weight(.semibold))
            .foregroundStyle(summary.runningBranchCount > 0 ? .blue : .secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(
                summary.runningBranchCount > 0
                    ? Color.blue.opacity(0.10) : Color.secondary.opacity(0.10),
                in: Capsule()
            )
    }

    private var bindingSignature: String {
        profiles.map { profile in
            let refs = profile.workspaces.map(\.serverWorkspaceRef).joined(separator: ",")
            return "\(profile.id)|\(profile.serverURL)|\(refs)"
        }.sorted().joined(separator: ";")
    }

    private var emptyState: ProfileResearchEmptyState? {
        guard controller.items.isEmpty else { return nil }
        if controller.isLoading { return .loadingResearch }
        switch profileLoadState {
        case .loading, .idle:
            return .loadingProfiles
        case .failed:
            return .profileLoadFailed
        case .loaded:
            return profiles.isEmpty ? .noProfiles : .noWorkPackages
        }
    }
}
