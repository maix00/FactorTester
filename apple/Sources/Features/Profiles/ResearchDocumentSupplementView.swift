import SwiftUI

struct ResearchDocumentSupplementView: View {
    let artifact: ResearchArtifactModel

    @StateObject private var observer: ResearchDocumentFileObserver
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var bindings: [ResearchDocumentBinding] = []
    @State private var error = ""

    init(artifact: ResearchArtifactModel) {
        self.artifact = artifact
        _observer = StateObject(wrappedValue: ResearchDocumentFileObserver(
            localRef: artifact.localRef
        ))
    }

    var body: some View {
        Group {
            if !components.isEmpty {
                Divider().padding(.top, 12)
                VStack(alignment: .leading, spacing: 12) {
                    Text(L10n.text("结构化研究补充"))
                        .font(.title2.weight(.semibold))
                    ForEach(rootComponents) { component in
                        ResearchDocumentComponentView(
                            component: component,
                            children: childrenByParent[component.id] ?? [],
                            childrenByParent: childrenByParent,
                            assets: assets,
                            bindings: bindings,
                            reportRef: artifact.localRef
                        )
                    }
                }
                .padding(.top, 24)
            } else if !error.isEmpty {
                Label(error, systemImage: "doc.badge.exclamationmark")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.top, 18)
            }
        }
        .task(id: "\(artifact.localRef)|\(observer.revision)") {
            await load()
        }
        .onAppear { observer.start() }
        .onDisappear { observer.stop() }
    }

    private var rootComponents: [ResearchDocumentComponent] {
        let roots = components.filter { $0.parentID == nil }
        let chapters = roots.filter { $0.kind == "chapter" }
        return chapters.isEmpty ? roots : chapters
    }

    private var childrenByParent: [String: [ResearchDocumentComponent]] {
        Dictionary(grouping: components.compactMap { component in
            component.parentID.map { ($0, component) }
        }, by: \.0).mapValues { $0.map(\.1) }
    }

    private func load() async {
        do {
            let payload = try await ResearchDocumentSource.load(
                localRef: artifact.localRef
            )
            components = payload.components
            assets = payload.assets
            bindings = payload.bindings
            error = ""
        } catch {
            components = []
            assets = []
            bindings = []
            self.error = L10n.text("本地结构化研究补充无法读取")
        }
    }
}
