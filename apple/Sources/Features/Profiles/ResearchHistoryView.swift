import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchHistoryView: View {
    let profile: LocalProfileModel
    @State private var selectedRecord: String?
    @State private var selectedStep: String?

    var body: some View {
        GroupBox("Research History / Reports") {
            if profile.researchRecords.isEmpty {
                Text("No indexed research records")
                    .foregroundStyle(.secondary)
                    .padding(8)
            } else {
                HSplitView {
                    List(profile.researchRecords, selection: $selectedRecord) {
                        record in
                        VStack(alignment: .leading) {
                            Text(record.title)
                            Text("\(record.status) · \(record.agentID)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .tag(record.id)
                    }
                    .frame(minWidth: 180)
                    if let record = selected {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 10) {
                                Text(record.scope)
                                    .font(.caption)
                                    .textSelection(.enabled)
                                Picker("Timeline / steps", selection: $selectedStep) {
                                    Text("Select a step").tag(Optional<String>.none)
                                    ForEach(record.timeline) { link in
                                        Text("\(link.kind) · \(link.targetRef)")
                                            .tag(Optional(link.id))
                                    }
                                }
                                ForEach(record.artifacts) { artifact in
                                    HStack {
                                        Label(
                                            artifact.format,
                                            systemImage: artifact.format == "pdf"
                                                ? "doc.richtext" : "doc.text"
                                        )
                                        Text(artifact.status)
                                        Spacer()
                                        Button("Open") {
                                            open(
                                                artifact,
                                                step: selectedStep
                                            )
                                        }
                                        .disabled(artifact.status != "ready")
                                    }
                                }
                            }
                            .padding(8)
                        }
                    }
                }
                .frame(minHeight: 180)
            }
        }
    }

    private var selected: ResearchRecordModel? {
        profile.researchRecords.first { $0.id == selectedRecord }
    }

    private func open(
        _ artifact: ResearchArtifactModel,
        step: String?
    ) {
        guard var components = URLComponents(string: artifact.localRef) else {
            return
        }
        if let step,
           let link = artifact.sectionRefs.first(where: { $0.id == step }) {
            components.fragment = link.sectionRef
        }
        if let url = components.url {
            #if os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }
}
