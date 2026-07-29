#if os(macOS)
import AppKit

final class ResearchInlineTextView: NSTextView {
    var onHeightChange: ((CGFloat) -> Void)?
    private let renderGate = ResearchInlineRenderGate()
    private var lastMeasuredWidth: CGFloat = 0

    init() {
        let storage = NSTextStorage()
        let layout = ResearchInlineCodeLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(
                width: 0,
                height: CGFloat.greatestFiniteMagnitude
            )
        )
        layout.addTextContainer(container)
        storage.addLayoutManager(layout)
        super.init(frame: .zero, textContainer: container)
        isEditable = false
        isSelectable = true
        drawsBackground = false
        isRichText = true
        textContainerInset = .zero
        textContainer?.lineFragmentPadding = 0
        textContainer?.widthTracksTextView = false
        isHorizontallyResizable = false
        isVerticallyResizable = true
        linkTextAttributes = [
            .foregroundColor: NSColor.controlAccentColor,
            .underlineStyle: 0,
        ]
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        guard newSize.width > 0,
              abs(lastMeasuredWidth - newSize.width) > 0.5 else {
            return
        }
        lastMeasuredWidth = newSize.width
        textContainer?.containerSize = NSSize(
            width: newSize.width,
            height: .greatestFiniteMagnitude
        )
        measureHeight()
    }

    func measureHeight() {
        guard let layoutManager,
              let textContainer,
              textContainer.containerSize.width > 0 else {
            return
        }
        layoutManager.ensureLayout(for: textContainer)
        let height = max(
            20,
            ceil(layoutManager.usedRect(for: textContainer).height) + 2
        )
        onHeightChange?(height)
    }

    func shouldRender(_ identity: ResearchInlineRenderIdentity) -> Bool {
        renderGate.admit(identity)
    }
}

struct ResearchInlineRenderIdentity: Equatable {
    let text: String
    let componentID: String
    let bindingKeys: [String]

    init(text: String, scope: ResearchDocumentReferenceScope) {
        self.text = text
        componentID = scope.componentID
        bindingKeys = scope.bindings.map {
            [$0.id, $0.componentID, $0.kind, $0.targetRef, $0.label]
                .joined(separator: "\u{1f}")
        }.sorted()
    }
}

final class ResearchInlineRenderGate {
    private var current: ResearchInlineRenderIdentity?

    func admit(_ identity: ResearchInlineRenderIdentity) -> Bool {
        guard current != identity else { return false }
        current = identity
        return true
    }
}
#endif
