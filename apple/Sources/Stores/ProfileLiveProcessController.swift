import Foundation

@MainActor
final class ProfileLiveProcessController: ObservableObject {
    typealias ObservationSleep = @MainActor (TimeInterval) async throws -> Void
    typealias CheckpointChange = @MainActor (String) -> Void
    @Published var selectedWorkspaceID = ""
    @Published var selectedResearchRef = ""
    @Published var selectedBranchID = ""
    @Published private(set) var research: [ProfileResearchSummary] = []
    @Published private(set) var workPackage: ProfileResearchWorkPackageDetail?
    @Published private(set) var detail: ProfileResearchDetail?
    @Published private(set) var timeline: [ResearchTransitionStep] = []
    @Published private(set) var nextTimelineCursor: String?
    @Published private(set) var isLoading = false
    @Published private(set) var isLoadingResearch = false
    @Published private(set) var error: String?

    let workspaces: [LocalWorkspaceModel]
    private let service: ProfileResearchService
    private var workPackageETag: String?
    private var detailETag: String?
    private var timelineETag: String?
    private var observedCheckpointRef: String?
    private var activeResearchRequestID: UUID?
    private let localCheckpointRefs: [String: String]
    private let observationSleep: ObservationSleep
    private let onCheckpointChange: CheckpointChange

    init(
        profile: LocalProfileModel,
        service: ProfileResearchService? = nil,
        pinnedSummary: ProfileResearchSummary? = nil,
        initialWorkspaceID: String? = nil,
        observationSleep: ObservationSleep? = nil,
        onCheckpointChange: @escaping CheckpointChange = { _ in }
    ) {
        workspaces = profile.workspaces.filter {
            !$0.serverWorkspaceRef.isEmpty
        }
        let url = URL(string: profile.serverURL)
            ?? ServerConfig.shared.baseURL
            ?? URL(string: "http://127.0.0.1:8000")!
        self.service = service ?? ProfileResearchService(baseURL: url)
        self.observationSleep = observationSleep ?? { seconds in
            let nanoseconds = UInt64(
                min(max(seconds, 1), Double(UInt64.max) / 1_000_000_000)
                    * 1_000_000_000
            )
            try await Task.sleep(nanoseconds: nanoseconds)
        }
        self.onCheckpointChange = onCheckpointChange
        var checkpointRefs: [String: String] = [:]
        for record in profile.researchRecords
        where !record.graphBranchRef.isEmpty && !record.checkpointRef.isEmpty {
            checkpointRefs[record.graphBranchRef] = record.checkpointRef
        }
        localCheckpointRefs = checkpointRefs
        selectedWorkspaceID = initialWorkspaceID ?? workspaces.first?.id ?? ""
        if let pinnedSummary {
            research = [pinnedSummary]
            selectedResearchRef = pinnedSummary.researchRef
        }
    }

    func loadSelectedWorkspace() async {
        guard let workspace = selectedWorkspace else {
            research = []
            selectedResearchRef = ""
            error = L10n.text("Profile 尚无可映射的服务器工作区。")
            return
        }
        isLoading = true
        error = nil
        defer { isLoading = false }
        do {
            let page = try await service.list(
                workspaceRef: normalized(workspace.serverWorkspaceRef)
            )
            try Task.checkCancellation()
            research = page.items
            if !research.contains(where: {
                $0.researchRef == selectedResearchRef
            }) {
                selectedResearchRef = research.first?.researchRef ?? ""
                selectedBranchID = ""
                workPackage = nil
            }
        } catch is CancellationError {
            return
        } catch {
            self.error = message(error)
            research = []
            selectedResearchRef = ""
        }
    }

    func observeSelectedResearch() async {
        guard let summary = selectedSummary else {
            workPackage = nil
            detail = nil
            timeline = []
            return
        }
        let requestID = UUID()
        activeResearchRequestID = requestID
        isLoadingResearch = true
        error = nil
        defer {
            if activeResearchRequestID == requestID {
                isLoadingResearch = false
            }
        }
        do {
            if workPackage?.workPackageRef != summary.workPackageRef {
                let result = try await service.workPackageDetail(
                    href: summary.detailHref,
                    etag: nil
                )
                guard case .value(let value, let etag) = result else { return }
                workPackage = value
                workPackageETag = etag
                if !value.branches.contains(where: {
                    $0.branchID == selectedBranchID
                }) {
                    selectedBranchID = value.branches.first?.branchID ?? ""
                }
            }
            guard let branch = selectedBranch else {
                detail = nil
                timeline = []
                error = "研究版本树指向的分支不在当前工作包中，请刷新研究目录后重试。"
                return
            }
            detail = nil
            timeline = []
            detailETag = nil
            timelineETag = nil
            observedCheckpointRef = localCheckpointRefs[branch.branchRef]
            try await refresh(branch: branch, conditional: false)
            while let directive = detail?.refresh, !directive.terminal {
                try Task.checkCancellation()
                switch directive.mode {
                case "conditional_etag":
                    try await wait(for: directive)
                    try await refresh(branch: branch, conditional: true)
                case "job_sse":
                    guard let href = directive.href else { return }
                    for try await _ in service.events(href: href) {
                        try Task.checkCancellation()
                        try await refresh(branch: branch, conditional: true)
                        if detail?.refresh.terminal == true { return }
                    }
                    guard detail?.refresh.terminal != true else { return }
                    try await wait(for: detail?.refresh ?? directive)
                    try await refresh(branch: branch, conditional: true)
                default:
                    return
                }
            }
        } catch is CancellationError {
            if activeResearchRequestID == requestID {
                error = "研究过程读取已取消；可重新选择检查点或刷新研究。"
            }
            return
        } catch {
            if activeResearchRequestID == requestID {
                self.error = message(error)
            }
        }
    }

    func loadEarlierTimeline() async {
        guard let href = detail?.timelineHref,
              let cursor = nextTimelineCursor else { return }
        do {
            let result = try await service.timeline(
                href: href,
                after: cursor
            )
            guard case .value(let page, _) = result else { return }
            let known = Set(timeline.map(\.id))
            timeline += page.items.filter { !known.contains($0.id) }
            nextTimelineCursor = page.nextCursor
        } catch {
            self.error = message(error)
        }
    }

    func refreshSelectedResearch() async {
        guard let branch = selectedBranch else { return }
        do {
            try await refresh(branch: branch, conditional: true)
        } catch is CancellationError {
            return
        } catch {
            self.error = message(error)
        }
    }

    var selectedWorkspace: LocalWorkspaceModel? {
        workspaces.first { $0.id == selectedWorkspaceID }
    }

    var selectedSummary: ProfileResearchSummary? {
        research.first { $0.researchRef == selectedResearchRef }
    }

    var selectedBranch: ProfileResearchBranchSummary? {
        workPackage?.branches.first { $0.branchID == selectedBranchID }
    }

    var observationKey: String {
        "\(selectedResearchRef)|\(selectedBranchID)"
    }

    private func refresh(
        branch: ProfileResearchBranchSummary,
        conditional: Bool
    ) async throws {
        let previousTraceRef = detail?.latestTraceRef
        var refreshedDetail = detail
        var refreshedDetailETag = detailETag
        let detailResult = try await service.branchDetail(
            href: branch.detailHref,
            etag: conditional ? detailETag : nil
        )
        if case .value(let value, let etag) = detailResult {
            if let previousTraceRef,
               previousTraceRef != value.latestTraceRef {
                try await refreshWorkPackage()
            }
            refreshedDetail = value
            refreshedDetailETag = etag
        }
        guard let candidateDetail = refreshedDetail else { return }
        let timelineResult = try await service.timeline(
            href: candidateDetail.timelineHref,
            etag: conditional ? timelineETag : nil
        )
        var refreshedTimeline = timeline
        var refreshedCursor = nextTimelineCursor
        var refreshedTimelineETag = timelineETag
        if case .value(let page, let etag) = timelineResult {
            refreshedTimeline = page.items
            refreshedCursor = page.nextCursor
            refreshedTimelineETag = etag
        }
        try Task.checkCancellation()
        detail = candidateDetail
        detailETag = refreshedDetailETag
        timeline = refreshedTimeline
        nextTimelineCursor = refreshedCursor
        timelineETag = refreshedTimelineETag
        publishCheckpointChange(candidateDetail.latestTraceRef)
    }

    private func refreshWorkPackage() async throws {
        guard let href = selectedSummary?.detailHref else { return }
        let result = try await service.workPackageDetail(
            href: href,
            etag: workPackageETag
        )
        if case .value(let value, let etag) = result {
            workPackage = value
            workPackageETag = etag
        }
    }

    private func wait(for directive: ResearchRefreshDirective) async throws {
        let minimumIntervalSeconds = max(
            directive.minimumIntervalSeconds ?? 5,
            1
        )
        try await observationSleep(minimumIntervalSeconds)
        try Task.checkCancellation()
    }

    private func publishCheckpointChange(_ checkpointRef: String?) {
        guard let checkpointRef, !checkpointRef.isEmpty else { return }
        if let observedCheckpointRef,
           observedCheckpointRef != checkpointRef {
            onCheckpointChange(checkpointRef)
        }
        observedCheckpointRef = checkpointRef
    }

    private func normalized(_ ref: String) -> String {
        ref.hasPrefix("workspace:") ? ref : "workspace:\(ref)"
    }

    private func message(_ error: Error) -> String {
        (error as? APIError)?.errorDescription ?? error.localizedDescription
    }
}
