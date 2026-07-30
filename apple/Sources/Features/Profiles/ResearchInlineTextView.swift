#if os(macOS)
import AppKit

final class ResearchInlineTextView: NSTextView {
    var onHeightChange: ((CGFloat) -> Void)?
    weak var selectionCoordinator: ResearchDocumentSelectionCoordinator?
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
        if event.clickCount == 1, activateLink(at: point) {
            selectionCoordinator?.clearSelection()
            return
        }
        guard event.clickCount == 1,
              let selectionCoordinator,
              let window else {
            selectionCoordinator?.clearSelection()
            super.mouseDown(with: event)
            return
        }
        window.makeFirstResponder(self)
        selectionCoordinator.beginSelection(
            in: self,
            characterIndex: characterIndex(at: point)
        )
        trackSelection(in: window, coordinator: selectionCoordinator)
    }

    override func copy(_ sender: Any?) {
        guard let selectionCoordinator,
              selectionCoordinator.hasCrossViewSelection else {
            super.copy(sender)
            return
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(
            selectionCoordinator.selectedPlainText,
            forType: .string
        )
    }

    func characterIndex(at point: NSPoint) -> Int {
        guard let layoutManager, let textContainer else { return 0 }
        let containerPoint = NSPoint(
            x: point.x - textContainerOrigin.x,
            y: point.y - textContainerOrigin.y
        )
        let glyphIndex = layoutManager.glyphIndex(
            for: containerPoint,
            in: textContainer
        )
        guard glyphIndex < layoutManager.numberOfGlyphs else {
            return string.utf16.count
        }
        return layoutManager.characterIndexForGlyph(at: glyphIndex)
    }

    private func trackSelection(
        in window: NSWindow,
        coordinator: ResearchDocumentSelectionCoordinator
    ) {
        let mask: NSEvent.EventTypeMask = [.leftMouseDragged, .leftMouseUp]
        while let event = window.nextEvent(matching: mask) {
            if event.type == .leftMouseUp { break }
            guard let target = coordinator.textView(at: event) else { continue }
            let point = target.convert(event.locationInWindow, from: nil)
            coordinator.extendSelection(
                to: target,
                characterIndex: target.characterIndex(at: point)
            )
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
