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

    private let rootComponents: [ResearchDocumentComponent]
    private let childrenByParent: [String: [ResearchDocumentComponent]]
    private let bindingsByComponent: [String: [ResearchDocumentBinding]]
    @State private var lastScrollToken = -1
    @State private var highlightedComponentID = ""
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
        let order = Dictionary(
            uniqueKeysWithValues: chapterOrder.enumerated().map {
                ($0.element, $0.offset)
            }
        )
        self.rootComponents = components
            .filter { $0.parentID == nil }
            .sorted {
                (order[$0.id] ?? .max) < (order[$1.id] ?? .max)
            }
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
                    } else if rootComponents.isEmpty {
                        Label(
                            L10n.text("当前研究报告尚无章节"),
                            systemImage: "doc.text"
                        )
                        .foregroundStyle(.secondary)
                    } else {
                        ForEach(rootComponents) { component in
                            ResearchDocumentComponentView(
                                component: component,
                                children: childrenByParent[component.id] ?? [],
                                childrenByParent: childrenByParent,
                                componentBindings: bindingsByComponent[component.id] ?? [],
                                bindingsByComponent: bindingsByComponent,
                                assets: assets,
                                reportRef: reportRef
                            )
                            .id(component.id)
                            .background(ChapterPositionReporter(id: component.id))
                            .background {
                                RoundedRectangle(
                                    cornerRadius: 10,
                                    style: .continuous
                                )
                                .fill(Color.primary.opacity(
                                    highlightedComponentID == component.id
                                        ? 0.08 : 0
                                ))
                                .padding(-10)
                            }
                            .transition(.opacity.combined(with: .move(edge: .bottom)))
                        }
                    }
                }
                .onPreferenceChange(ChapterPositionPreference.self) { positions in
                    guard let closest = positions.min(by: {
                        abs($0.value - 96) < abs($1.value - 96)
                    })?.key else { return }
                    visibleChapter(closest)
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.horizontal, 42)
                .padding(.vertical, 34)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .coordinateSpace(name: "research.report.page")
            .onAppear { scrollIfNeeded(proxy) }
            .onChange(of: scrollRequest) { _ in scrollIfNeeded(proxy) }
            .onChange(of: rootComponentIDs) { _ in scrollIfNeeded(proxy) }
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

    private func scrollIfNeeded(_ proxy: ScrollViewProxy) {
        guard let request = scrollRequest,
              lastScrollToken != request.token,
              rootComponents.contains(where: {
                  $0.id == request.componentID
              })
        else { return }
        lastScrollToken = request.token
        DispatchQueue.main.async {
            if request.behavior == .smooth {
                withAnimation(.easeInOut(duration: 0.22)) {
                    proxy.scrollTo(request.componentID, anchor: .top)
                }
            } else {
                proxy.scrollTo(request.componentID, anchor: .top)
            }
            flash(request.componentID)
        }
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
