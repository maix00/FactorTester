import SwiftUI

struct ResearchReportTreePage: View {
    let title: String
    let profileName: String
    let currentNode: String
    let error: String?
    let components: [ResearchDocumentComponent]
    let assets: [ResearchDocumentAsset]
    let bindings: [ResearchDocumentBinding]
    let reportRef: String
    let scrollTarget: String
    let visibleChapter: (String) -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    header
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.secondary)
                    } else if components.isEmpty {
                        ProgressView(L10n.text("正在读取本地研究报告…"))
                    } else {
                        ForEach(rootComponents) { component in
                            ResearchDocumentComponentView(
                                component: component,
                                children: childrenByParent[component.id] ?? [],
                                childrenByParent: childrenByParent,
                                assets: assets,
                                bindings: bindings,
                                reportRef: reportRef
                            )
                            .id(component.id)
                            .background(ChapterPositionReporter(id: component.id))
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
            .onAppear { scroll(proxy) }
            .onChange(of: scrollTarget) { _ in scroll(proxy) }
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

    private var rootComponents: [ResearchDocumentComponent] {
        components.filter { $0.parentID == nil }
    }

    private var childrenByParent: [String: [ResearchDocumentComponent]] {
        Dictionary(grouping: components.compactMap { component in
            component.parentID.map { ($0, component) }
        }, by: \.0).mapValues { $0.map(\.1) }
    }

    private func scroll(_ proxy: ScrollViewProxy) {
        guard rootComponents.contains(where: { $0.id == scrollTarget }) else { return }
        DispatchQueue.main.async {
            withAnimation(.easeInOut(duration: 0.22)) {
                proxy.scrollTo(scrollTarget, anchor: .top)
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
