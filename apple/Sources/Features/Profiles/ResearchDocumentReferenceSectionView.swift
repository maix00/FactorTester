import SwiftUI

struct ResearchDocumentReferenceSectionView: View {
    let section: ResearchDocumentReferenceSection

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
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
