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

    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        guard event.clickCount == 1, activateLink(at: point) else {
            super.mouseDown(with: event)
            return
        }
    }

    @discardableResult
    func activateLink(at point: NSPoint) -> Bool {
        guard let layoutManager,
              let textContainer,
              let textStorage,
              textStorage.length > 0 else {
            return false
        }
        let containerPoint = NSPoint(
            x: point.x - textContainerOrigin.x,
            y: point.y - textContainerOrigin.y
        )
        var hit: (link: Any, characterIndex: Int)?
        textStorage.enumerateAttribute(
            .link,
            in: NSRange(location: 0, length: textStorage.length)
        ) { link, characterRange, stop in
            guard let link else { return }
            let glyphRange = layoutManager.glyphRange(
                forCharacterRange: characterRange,
                actualCharacterRange: nil
            )
            layoutManager.enumerateLineFragments(
                forGlyphRange: glyphRange
            ) { _, _, _, lineGlyphRange, lineStop in
                let visibleRange = NSIntersectionRange(
                    glyphRange,
                    lineGlyphRange
                )
                guard visibleRange.length > 0 else { return }
                let rect = layoutManager.boundingRect(
                    forGlyphRange: visibleRange,
                    in: textContainer
                )
                guard rect.insetBy(dx: -1, dy: -2).contains(
                    containerPoint
                ) else { return }
                hit = (link, characterRange.location)
                lineStop.pointee = true
                stop.pointee = true
            }
        }
        guard let hit,
              delegate?.textView?(
                self,
                clickedOnLink: hit.link,
                at: hit.characterIndex
              ) == true else {
            return false
        }
        return true
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
    let fontName: String
    let fontSize: CGFloat
    let mathImageKeys: [String]

    init(
        text: String,
        scope: ResearchDocumentReferenceScope,
        font: NSFont = NSFont.preferredFont(forTextStyle: .body),
        mathImageKeys: [String] = []
    ) {
        self.text = text
        componentID = scope.componentID
        fontName = font.fontName
        fontSize = font.pointSize
        self.mathImageKeys = mathImageKeys
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
