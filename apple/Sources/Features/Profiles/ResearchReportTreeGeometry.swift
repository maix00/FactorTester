import SwiftUI

struct ResearchReportChapterGeometry: Equatable {
    let minY: CGFloat
    let height: CGFloat
}

struct ChapterGeometryPreference: PreferenceKey {
    static var defaultValue: [
        String: ResearchReportChapterGeometry
    ] = [:]

    static func reduce(
        value: inout [String: ResearchReportChapterGeometry],
        nextValue: () -> [String: ResearchReportChapterGeometry]
    ) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

struct ChapterGeometryReporter: View {
    let id: String

    var body: some View {
        GeometryReader { proxy in
            Color.clear.preference(
                key: ChapterGeometryPreference.self,
                value: [
                    id: ResearchReportChapterGeometry(
                        minY: proxy.frame(
                            in: .named("research.report.page")
                        ).minY,
                        height: proxy.size.height
                    ),
                ]
            )
        }
    }
}

struct ResearchReportViewportHeightPreference: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(
        value: inout CGFloat,
        nextValue: () -> CGFloat
    ) {
        value = max(value, nextValue())
    }
}

struct ResearchReportViewportHeightReporter: View {
    var body: some View {
        GeometryReader { proxy in
            Color.clear.preference(
                key: ResearchReportViewportHeightPreference.self,
                value: proxy.size.height
            )
        }
    }
}
