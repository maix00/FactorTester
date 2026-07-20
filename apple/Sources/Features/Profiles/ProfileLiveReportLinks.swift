import SwiftUI

struct ProfileLiveReportLinks: View {
    let profile: LocalProfileModel
    let reportLookupRef: String?
    let timeline: [ResearchTransitionStep]
    let highlightedRefs: Set<String>
    let select: (Set<String>) -> Void
    @State private var sections: [ResearchReportSection] = []

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                Text("REPORT.index 关联")
                    .font(.title2.weight(.semibold))
                Text("点击章节可反向高亮产生该证据的研究步骤。")
                    .foregroundStyle(.secondary)
                if sections.isEmpty {
                    Label(
                        "没有与当前研究引用匹配的本地报告章节",
                        systemImage: "doc.text.magnifyingglass"
                    )
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 30)
                }
                ForEach(sections) { section in
                    Button {
                        select(Set(section.links.map(\.targetRef)))
                    } label: {
                        sectionCard(section)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(20)
        }
        .task(id: reportLookupRef) { sections = await loadSections() }
    }

    private func sectionCard(
        _ section: ResearchReportSection
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(section.title).font(.headline)
            Text(section.summary)
                .foregroundStyle(.secondary)
                .lineLimit(5)
            if !section.links.isEmpty {
                Text(section.links.map(\.targetRef).joined(separator: " · "))
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            refs(section).isDisjoint(with: highlightedRefs)
                ? Color.clear : Color.accentColor.opacity(0.09),
            in: RoundedRectangle(cornerRadius: 10)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.separator, lineWidth: 0.5)
        }
    }

    private func refs(_ section: ResearchReportSection) -> Set<String> {
        Set(section.links.map(\.targetRef))
    }

    private func loadSections() async -> [ResearchReportSection] {
        let accepted = Set(
            timeline.flatMap { Array($0.allRefs) }
                + [reportLookupRef].compactMap { $0 }
        )
        let records = profile.researchRecords.filter { record in
            accepted.contains(record.id)
                || record.timeline.contains {
                    accepted.contains($0.targetRef)
                }
                || record.artifacts.contains {
                    accepted.contains($0.id)
                }
        }
        return await withTaskGroup(
            of: [ResearchReportSection].self
        ) { group in
            for artifact in records.flatMap(\.artifacts).prefix(20) {
                group.addTask {
                    await ResearchReportIndex.load(artifact: artifact)
                }
            }
            var result: [ResearchReportSection] = []
            for await values in group {
                result.append(contentsOf: values)
            }
            return Array(result.prefix(100))
        }
    }
}
