#if os(macOS)
import AppKit

@MainActor
final class ResearchDocumentInlineTextCoordinator: NSObject, NSTextViewDelegate {
    var openReference: (ResearchDocumentTypedLink) -> Void
    private weak var view: ResearchInlineTextView?
    private var text = ""
    private var scope = ResearchDocumentReferenceScope(
        componentID: "",
        bindings: []
    )
    private var font = NSFont.preferredFont(forTextStyle: .body)
    private var mathImages: [String: ResearchInlineMathRendered] = [:]
    private var requestedMath: Set<String> = []

    init(openReference: @escaping (ResearchDocumentTypedLink) -> Void) {
        self.openReference = openReference
    }

    func update(
        view: ResearchInlineTextView,
        text: String,
        scope: ResearchDocumentReferenceScope,
        font: NSFont
    ) {
        self.view = view
        self.text = text
        self.scope = scope
        self.font = font
        requestMath()
        render()
    }

    private func requestMath() {
        for latex in ResearchInlineMathTokens.formulas(in: text) {
            let key = ResearchInlineMathImageRenderer.key(
                latex: latex,
                fontSize: font.pointSize
            )
            guard mathImages[key] == nil,
                  requestedMath.insert(key).inserted else { continue }
            ResearchInlineMathImageRenderer.shared.request(
                latex: latex,
                fontSize: font.pointSize
            ) { [weak self] rendered in
                guard let self else { return }
                self.requestedMath.remove(key)
                if let rendered { self.mathImages[key] = rendered }
                self.render()
            }
        }
    }

    private func render() {
        guard let view else { return }
        let identity = ResearchInlineRenderIdentity(
            text: text,
            scope: scope,
            font: font,
            mathImageKeys: mathImages.keys.sorted()
        )
        guard view.shouldRender(identity) else { return }
        let rendered = ResearchInlineAttributedString.make(
            text,
            scope: scope,
            font: font,
            mathImages: mathImages
        )
        guard !view.textStorage!.isEqual(to: rendered) else { return }
        view.textStorage?.setAttributedString(rendered)
        view.invalidateIntrinsicContentSize()
        view.measureHeight()
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
#endif
