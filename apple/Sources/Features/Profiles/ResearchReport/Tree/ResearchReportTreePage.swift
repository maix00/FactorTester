import SwiftUI

struct ResearchReportTreePage: View {
    let title: String
    let error: String?
    let isLoading: Bool
    let assets: [ResearchDocumentAsset]
    let reportRef: String
    let scrollRequest: ResearchReportScrollRequest?
    @ObservedObject var scrollAnchorCoordinator:
        ResearchReportScrollAnchorCoordinator
    let pageBoundary: (Int) -> Void
    let canPageBoundary: (Int) -> Bool

    let chapterOrder: [String]
    let rootComponentsByID: [String: ResearchDocumentComponent]
    let childrenByParent: [String: [ResearchDocumentComponent]]
    let bindingsByComponent: [String: [ResearchDocumentBinding]]
    @State var lastScrollToken = -1
    @State var highlightedComponentID = ""
    @State var highlightTask: Task<Void, Never>?
    @State var chapterDisclosureMode =
        ResearchReportChapterDisclosureMode.defaultExpanded
    @State var chapterDisclosureRevision = 0

    init(
        title: String,
        error: String?,
        isLoading: Bool,
        components: [ResearchDocumentComponent],
        assets: [ResearchDocumentAsset],
        bindings: [ResearchDocumentBinding],
        chapterOrder: [String],
        reportRef: String,
        scrollRequest: ResearchReportScrollRequest?,
        scrollAnchorCoordinator: ResearchReportScrollAnchorCoordinator,
        pageBoundary: @escaping (Int) -> Void,
        canPageBoundary: @escaping (Int) -> Bool
    ) {
        self.title = title
        self.error = error
        self.isLoading = isLoading
        self.assets = assets
        self.reportRef = reportRef
        self.scrollRequest = scrollRequest
        _scrollAnchorCoordinator = ObservedObject(
            wrappedValue: scrollAnchorCoordinator
        )
        self.pageBoundary = pageBoundary
        self.canPageBoundary = canPageBoundary
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
                // Only one chapter is mounted. Keep an eager stack so the
                // AppKit-backed content settles before scroll restoration.
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
                        }
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
                .background(ResearchReportScrollViewResolver(
                    coordinator: scrollAnchorCoordinator,
                    pageBoundary: pageBoundary,
                    canPageBoundary: canPageBoundary
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
            .overlay { pageTurnOverlay }
            .task(id: scrollExecutionKey) {
                await scrollIfNeeded(proxy)
            }
            .onChange(of: materializedChapterOrder) { _ in
                chapterDisclosureMode = .defaultExpanded
                chapterDisclosureRevision &+= 1
            }
            .onDisappear {
                highlightTask?.cancel()
                highlightTask = nil
            }
        }
    }

    @ViewBuilder
    private var pageTurnOverlay: some View {
        if let hint = scrollAnchorCoordinator.pageTurnHint {
            VStack {
                if hint.direction < 0 { pageTurnIndicator(hint) }
                Spacer(minLength: 0)
                if hint.direction > 0 { pageTurnIndicator(hint) }
            }
            .padding(.vertical, 12)
            .allowsHitTesting(false)
        }
    }

    private func pageTurnIndicator(
        _ hint: ResearchReportPageTurnHint
    ) -> some View {
        Label(
            L10n.text(hint.isArmed
                ? (hint.direction < 0
                    ? "松开切换到上一章节" : "松开切换到下一章节")
                : (hint.direction < 0
                    ? "继续下拉以切换到上一章节" : "继续上拉以切换到下一章节")),
            systemImage: hint.direction < 0 ? "arrow.up" : "arrow.down"
        )
        .font(.callout.weight(.medium))
        .foregroundStyle(hint.isArmed ? Color.accentColor : .secondary)
        .opacity(0.45 + 0.55 * hint.progress)
    }
}
