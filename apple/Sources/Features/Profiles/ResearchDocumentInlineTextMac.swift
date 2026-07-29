#if os(macOS)
import AppKit
import SwiftUI

struct ResearchDocumentInlineTextMac: View {
    let text: String
    let referenceScope: ResearchDocumentReferenceScope
    let openReference: (ResearchDocumentTypedLink) -> Void

    @State private var measuredHeight: CGFloat = 20

    var body: some View {
        ResearchDocumentInlineTextRepresentable(
            text: text,
            referenceScope: referenceScope,
            measuredHeight: $measuredHeight,
            openReference: openReference
        )
        .frame(maxWidth: .infinity, minHeight: measuredHeight, maxHeight: measuredHeight)
    }
}

private struct ResearchDocumentInlineTextRepresentable: NSViewRepresentable {
    let text: String
    let referenceScope: ResearchDocumentReferenceScope
    @Binding var measuredHeight: CGFloat
    let openReference: (ResearchDocumentTypedLink) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(openReference: openReference)
    }

    func makeNSView(context: Context) -> ResearchInlineTextView {
        let view = ResearchInlineTextView()
        view.delegate = context.coordinator
        view.onHeightChange = updateHeight
        return view
    }

    func updateNSView(
        _ view: ResearchInlineTextView, context: Context
    ) {
        context.coordinator.openReference = openReference
        view.onHeightChange = updateHeight
        let rendered = ResearchInlineAttributedString.make(
            text,
            scope: referenceScope
        )
        if !view.textStorage!.isEqual(to: rendered) {
            view.textStorage?.setAttributedString(rendered)
            view.invalidateIntrinsicContentSize()
            view.measureHeight()
        }
    }

    private func updateHeight(_ height: CGFloat) {
        guard abs(measuredHeight - height) > 0.5 else { return }
        DispatchQueue.main.async { measuredHeight = height }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var openReference: (ResearchDocumentTypedLink) -> Void

        init(openReference: @escaping (ResearchDocumentTypedLink) -> Void) {
            self.openReference = openReference
        }

        func textView(
            _ textView: NSTextView,
            clickedOnLink link: Any,
            at charIndex: Int
        ) -> Bool {
            guard let url = link as? URL,
                  var reference = ResearchDocumentTypedLinkParser.reference(
                    from: url
                  ) else { return false }
            if let label = textView.textStorage?.attribute(
                ResearchDocumentReferenceTextAttribute.label,
                at: charIndex,
                effectiveRange: nil
            ) as? String, !label.isEmpty {
                reference = .init(
                    kind: reference.kind,
                    targetRef: reference.targetRef,
                    label: label
                )
            }
            openReference(reference)
            return true
        }
    }
}

#endif
