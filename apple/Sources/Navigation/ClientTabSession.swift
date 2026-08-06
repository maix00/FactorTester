import Combine
import Foundation

enum ResearchModuleSection: String, CaseIterable, Identifiable {
    case local
    case shared
    case graph

    var id: String { rawValue }
}

/// Lightweight, view-independent state retained while a client tab is open.
///
/// This deliberately stores identifiers and small value types only. Rendered
/// report trees, controllers, NSTextViews, and WKWebViews remain owned by the
/// selected tab's view hierarchy and are released when that tab is unmounted.
final class ClientTabSession: ObservableObject {
    @Published var researchSection = ResearchModuleSection.local
    @Published var researchLifecycle = ResearchLifecycleFilter.active
    @Published var selectedResearchGraphEndpointID: String?
    @Published var selectedResearchGraphVersion: Int?
    @Published var selectedResearchGraphElement: ResearchGraphSelection?
    @Published var selectedBranchID = ""
    /// Detail values survive tab view unmounting without retaining any native
    /// text views, charts, or web content processes.
    @Published var jobDetails: [String: TestJobDetail] = [:]
    /// One WebView is retained per tab, while the surrounding SwiftUI tree is
    /// still released when the tab is not selected.
    var webPageSession: WebPageSession?

    func ensureWebPageSession() -> WebPageSession {
        if let webPageSession { return webPageSession }
        let session = WebPageSession()
        webPageSession = session
        return session
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

    func session(for tabID: String) -> ClientTabSession {
        if let existing = sessions[tabID] { return existing }
        let session = ClientTabSession()
        sessions[tabID] = session
        return session
    }

    func removeSession(for tabID: String) {
        sessions.removeValue(forKey: tabID)
    }
}
