import SwiftUI

/// Formula-bearing tables share one local KaTeX document instead of creating
/// a WebView for every formula cell. Ordinary tables stay native and lazy.
struct ResearchDocumentMathTableView: View {
    let columns: [String]
    let rows: [[String]]
    let maximumHeight: CGFloat

    @Environment(\.researchDocumentReferenceAction) private var openReference
    @Environment(\.researchDocumentReferenceComponentID) private var componentID
    @Environment(\.researchDocumentReferenceBindings) private var bindings
    @State private var contentHeight: CGFloat = 160

    var body: some View {
        ResearchMathWebView(
            document: MathTableDocument.make(
                columns: columns,
                rows: rows,
                trustedReferenceKeys: referenceScope.webTrustedReferenceKeys
            ),
            openReference: {
                guard let trusted = referenceScope.trusted($0) else { return }
                openReference(trusted)
            },
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: max(
            ResearchDocumentTableLayout.visibleHeight(
                contentHeight,
                maximum: maximumHeight
            ),
            96
        ))
        .background(
            Color.secondary.opacity(0.025),
            in: RoundedRectangle(cornerRadius: 7)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .accessibilityLabel(L10n.text("含公式的研究表格"))
    }

    private var referenceScope: ResearchDocumentReferenceScope {
        .init(componentID: componentID, bindings: bindings)
    }
}
