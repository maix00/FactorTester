import SwiftUI

struct ResearchReportTreePage: View {
    let title: String
    let profileName: String
    let currentNode: String
    let error: String?
    let isLoading: Bool
    let assets: [ResearchDocumentAsset]
    let reportRef: String
    let scrollRequest: ResearchReportScrollRequest?
    let scrollAnchorCoordinator: ResearchReportScrollAnchorCoordinator
    let readingPositionChanged: (ResearchReportReadingAnchor) -> Void
    let visibleChapter: (String) -> Void

    let chapterOrder: [String]
    let rootComponentsByID: [String: ResearchDocumentComponent]
    let childrenByParent: [String: [ResearchDocumentComponent]]
    let bindingsByComponent: [String: [ResearchDocumentBinding]]
    @State var lastScrollToken = -1
    @State var lastReportedVisibleChapterID = ""
    @State var highlightedComponentID = ""
    @State var chapterGeometry: [
        String: ResearchReportChapterGeometry
    ] = [:]
    @State var viewportHeight: CGFloat = 0
    @State var highlightTask: Task<Void, Never>?

    init(
        title: String,
        profileName: String,
        currentNode: String,
        error: String?,
        isLoading: Bool,
        components: [ResearchDocumentComponent],
        assets: [ResearchDocumentAsset],
        bindings: [ResearchDocumentBinding],
        chapterOrder: [String],
        reportRef: String,
        scrollRequest: ResearchReportScrollRequest?,
        scrollAnchorCoordinator: ResearchReportScrollAnchorCoordinator,
        readingPositionChanged: @escaping (ResearchReportReadingAnchor) -> Void,
        visibleChapter: @escaping (String) -> Void
    ) {
        self.title = title
        self.profileName = profileName
        self.currentNode = currentNode
        self.error = error
        self.isLoading = isLoading
        self.assets = assets
        self.reportRef = reportRef
        self.scrollRequest = scrollRequest
        self.scrollAnchorCoordinator = scrollAnchorCoordinator
        self.readingPositionChanged = readingPositionChanged
        self.visibleChapter = visibleChapter
        self.chapterOrder = chapterOrder
        self.rootComponentsByID = Dictionary(
            uniqueKeysWithValues: components
                .filter { $0.parentID == nil }
                .map { ($0.id, $0) }
        )
        self.childrenByParent = Dictionary(grouping: components.compactMap { component in
            component.parentID.map { ($0, component) }
        }, by: \.0).mapValues { $0.map(\.1) }
        self.bindingsByComponent = Dictionary(grouping: bindings, by: \.componentID)
    }

    var body: some View {
        return ScrollViewReader { proxy in
            ScrollView {
                // The mounted chapter window is deliberately bounded. Use an
                // eager stack here so AppKit-backed rich text and tables can
                // settle their new heights before the following chapter is
                // positioned. A lazy stack may temporarily reuse the old
                // height during disclosure and visually pull the next chapter
                // into the expanded content.
                VStack(alignment: .leading, spacing: 18) {
                    header
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.secondary)
                    } else if isLoading {
                        ProgressView(L10n.text("正在读取本地研究报告…"))
                    } else if chapterOrder.isEmpty {
                        Label(
                            L10n.text("当前研究报告尚无章节"),
                            systemImage: "doc.text"
                        )
                        .foregroundStyle(.secondary)
                    } else {
                        ForEach(
                            materializedChapterOrder,
                            id: \.self
                        ) { componentID in
                            chapterSlot(componentID)
                                .id(componentID)
                                .background(ChapterGeometryReporter(
                                    id: componentID
                                ))
                        }
                    }
                }
                .onPreferenceChange(ChapterGeometryPreference.self) { geometry in
                    let positionsChanged = chapterPositionsChanged(
                        from: chapterGeometry,
                        to: geometry
                    )
                    guard positionsChanged else { return }
                    chapterGeometry = geometry
                    let positions = geometry.mapValues(\.minY)
                    scrollAnchorCoordinator.updateChapterPositions(positions)
                    updateVisibleChapter(positions)
                }
                .frame(maxWidth: 820, alignment: .leading)
                .background(ResearchReportScrollViewResolver(
                    coordinator: scrollAnchorCoordinator
                ))
                .environment(
                    \.researchReportScrollAnchorCoordinator,
                    scrollAnchorCoordinator
                )
                .padding(.horizontal, 42)
                .padding(.vertical, 34)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .accessibilityIdentifier("research.report.page")
            .coordinateSpace(name: "research.report.page")
            .background(ResearchReportViewportHeightReporter())
            .onPreferenceChange(
                ResearchReportViewportHeightPreference.self
            ) { height in
                if abs(viewportHeight - height) > 1 {
                    viewportHeight = height
                    updateVisibleChapter(chapterPositions)
                }
            }
            .task(id: scrollExecutionKey) {
                await scrollIfNeeded(proxy)
            }
            .onDisappear {
                highlightTask?.cancel()
                highlightTask = nil
            }
        }
    }
}
