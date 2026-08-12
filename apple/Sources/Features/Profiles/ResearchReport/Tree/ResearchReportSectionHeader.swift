import SwiftUI

struct ResearchReportSectionHeader: View {
    let component: ResearchDocumentComponent
    let bindings: [ResearchDocumentBinding]
    let specialKind: ResearchReportSectionSpecialKind?
    let isExpanded: Bool
    let toggle: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Button(action: toggle) {
                HStack(spacing: 8) {
                    bridgeMarker
                    Image(systemName:
                        ResearchReportSectionHeaderPresentation.iconName(
                            specialKind: specialKind
                        ))
                        .foregroundStyle(specialKind?.tint ?? .secondary)
                        .frame(width: 16, height: 20)
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(component.title)

            ResearchDocumentHeadingText(
                text: component.title,
                role: .section,
                componentID: component.id,
                onPlainClick: toggle
            )
            .environment(\.researchDocumentReferenceBindings, bindings)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)
            Button(action: toggle) {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.top, 3)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(component.title)
        }
        .padding(.vertical, 8)
    }

    private var bridgeMarker: some View {
        Circle()
            .fill(Color.secondary.opacity(0.42))
            .frame(width: 7, height: 7)
            .padding(.top, 15)
            .frame(width: 12)
            .zIndex(1)
    }
}

enum ResearchReportSectionHeaderPresentation {
    static func iconName(
        specialKind: ResearchReportSectionSpecialKind?
    ) -> String {
        specialKind?.icon ?? "doc.text"
    }
}
