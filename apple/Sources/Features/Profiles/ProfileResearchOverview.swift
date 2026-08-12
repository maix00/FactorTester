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
        "\(serverURL.absoluteString)|\(summary.workPackageRef)"
    }
}

enum ResearchLifecycleFilter: String, CaseIterable, Identifiable {
    case active
    case archived
    case deleted

    var id: String { rawValue }

    var title: String {
        switch self {
        case .active: return "研究中"
        case .archived: return "已归档"
        case .deleted: return "最近删除"
        }
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
    typealias LifecycleLoader = @MainActor (
        _ serverURL: URL,
        _ workspaceRef: String,
        _ lifecycle: String
    ) async throws -> ProfileResearchListResponse
    typealias LifecycleMutator = @MainActor (
        _ item: ResearchDirectoryItem,
        _ target: String,
        _ reason: String
    ) async throws -> Void

    @Published private(set) var items: [ResearchDirectoryItem] = []
    @Published private(set) var isLoading = false
    @Published private(set) var error: String?
    @Published private(set) var lifecycle: ResearchLifecycleFilter = .active

    private var profiles: [LocalProfileModel]
    private let load: LifecycleLoader
    private let mutate: LifecycleMutator

    init(
        profiles: [LocalProfileModel],
        load: Loader? = nil,
        lifecycleLoad: LifecycleLoader? = nil,
        mutate: LifecycleMutator? = nil
    ) {
        self.profiles = profiles
        if let lifecycleLoad {
            self.load = lifecycleLoad
        } else if let load {
            self.load = { serverURL, workspaceRef, _ in
                try await load(serverURL, workspaceRef)
            }
        } else {
            self.load = { serverURL, workspaceRef, lifecycle in
                try await ProfileResearchService.unified(serviceURL: serverURL).list(
                    workspaceRef: workspaceRef,
                    lifecycle: lifecycle
                )
            }
        }
        self.mutate = mutate ?? { item, target, reason in
            _ = try await ProfileResearchService.unified(
                serviceURL: item.serverURL
            ).transitionLifecycle(
                workPackageRef: item.summary.workPackageRef,
                target: target,
                expectedRevision: item.summary.lifecycleRevision ?? 1,
                reason: reason
            )
        }
    }

    func replaceProfiles(_ profiles: [LocalProfileModel]) {
        self.profiles = profiles
    }

    func refresh(lifecycle: ResearchLifecycleFilter = .active) async {
        self.lifecycle = lifecycle
        isLoading = true
        error = nil
        // Seed the directory from the local Profile snapshot first.  The
        // server projection may refine ownership and lifecycle, but it must
        // not make the local research directory blank while a port is down.
        let localItems = localSnapshotItems(lifecycle: lifecycle)
        if !localItems.isEmpty {
            items = localItems
        }
        defer { isLoading = false }
        var loaded: [ResearchDirectoryItem] = []
        var failures: [String] = []
        for binding in uniqueServerBindings() {
            do {
                let page = try await load(
                    binding.serverURL,
                    "",
                    lifecycle.rawValue
                )
                loaded += page.items.map { summary in
                    let owners = authoritativeOwners(
                        for: summary,
                        in: binding.profiles
                    )
                    let record = owners
                        .flatMap(\.researchRecords)
                        .first {
                            $0.graphInstanceRef == summary.workPackageRef
                        }
                    return ResearchDirectoryItem(
                        serverURL: binding.serverURL,
                        workspaceID: workspaceID(
                            for: summary.workspaceRef,
                            in: owners
                        ),
                        workspaceRef: summary.workspaceRef,
                        profileIDs: owners.map(\.id),
                        profileNames: owners.map(\.displayName),
                        displayTitle: researchTitle(
                            serverTitle: summary.title,
                            localRecord: record
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
        if loaded.isEmpty, !localItems.isEmpty {
            items = localItems
        }
        if !failures.isEmpty {
            error = failures.joined(separator: " · ")
        }
    }

    private func localSnapshotItems(
        lifecycle: ResearchLifecycleFilter
    ) -> [ResearchDirectoryItem] {
        profiles.flatMap { profile in
            profile.researchRecords.compactMap { record -> ResearchDirectoryItem? in
                let status = record.status.isEmpty ? "active" : record.status
                guard status == lifecycle.rawValue else { return nil }
                guard !record.graphInstanceRef.isEmpty else { return nil }
                guard let serverURL = canonicalServerURL(profile.serverURL) else {
                    return nil
                }
                let workspaceRef = profile.workspaces.first?.serverWorkspaceRef ?? ""
                let ref = record.graphInstanceRef
                let summary = ProfileResearchSummary(
                    researchRef: ref,
                    workPackageRef: record.graphInstanceRef,
                    workspaceRef: workspaceRef,
                    title: record.preferredResearchTitle,
                    productGroup: record.productGroup,
                    productScope: nil,
                    status: status,
                    branchCount: 1,
                    runningBranchCount: status == "active" ? 1 : 0,
                    updatedAt: 0,
                    detailHref: "",
                    reportLookupRef: nil,
                    createdByProfileRef: profile.principalRef,
                    currentOwnerProfileRef: profile.principalRef,
                    lifecycle: status,
                    lifecycleRevision: nil
                )
                return ResearchDirectoryItem(
                    serverURL: serverURL,
                    workspaceID: profile.workspaces.first?.id ?? "",
                    workspaceRef: workspaceRef,
                    profileIDs: [profile.id],
                    profileNames: [profile.displayName],
                    displayTitle: record.preferredResearchTitle,
                    scopeSummary: record.researchScopeTitle,
                    summary: summary
                )
            }
        }
    }

    private func researchTitle(
        serverTitle: String?,
        localRecord: ResearchRecordModel?
    ) -> String {
        let server = serverTitle?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !server.isEmpty { return server }
        let local = localRecord?.preferredResearchTitle
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return local.isEmpty ? "未命名研究" : local
    }

    func transition(
        _ item: ResearchDirectoryItem,
        to target: ResearchLifecycleFilter
    ) async {
        isLoading = true
        error = nil
        do {
            try await mutate(
                item,
                target.rawValue,
                lifecycleReason(from: lifecycle, to: target)
            )
            await refresh(lifecycle: lifecycle)
        } catch {
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    private func lifecycleReason(
        from source: ResearchLifecycleFilter,
        to target: ResearchLifecycleFilter
    ) -> String {
        "FTClient 用户操作：\(source.title) → \(target.title)"
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

    private func uniqueServerBindings() -> [ResearchServerBinding] {
        var values: [String: ResearchServerBinding] = [:]
        for profile in profiles where profile.status == "active" {
            guard let serverURL = canonicalServerURL(profile.serverURL) else {
                continue
            }
            let key = serverURL.absoluteString
            if var existing = values[key] {
                if !existing.profiles.contains(where: {
                    $0.id == profile.id
                }) {
                    existing.profiles.append(profile)
                    existing.profiles.sort { $0.id < $1.id }
                    values[key] = existing
                }
            } else {
                values[key] = ResearchServerBinding(
                    serverURL: serverURL,
                    profiles: [profile]
                )
            }
        }
        return values.values.sorted {
            $0.serverURL.absoluteString < $1.serverURL.absoluteString
        }
    }

    private func workspaceID(
        for workspaceRef: String,
        in profiles: [LocalProfileModel]
    ) -> String {
        let normalizedRef = normalizedWorkspaceRef(workspaceRef)
        for workspace in profiles.flatMap(\.workspaces) {
            if normalizedWorkspaceRef(workspace.serverWorkspaceRef)
                == normalizedRef {
                return workspace.id
            }
        }
        return workspaceRef.hasPrefix("workspace:")
            ? String(workspaceRef.dropFirst("workspace:".count))
            : workspaceRef
    }

    private func normalizedWorkspaceRef(_ value: String) -> String {
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

private struct ResearchServerBinding {
    let serverURL: URL
    var profiles: [LocalProfileModel]
}

struct ProfileResearchOverview: View {
    let profiles: [LocalProfileModel]
    let profileLoadState: LocalProfileLoadState
    let isActive: Bool
    @Binding var lifecycle: ResearchLifecycleFilter
    let openWorkPackage: (ResearchDirectoryItem) -> Void
    @StateObject private var controller: ResearchDirectoryController
    @StateObject private var publicationStatus = ResearchPublicationStatusController()

    init(
        profiles: [LocalProfileModel],
        profileLoadState: LocalProfileLoadState = .loaded,
        isActive: Bool = true,
        lifecycle: Binding<ResearchLifecycleFilter> = .constant(.active),
        openWorkPackage: @escaping (ResearchDirectoryItem) -> Void
    ) {
        self.profiles = profiles
        self.profileLoadState = profileLoadState
        self.isActive = isActive
        _lifecycle = lifecycle
        self.openWorkPackage = openWorkPackage
        _controller = StateObject(
            wrappedValue: ResearchDirectoryController(profiles: profiles)
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("研究进度").font(.largeTitle.weight(.semibold))
            Text("按 Work Package 查看跨 Profile 的阶段、义务、证据与报告。")
                .foregroundStyle(.secondary)
            Picker("研究状态", selection: $lifecycle) {
                ForEach(ResearchLifecycleFilter.allCases) { value in
                    Text(LocalizedStringKey(value.title)).tag(value)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 420)
            if let error = controller.error {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }
            if controller.items.isEmpty {
                emptyContent
            } else {
                researchList
                Button("刷新") {
                    Task { await controller.refresh(lifecycle: lifecycle) }
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(24)
        .frame(
            maxWidth: .infinity,
            maxHeight: .infinity,
            alignment: .topLeading
        )
        .task(
            id: "\(isActive)|\(bindingSignature)|\(profileLoadState)|\(lifecycle.rawValue)"
        ) {
            controller.replaceProfiles(profiles)
            // Wait for the shared profile controller before the first refresh;
            // an empty initial snapshot is not an authoritative empty list.
            guard isActive, profileLoadState == .loaded else { return }
            async let research: Void = controller.refresh(lifecycle: lifecycle)
            async let publications: Void = publicationStatus.refresh()
            _ = await (research, publications)
        }
    }

    private var researchList: some View {
        List(controller.items) { item in
            HStack(spacing: 12) {
                Button { openWorkPackage(item) } label: {
                    researchRow(item)
                }
                .buttonStyle(.plain)
                lifecycleActions(item)
            }
            .padding(.vertical, 4)
        }
        .listStyle(.inset)
        .frame(minHeight: 220)
    }

    private func researchRow(_ item: ResearchDirectoryItem) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.title3)
                .foregroundStyle(.tint)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(item.displayTitle).font(.headline)
                    statusBadge(item.summary)
                    if isShared(item) {
                        Text("正在共享")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.blue)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(.blue.opacity(0.10), in: Capsule())
                    }
                }
                Text(verbatim: L10n.format(
                    "%@ · %lld 个分支 · %lld 个进行中",
                    ResearchDisplayText.productGroup(item.summary.productGroup),
                    item.summary.branchCount,
                    item.summary.runningBranchCount
                ))
                .font(.callout)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 3) {
                Text(item.profileNames.isEmpty
                     ? "未分配 Profile"
                     : item.profileNames.joined(separator: "、"))
                .font(.callout)
                .lineLimit(1)
                Text(item.summary.workPackageRef)
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var emptyContent: some View {
        if let emptyState {
            if emptyState == .loadingResearch {
                ProgressView(LocalizedStringKey(emptyState.message))
                    .frame(maxWidth: .infinity, minHeight: 220)
            } else {
                Label(
                    LocalizedStringKey(emptyState.message),
                    systemImage: emptyState.systemImage
                )
                .foregroundStyle(emptyState == .profileLoadFailed ? .orange : .secondary)
                .frame(maxWidth: .infinity, minHeight: 220)
            }
        }
    }

    @ViewBuilder
    private func lifecycleActions(_ item: ResearchDirectoryItem) -> some View {
        HStack(spacing: 8) {
            switch lifecycle {
            case .active:
                lifecycleButton(
                    title: "归档",
                    systemImage: "archivebox",
                    role: nil
                ) {
                    Task { await controller.transition(item, to: .archived) }
                }
                lifecycleButton(
                    title: "删除",
                    systemImage: "trash",
                    role: .destructive
                ) {
                    Task { await controller.transition(item, to: .deleted) }
                }
            case .archived:
                lifecycleButton(
                    title: "重新启用",
                    systemImage: "arrow.uturn.backward",
                    role: nil
                ) {
                    Task { await controller.transition(item, to: .active) }
                }
                lifecycleButton(
                    title: "删除",
                    systemImage: "trash",
                    role: .destructive
                ) {
                    Task { await controller.transition(item, to: .deleted) }
                }
            case .deleted:
                lifecycleButton(
                    title: "恢复到已归档",
                    systemImage: "arrow.uturn.backward",
                    role: nil
                ) {
                    Task { await controller.transition(item, to: .archived) }
                }
            }
        }
        .buttonStyle(.borderless)
        .fixedSize()
    }

    private func lifecycleButton(
        title: String,
        systemImage: String,
        role: ButtonRole?,
        action: @escaping () -> Void
    ) -> some View {
        Button(role: role, action: action) {
            Image(systemName: systemImage)
                .font(.callout.weight(.semibold))
                .frame(width: 28, height: 28)
        }
        .accessibilityLabel(L10n.text(title))
        .help(L10n.text(title))
    }

    private func statusBadge(_ summary: ProfileResearchSummary) -> some View {
        let lifecycle = summary.lifecycle ?? "active"
        let label: String = switch lifecycle {
        case "archived": "已归档"
        case "deleted": "最近删除"
        default: summary.runningBranchCount > 0 ? "进行中" : summary.status
        }
        let color: Color = switch lifecycle {
        case "archived": .secondary
        case "deleted": .orange
        default: summary.runningBranchCount > 0 ? .blue : .secondary
        }
        return Text(LocalizedStringKey(label))
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(
                color.opacity(0.10),
                in: Capsule()
            )
    }

    private func isShared(_ item: ResearchDirectoryItem) -> Bool {
        guard let reportID = item.summary.reportLookupRef else { return false }
        return publicationStatus.sharedReportIDs.contains(reportID)
    }

    private var bindingSignature: String {
        profiles.map { profile in
            let refs = profile.workspaces.map(\.serverWorkspaceRef).joined(separator: ",")
            let research = profile.researchRecords.map { record in
                let reports = record.artifacts.map {
                    "\($0.id)|\($0.localRef)"
                }.joined(separator: ",")
                return "\(record.id)|\(record.title)|\(reports)"
            }.joined(separator: ";")
            return "\(profile.id)|\(profile.serverURL)|\(refs)|\(research)"
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
