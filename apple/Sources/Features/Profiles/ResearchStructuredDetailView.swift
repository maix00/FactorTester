import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchStructuredDetailView: View {
    let record: ResearchRecordModel
    @State private var selectedStep = ""
    @State private var sections: [ResearchReportSection] = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(record.scope).font(.caption).textSelection(.enabled)
                Picker("Timeline / steps", selection: $selectedStep) {
                    Text("Select a step").tag("")
                    ForEach(record.timeline) { link in
                        Text("\(link.kind) · \(link.targetRef)").tag(link.id)
                    }
                }
                if selectedStep.isEmpty {
                    Text("Select a step to load its bounded report detail.")
                        .foregroundStyle(.secondary)
                } else {
                    referenceCards
                    ForEach(relatedSections) { section in sectionCard(section) }
                }
                Divider()
                ForEach(record.artifacts) { artifact in
                    HStack {
                        Label(artifact.format, systemImage: "doc.text")
                        Text(artifact.status)
                        Spacer()
                        Button("View original report") { open(artifact) }
                            .disabled(artifact.status != "ready")
                    }
                }
            }
            .padding(8)
        }
        .task(id: record.id) { sections = await loadSections() }
    }

    private var selectedLink: ResearchDeepLinkModel? {
        record.timeline.first { $0.id == selectedStep }
    }

    private var relatedSections: [ResearchReportSection] {
        guard let selectedLink else { return [] }
        return sections.filter { section in
            section.id == selectedLink.sectionRef
            || section.links.contains {
                $0.id == selectedLink.id
                || $0.targetRef == selectedLink.targetRef
            }
        }
    }

    private var referenceCards: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let link = selectedLink {
                referenceRow(kind: link.kind, value: link.targetRef)
            }
            ForEach(relatedSections.flatMap(\.links)) { link in
                referenceRow(kind: link.kind, value: link.targetRef)
            }
        }
    }

    private func loadSections() async -> [ResearchReportSection] {
        await withTaskGroup(of: [ResearchReportSection].self) { group in
            for artifact in record.artifacts {
                group.addTask {
                    await ResearchReportIndex.load(artifact: artifact)
                }
            }
            var result: [ResearchReportSection] = []
            for await values in group { result.append(contentsOf: values) }
            return result
        }
    }

    private func referenceRow(kind: String, value: String) -> some View {
        LabeledContent(kind, value: value)
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
    }

    private func sectionCard(_ section: ResearchReportSection) -> some View {
        GroupBox(section.title) {
            Text(section.summary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding(6)
        }
    }

    private func open(_ artifact: ResearchArtifactModel) {
        guard let url = URL(string: artifact.localRef) else { return }
        #if os(macOS)
        NSWorkspace.shared.open(url)
        #endif
    }
}
