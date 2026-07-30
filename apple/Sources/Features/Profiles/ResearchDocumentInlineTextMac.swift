#if os(macOS)
import AppKit
import SwiftUI

struct ResearchDocumentInlineTextMac: View {
    let text: String
    let referenceScope: ResearchDocumentReferenceScope
    let font: NSFont
    let openReference: (ResearchDocumentTypedLink) -> Void

    @State private var measuredHeight: CGFloat = 20
    @Environment(\.researchDocumentSelectionCoordinator)
    private var selectionCoordinator

    init(
        text: String,
        referenceScope: ResearchDocumentReferenceScope,
        font: NSFont = NSFont.preferredFont(forTextStyle: .body),
        openReference: @escaping (ResearchDocumentTypedLink) -> Void
    ) {
        self.text = text
        self.referenceScope = referenceScope
        self.font = font
        self.openReference = openReference
    }

    var body: some View {
        ResearchDocumentInlineTextRepresentable(
            text: text,
            referenceScope: referenceScope,
            font: font,
            selectionCoordinator: selectionCoordinator,
            measuredHeight: $measuredHeight,
            openReference: openReference
        )
        .frame(maxWidth: .infinity, minHeight: measuredHeight, maxHeight: measuredHeight)
    }
}

private struct ResearchDocumentInlineTextRepresentable: NSViewRepresentable {
    let text: String
    let referenceScope: ResearchDocumentReferenceScope
    let font: NSFont
    let selectionCoordinator: ResearchDocumentSelectionCoordinator?
    @Binding var measuredHeight: CGFloat
    let openReference: (ResearchDocumentTypedLink) -> Void

    func makeCoordinator() -> ResearchDocumentInlineTextCoordinator {
        ResearchDocumentInlineTextCoordinator(openReference: openReference)
    }

    func makeNSView(context: Context) -> ResearchInlineTextView {
        let view = ResearchInlineTextView()
        view.delegate = context.coordinator
        view.onHeightChange = updateHeight
        selectionCoordinator?.register(view)
        return view
    }

    func updateNSView(
        _ view: ResearchInlineTextView, context: Context
    ) {
        context.coordinator.openReference = openReference
        view.onHeightChange = updateHeight
        if view.selectionCoordinator !== selectionCoordinator {
            view.selectionCoordinator?.unregister(view)
            selectionCoordinator?.register(view)
        }
        context.coordinator.update(
            view: view,
            text: text,
            scope: referenceScope,
            font: font
        )
    }

    private func updateHeight(_ height: CGFloat) {
        guard abs(measuredHeight - height) > 0.5 else { return }
        DispatchQueue.main.async { measuredHeight = height }
    }

    static func dismantleNSView(
        _ view: ResearchInlineTextView,
        coordinator: ResearchDocumentInlineTextCoordinator
    ) {
        view.selectionCoordinator?.unregister(view)
    }

}

#endif
