import Combine
import Foundation

enum ResearchModuleSection: String, CaseIterable, Identifiable {
    case researches
    case evidence
    case reports
    case graph
    case profiles
    case agentModels = "agent-models"

    var id: String { rawValue }

    static func fromResearchPath(_ path: String) -> Self? {
        guard let components = URLComponents(string: path),
              components.path == "/research",
              let rawValue = components.queryItems?.first(where: {
                  $0.name == "section"
              })?.value else {
            return nil
        }
        switch rawValue {
        case "local", "shared": return .reports
        default: return Self(rawValue: rawValue)
        }
    }
}

/// Lightweight, view-independent state retained while a client tab is open.
///
/// This deliberately stores identifiers and small value types only. Rendered
/// report trees, controllers, and NSTextViews remain owned by the selected
/// tab's view hierarchy; a small bounded WebView cache is managed separately.
final class ClientTabSession: ObservableObject {
    /// The Web research shell owns the visible switcher.  Keep this value as
    /// session metadata rather than a published view trigger: receiving the
    /// Web section callback must not reload the already-rendered WebView.
    /// A later mount still reads the value and restores the selected section.
    var researchSection = ResearchModuleSection.researches
    @Published var researchLifecycle = ResearchLifecycleFilter.active
    @Published var selectedBranchID = ""
    /// Detail values survive tab view unmounting without retaining any native
    /// text views, charts, or web content processes.
    @Published var jobDetails: [String: TestJobDetail] = [:]
    /// The session may retain a WebView while it is in the bounded cache.  The
    /// store evicts the expensive view independently of this lightweight tab
    /// state when many report/reference tabs are open.
    var webPageSession: WebPageSession?

    func ensureWebPageSession() -> WebPageSession {
        if let webPageSession { return webPageSession }
        let session = WebPageSession()
        webPageSession = session
        return session
    }

    func releaseWebPageSession() {
        webPageSession?.releaseWebView()
        webPageSession = nil
    }

    private var reportSessions: [String: ResearchReportTabSession] = [:]

    func reportSession(for reportID: String) -> ResearchReportTabSession {
        if let existing = reportSessions[reportID] { return existing }
        let session = ResearchReportTabSession()
        reportSessions[reportID] = session
        return session
    }
}

final class ResearchReportTabSession {
    var generation: Int?
    var selectedChapterID = ""
    var appliedGraphNavigationID = ""
}

final class ClientTabSessionStore: ObservableObject {
    private var sessions: [String: ClientTabSession] = [:]
    private var activationOrder: [String: UInt64] = [:]
    private var activationCounter: UInt64 = 0
    private let maxRetainedWebViews = 4

    func session(for tabID: String) -> ClientTabSession {
        if let existing = sessions[tabID] { return existing }
        let session = ClientTabSession()
        sessions[tabID] = session
        return session
    }

    /// Mark a tab active and evict only old, expensive WebViews.  Report
    /// selection, branch choice, and other small state remain in the session;
    /// reopening an evicted tab uses the same Web route and Swift tab ID.
    func activate(_ tabID: String) {
        activationCounter &+= 1
        activationOrder[tabID] = activationCounter
        var retained = sessions.filter { $0.value.webPageSession?.webView != nil }
        guard retained.count > maxRetainedWebViews else { return }
        let victims = retained
            .filter { $0.key != tabID }
            .sorted { activationOrder[$0.key, default: 0] < activationOrder[$1.key, default: 0] }
        for (id, session) in victims where retained.count > maxRetainedWebViews {
            session.releaseWebPageSession()
            retained.removeValue(forKey: id)
        }
    }

    func removeSession(for tabID: String) {
        sessions.removeValue(forKey: tabID)?.releaseWebPageSession()
        activationOrder.removeValue(forKey: tabID)
    }
}
