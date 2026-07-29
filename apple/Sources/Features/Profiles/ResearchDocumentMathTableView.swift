import SwiftUI

/// Formula-bearing tables share one local KaTeX document instead of creating
/// a WebView for every formula cell. Ordinary tables stay native and lazy.
struct ResearchDocumentMathTableView: View {
    let columns: [String]
    let rows: [[String]]
    let maximumHeight: CGFloat

    @Environment(\.researchDocumentReferenceAction) private var openReference
    @State private var contentHeight: CGFloat = 160

    var body: some View {
        ResearchMathWebView(
            document: MathTableDocument.make(columns: columns, rows: rows),
            openReference: openReference,
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 96), maximumHeight))
        .background(
            Color.secondary.opacity(0.025),
            in: RoundedRectangle(cornerRadius: 7)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .accessibilityLabel(L10n.text("含公式的研究表格"))
    }
}
