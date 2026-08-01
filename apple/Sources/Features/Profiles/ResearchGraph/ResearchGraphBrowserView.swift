import SwiftUI

enum ResearchGraphSelection: Hashable {
    case node(String)
    case edge(String)
}

struct ResearchGraphBrowserView: View {
    let profiles: [LocalProfileModel]
    let isActive: Bool
    @ObservedObject var tabSession: ClientTabSession

    @StateObject private var controller: ResearchGraphBrowserController

    init(
        profiles: [LocalProfileModel],
        isActive: Bool,
        tabSession: ClientTabSession
    ) {
        self.profiles = profiles
        self.isActive = isActive
        self.tabSession = tabSession
        _controller = StateObject(
            wrappedValue: ResearchGraphBrowserController(
                endpoints: ResearchGraphEndpoint.available(from: profiles),
                initialEndpointID: tabSession.selectedResearchGraphEndpointID,
                initialVersion: tabSession.selectedResearchGraphVersion
            )
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if let error = controller.error {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }
            content
        }
        .padding(24)
        .frame(
            maxWidth: .infinity,
            maxHeight: .infinity,
            alignment: .topLeading
        )
        .task(id: loadIdentity) {
            controller.replaceEndpoints(
                ResearchGraphEndpoint.available(from: profiles)
            )
            guard isActive else { return }
            await controller.refresh()
        }
        .onChange(of: controller.selectedGraph?.id) { _ in
            reconcileSelection()
        }
        .onChange(of: controller.selectedEndpointID) { value in
            tabSession.selectedResearchGraphEndpointID = value
        }
        .onChange(of: controller.selectedVersion) { value in
            tabSession.selectedResearchGraphVersion = value
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text("Factor Research Graph")
                    .font(.largeTitle.weight(.semibold))
                if let activeVersion = controller.activeVersion {
                    Text(verbatim: L10n.format(
                        "v%lld · 当前 Active",
                        activeVersion
                    ))
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.green.opacity(0.14), in: Capsule())
                    .foregroundStyle(.green)
                }
                Spacer()
                Button {
                    Task { await controller.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help(L10n.text("刷新"))
                .disabled(controller.isLoading)
            }
            HStack(spacing: 12) {
                if controller.endpoints.count > 1 {
                    Picker(
                        "服务器",
                        selection: $controller.selectedEndpointID
                    ) {
                        ForEach(controller.endpoints) { endpoint in
                            Text(verbatim: endpoint.displayName)
                                .tag(Optional(endpoint.id))
                        }
                    }
                    .frame(maxWidth: 240)
                }
                Picker("图版本", selection: versionBinding) {
                    ForEach(controller.versions) { graph in
                        Text(verbatim: versionTitle(graph.version))
                            .tag(Optional(graph.version))
                    }
                }
                .pickerStyle(.menu)
                .frame(width: 150)
                Button {
                    if let version = controller.olderVersion {
                        controller.selectVersion(version)
                    }
                } label: {
                    Image(systemName: "chevron.left")
                }
                .buttonStyle(.borderless)
                .help(L10n.text("较旧版本"))
                .disabled(controller.olderVersion == nil)
                Button {
                    if let version = controller.newerVersion {
                        controller.selectVersion(version)
                    }
                } label: {
                    Image(systemName: "chevron.right")
                }
                .buttonStyle(.borderless)
                .help(L10n.text("较新版本"))
                .disabled(controller.newerVersion == nil)
                Text(verbatim: L10n.format(
                    "共 %lld 个版本",
                    controller.versions.count
                ))
                .font(.caption)
                .foregroundStyle(.secondary)
                if controller.selectedVersion != controller.activeVersion,
                   controller.selectedVersion != nil {
                    Label(
                        "只读查看，不会切换 Active 图",
                        systemImage: "eye"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    Button("查看 Active") {
                        if let activeVersion = controller.activeVersion {
                            controller.selectVersion(activeVersion)
                        }
                    }
                    .buttonStyle(.link)
                }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if controller.endpoints.isEmpty {
            ResearchGraphEmptyState(
                title: "没有可读取的研究图服务器",
                systemImage: "server.rack",
                description: "请先注册一个绑定服务器的研究 Profile。"
            )
        } else if controller.isLoading && controller.versions.isEmpty {
            ProgressView("正在读取研究图…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let graph = controller.selectedGraph {
            graphContent(graph)
        } else {
            ResearchGraphEmptyState(
                title: "尚无研究图版本",
                systemImage: "point.3.connected.trianglepath.dotted",
                description: nil
            )
        }
    }

    private func graphContent(_ graph: ResearchGraphVersion) -> some View {
        GeometryReader { proxy in
            HStack(spacing: 0) {
                ResearchGraphTopologyView(
                    graph: graph,
                    selection: $tabSession.selectedResearchGraphElement
                )
                .id(graph.id)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                Divider()
                ResearchGraphRequirementDetailView(
                    graph: graph,
                    selection: $tabSession.selectedResearchGraphElement
                )
                .frame(width: min(max(proxy.size.width * 0.36, 340), 480))
                .frame(maxHeight: .infinity)
            }
        }
    }

    private var versionBinding: Binding<Int?> {
        Binding(
            get: { controller.selectedVersion },
            set: { value in
                if let value { controller.selectVersion(value) }
            }
        )
    }

    private func versionTitle(_ version: Int) -> String {
        version == controller.activeVersion
            ? L10n.format("v%lld（Active）", version)
            : "v\(version)"
    }

    private var loadIdentity: String {
        let endpoints = ResearchGraphEndpoint.available(from: profiles)
            .map(\.id)
            .joined(separator: "|")
        return "\(isActive)|\(endpoints)|\(controller.selectedEndpointID ?? "")"
    }

    private func reconcileSelection() {
        guard let graph = controller.selectedGraph else {
            tabSession.selectedResearchGraphElement = nil
            return
        }
        switch tabSession.selectedResearchGraphElement {
        case .node(let nodeID) where graph.node(id: nodeID) != nil:
            return
        case .edge(let edgeID) where graph.edge(id: edgeID) != nil:
            return
        default:
            let nodeID = graph.node(id: graph.entryNode) != nil
                ? graph.entryNode : graph.nodes.first?.id
            tabSession.selectedResearchGraphElement = nodeID.map(
                ResearchGraphSelection.node
            )
        }
    }
}

struct ResearchGraphEmptyState: View {
    let title: LocalizedStringKey
    let systemImage: String
    let description: LocalizedStringKey?

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: systemImage)
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text(title).font(.headline)
            if let description {
                Text(description)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
