import Foundation

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
    let chapterOffset: CGFloat
    let destination: ResearchReportScrollDestination

    init(
        componentID: String,
        token: Int,
        behavior: ResearchReportNavigationBehavior,
        chapterOffset: CGFloat = 0,
        destination: ResearchReportScrollDestination = .chapterTop
    ) {
        self.componentID = componentID
        self.token = token
        self.behavior = behavior
        self.chapterOffset = max(0, chapterOffset)
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

struct ResearchReportReadingAnchor: Equatable {
    let componentID: String
    let chapterOffset: CGFloat
}

enum ResearchReportScrollAnchorMath {
    static func restoredReadingOffset(
        currentOffset: CGFloat,
        chapterOffset: CGFloat
    ) -> CGFloat {
        currentOffset + max(0, chapterOffset)
    }

    static func restoredViewportOffset(
        currentOffset: CGFloat,
        previousAnchorPosition: CGFloat,
        currentAnchorPosition: CGFloat
    ) -> CGFloat {
        max(0, currentOffset + currentAnchorPosition - previousAnchorPosition)
    }
}

struct ResearchReportScrollExecutionKey: Equatable {
    let token: Int
    let targetIsLoaded: Bool
}
