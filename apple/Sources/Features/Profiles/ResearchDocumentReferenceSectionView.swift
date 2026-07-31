import SwiftUI

struct ResearchDocumentReferenceSectionView: View {
    let section: ResearchDocumentReferenceSection
    @Environment(\.researchDocumentReferenceAction) private var openReference

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(section.title)
                .font(.subheadline.weight(.semibold))
            Grid(
                alignment: .leading,
                horizontalSpacing: 18,
                verticalSpacing: 9
            ) {
                ForEach(section.fields) { field in
                    GridRow {
                        Text(field.name)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(field.value)
                            .font(.callout)
                            .textSelection(.enabled)
                            .frame(
                                maxWidth: .infinity,
                                alignment: .leading
                            )
                    }
                }
            }
            ForEach(section.links) { link in
                Button {
                    openReference(link.reference)
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: ResearchDocumentTypedLinkPresentation.symbol(
                            for: link.reference.kind
                        ))
                            .foregroundStyle(
                                ResearchDocumentTypedLinkPresentation.color(
                                    for: link.reference.kind
                                )
                            )
                        VStack(alignment: .leading, spacing: 1) {
                            Text(link.reference.label)
                                .foregroundStyle(
                                    ResearchDocumentTypedLinkPresentation.color(
                                        for: link.reference.kind
                                    )
                                )
                            Text(L10n.text(link.relation))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
