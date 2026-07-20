import Foundation

@MainActor
final class ProfileLiveProcessController: ObservableObject {
    @Published var selectedWorkspaceID = ""
    @Published var selectedResearchRef = ""
    @Published private(set) var research: [ProfileResearchSummary] = []
    @Published private(set) var detail: ProfileResearchDetail?
    @Published private(set) var timeline: [ResearchTransitionStep] = []
    @Published private(set) var nextTimelineCursor: String?
    @Published private(set) var isLoading = false
    @Published private(set) var error: String?

    let workspaces: [LocalWorkspaceModel]
    private let service: ProfileResearchService
    private let clock: ResearchRefreshClock
    private var detailETag: String?
    private var timelineETag: String?

    init(
        profile: LocalProfileModel,
        service: ProfileResearchService? = nil,
        clock: ResearchRefreshClock = SystemResearchRefreshClock()
    ) {
        workspaces = profile.workspaces.filter {
            !$0.serverWorkspaceRef.isEmpty
        }
        let url = URL(string: profile.serverURL)
            ?? ServerConfig.shared.baseURL
            ?? URL(string: "http://127.0.0.1:8000")!
        self.service = service ?? ProfileResearchService(baseURL: url)
        self.clock = clock
        selectedWorkspaceID = workspaces.first?.id ?? ""
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
            detail = nil
            timeline = []
            return
        }
        detail = nil
        timeline = []
        detailETag = nil
        timelineETag = nil
        do {
            try await refresh(summary: summary, conditional: false)
            while !Task.isCancelled, let directive = detail?.refresh {
                if directive.terminal || directive.mode == "stopped" { return }
                if directive.mode == "job_sse", let href = directive.href {
                    for try await _ in service.events(href: href) {
                        try Task.checkCancellation()
                        try await refresh(summary: summary, conditional: true)
                        if detail?.refresh.terminal == true { return }
                    }
                    try Task.checkCancellation()
                    try await refresh(summary: summary, conditional: true)
                    if detail?.refresh.mode == "job_sse",
                       detail?.refresh.terminal == false {
                        try await clock.sleep(seconds: 5)
                    }
                } else {
                    let seconds = max(
                        directive.minimumIntervalSeconds ?? 5,
                        5
                    )
                    try await clock.sleep(seconds: seconds)
                    try Task.checkCancellation()
                    try await refresh(summary: summary, conditional: true)
                }
            }
        } catch is CancellationError {
            return
        } catch {
            self.error = message(error)
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

    var selectedWorkspace: LocalWorkspaceModel? {
        workspaces.first { $0.id == selectedWorkspaceID }
    }

    var selectedSummary: ProfileResearchSummary? {
        research.first { $0.researchRef == selectedResearchRef }
    }

    private func refresh(
        summary: ProfileResearchSummary,
        conditional: Bool
    ) async throws {
        let detailResult = try await service.detail(
            href: summary.detailHref,
            etag: conditional ? detailETag : nil
        )
        if case .value(let value, let etag) = detailResult {
            detail = value
            detailETag = etag
        }
        guard let href = detail?.timelineHref else { return }
        let timelineResult = try await service.timeline(
            href: href,
            etag: conditional ? timelineETag : nil
        )
        if case .value(let page, let etag) = timelineResult {
            timeline = page.items
            nextTimelineCursor = page.nextCursor
            timelineETag = etag
        }
    }

    private func normalized(_ ref: String) -> String {
        ref.hasPrefix("workspace:") ? ref : "workspace:\(ref)"
    }

    private func message(_ error: Error) -> String {
        (error as? APIError)?.errorDescription ?? error.localizedDescription
    }
}
