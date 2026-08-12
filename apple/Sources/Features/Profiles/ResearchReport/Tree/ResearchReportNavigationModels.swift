import Foundation

enum ResearchReportNavigationFocus {
    static func preferred(
        pendingID: String,
        selectedID: String,
        initialID: String?
    ) -> String? {
        if !pendingID.isEmpty { return pendingID }
        if !selectedID.isEmpty { return selectedID }
        return initialID
    }
}

enum ResearchReportNavigationBehavior: Equatable {
    case instant
    case smooth
}

enum ResearchReportScrollDestination: Equatable {
    case chapterTop
    case documentBottom
}

struct ResearchReportScrollRequest: Equatable {
    let componentID: String
    let token: Int
    let behavior: ResearchReportNavigationBehavior
    let destination: ResearchReportScrollDestination

    init(
        componentID: String,
        token: Int,
        behavior: ResearchReportNavigationBehavior,
        destination: ResearchReportScrollDestination = .chapterTop
    ) {
        self.componentID = componentID
        self.token = token
        self.behavior = behavior
        self.destination = destination
    }
}

struct ResearchReportInitialDestination: Equatable {
    let componentID: String
    let scrollDestination: ResearchReportScrollDestination
}

enum ResearchReportInitialNavigation {
    static func destination(
        wasLoaded: Bool,
        hasExplicitTarget: Bool,
        outlineIDs: [String]
    ) -> ResearchReportInitialDestination? {
        guard !wasLoaded, !hasExplicitTarget,
              let tail = outlineIDs.last else { return nil }
        return ResearchReportInitialDestination(
            componentID: tail,
            scrollDestination: .documentBottom
        )
    }
}

struct ResearchReportScrollExecutionKey: Equatable {
    let token: Int
    let targetIsLoaded: Bool
}
