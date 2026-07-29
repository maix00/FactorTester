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
    let visibleChapter: (String) -> Void

    private let chapterOrder: [String]
    private let rootComponentsByID: [String: ResearchDocumentComponent]
    private let childrenByParent: [String: [ResearchDocumentComponent]]
    private let bindingsByComponent: [String: [ResearchDocumentBinding]]
    @State private var lastScrollToken = -1
    @State private var highlightedComponentID = ""
    @State private var chapterHeights: [String: CGFloat] = [:]
    @State private var chapterPositions: [String: CGFloat] = [:]
    @State private var viewportHeight: CGFloat = 0
    @State private var highlightTask: Task<Void, Never>?

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
                LazyVStack(alignment: .leading, spacing: 18) {
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
                        ForEach(chapterOrder, id: \.self) { componentID in
                            chapterSlot(componentID)
                                .id(componentID)
                                .background(ChapterPositionReporter(
                                    id: componentID
                                ))
                        }
                    }
                }
                .onPreferenceChange(ChapterPositionPreference.self) { positions in
                    chapterPositions = positions
                    updateVisibleChapter(positions)
                }
                .onPreferenceChange(ChapterHeightPreference.self) { heights in
                    var updated = chapterHeights
                    for (componentID, height) in heights where height > 0 {
                        guard abs(
                            (updated[componentID] ?? 0) - height
                        ) > 1 else { continue }
                        updated[componentID] = height
                    }
                    if updated != chapterHeights {
                        chapterHeights = updated
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
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

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.largeTitle.weight(.bold))
            Text(L10n.format("由 %@ 负责 · 当前阶段：%@", profileName,
                             ResearchDisplayText.node(currentNode)))
                .font(.callout).foregroundStyle(.secondary)
            Text(L10n.text("研究节点进入后自动建立章节，正文和证据可在本地报告中继续补充。"))
                .font(.subheadline).foregroundStyle(.secondary)
        }
    }

    private var rootComponentIDs: [String] { rootComponents.map(\.id) }

    private var scrollExecutionKey: ResearchReportScrollExecutionKey {
        let request = scrollRequest
        return ResearchReportScrollExecutionKey(
            token: request?.token ?? -1,
            targetIsLoaded: request.map {
                rootComponentsByID[$0.componentID] != nil
            } ?? false,
            isCompleted: request.map {
                lastScrollToken == $0.token
            } ?? true
        )
    }

    @ViewBuilder
    private func chapterSlot(_ componentID: String) -> some View {
        if let component = rootComponentsByID[componentID] {
            ResearchDocumentComponentView(
                component: component,
                children: childrenByParent[component.id] ?? [],
                childrenByParent: childrenByParent,
                componentBindings: bindingsByComponent[component.id] ?? [],
                bindingsByComponent: bindingsByComponent,
                assets: assets,
                reportRef: reportRef
            )
            .background(ChapterHeightReporter(id: componentID))
            .accessibilityIdentifier(
                "research.report.chapter.\(componentID)"
            )
            .background {
                RoundedRectangle(
                    cornerRadius: 10,
                    style: .continuous
                )
                .fill(Color.primary.opacity(
                    highlightedComponentID == component.id ? 0.08 : 0
                ))
                .padding(-10)
            }
            .transition(.opacity)
        } else {
            ResearchReportChapterPlaceholder()
                .frame(height: chapterHeights[componentID] ?? 280)
                .accessibilityIdentifier(
                    "research.report.chapter-placeholder.\(componentID)"
                )
        }
    }

    private var rootComponents: [ResearchDocumentComponent] {
        chapterOrder.compactMap { rootComponentsByID[$0] }
    }

    @MainActor
    private func scrollIfNeeded(_ proxy: ScrollViewProxy) async {
        guard let request = scrollRequest,
              lastScrollToken != request.token,
              rootComponentsByID[request.componentID] != nil
        else { return }

        // The report window and the scroll request often arrive in the same
        // SwiftUI update. Yield until the newly loaded target has entered the
        // ScrollViewReader hierarchy before asking it to position the chapter.
        await Task.yield()
        guard !Task.isCancelled,
              lastScrollToken != request.token else { return }
        performScroll(request, proxy: proxy)

        // AppKit can accept the first request against the old lazy-stack
        // geometry and then move the target again as the loaded chapter
        // replaces its placeholder. Keep retrying against the same token until
        // the geometry observer confirms that the target reached the reading
        // anchor. A new navigation token cancels this task automatically.
        let initialDelay = request.behavior == .smooth ? 260 : 80
        for attempt in 0..<8 {
            try? await Task.sleep(
                for: .milliseconds(initialDelay + (attempt * 55))
            )
            guard !Task.isCancelled,
                  lastScrollToken != request.token else { return }
            proxy.scrollTo(request.componentID, anchor: .top)
        }
    }

    private func performScroll(
        _ request: ResearchReportScrollRequest,
        proxy: ScrollViewProxy
    ) {
        if request.behavior == .smooth {
            withAnimation(.easeInOut(duration: 0.22)) {
                proxy.scrollTo(request.componentID, anchor: .top)
            }
        } else {
            proxy.scrollTo(request.componentID, anchor: .top)
        }
    }

    private func updateVisibleChapter(_ positions: [String: CGFloat]) {
        if let request = scrollRequest,
           lastScrollToken != request.token {
            guard ResearchReportChapterViewport.completedScroll(
                to: request.componentID,
                positions: positions,
                loadedIDs: rootComponentIDs,
                isTrailingTarget: chapterOrder.last == request.componentID,
                viewportHeight: viewportHeight
            ) else {
                return
            }
            lastScrollToken = request.token
            flash(request.componentID)
            visibleChapter(request.componentID)
            return
        }

        guard let active = ResearchReportChapterViewport.activeID(
            positions: positions,
            orderedIDs: chapterOrder
        ) else { return }
        visibleChapter(active)
    }

    private func flash(_ componentID: String) {
        highlightTask?.cancel()
        highlightedComponentID = componentID
        highlightTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1_400))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.25)) {
                highlightedComponentID = ""
            }
        }
    }
}

private struct ChapterPositionPreference: PreferenceKey {
    static var defaultValue: [String: CGFloat] = [:]

    static func reduce(value: inout [String: CGFloat], nextValue: () -> [String: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

private struct ChapterPositionReporter: View {
    let id: String

    var body: some View {
        GeometryReader { proxy in
            Color.clear.preference(
                key: ChapterPositionPreference.self,
                value: [id: proxy.frame(in: .named("research.report.page")).minY]
            )
        }
    }
}

private struct ResearchReportViewportHeightPreference: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(
        value: inout CGFloat,
        nextValue: () -> CGFloat
    ) {
        value = max(value, nextValue())
    }
}

private struct ResearchReportViewportHeightReporter: View {
    var body: some View {
        GeometryReader { proxy in
            Color.clear.preference(
                key: ResearchReportViewportHeightPreference.self,
                value: proxy.size.height
            )
        }
    }
}

private struct ChapterHeightPreference: PreferenceKey {
    static var defaultValue: [String: CGFloat] = [:]

    static func reduce(
        value: inout [String: CGFloat],
        nextValue: () -> [String: CGFloat]
    ) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

private struct ChapterHeightReporter: View {
    let id: String

    var body: some View {
        GeometryReader { proxy in
            Color.clear.preference(
                key: ChapterHeightPreference.self,
                value: [id: proxy.size.height]
            )
        }
    }
}

private struct ResearchReportChapterPlaceholder: View {
    var body: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text(L10n.text("正在加载研究节点…"))
                .font(.callout)
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
