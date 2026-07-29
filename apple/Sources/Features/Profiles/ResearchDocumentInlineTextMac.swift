#if os(macOS)
import AppKit
import SwiftUI

struct ResearchDocumentInlineTextMac: View {
    let text: String
    let openReference: (ResearchDocumentTypedLink) -> Void

    @State private var measuredHeight: CGFloat = 20

    var body: some View {
        ResearchDocumentInlineTextRepresentable(
            text: text,
            measuredHeight: $measuredHeight,
            openReference: openReference
        )
        .frame(maxWidth: .infinity, minHeight: measuredHeight, maxHeight: measuredHeight)
    }
}

private struct ResearchDocumentInlineTextRepresentable: NSViewRepresentable {
    let text: String
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
        let rendered = ResearchInlineAttributedString.make(text)
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
                  let reference = ResearchDocumentTypedLinkParser.reference(
                    from: url
                  ) else { return false }
            openReference(reference)
            return true
        }
    }
}

private final class ResearchInlineTextView: NSTextView {
    var onHeightChange: ((CGFloat) -> Void)?
    private var lastMeasuredWidth: CGFloat = 0

    init() {
        let storage = NSTextStorage()
        let layout = ResearchInlineCodeLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(
                width: 0, height: CGFloat.greatestFiniteMagnitude
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
              abs(lastMeasuredWidth - newSize.width) > 0.5 else { return }
        lastMeasuredWidth = newSize.width
        textContainer?.containerSize = NSSize(
            width: newSize.width, height: .greatestFiniteMagnitude
        )
        measureHeight()
    }

    func measureHeight() {
        guard let layoutManager, let textContainer,
              textContainer.containerSize.width > 0 else { return }
        layoutManager.ensureLayout(for: textContainer)
        let height = max(
            20, ceil(layoutManager.usedRect(for: textContainer).height) + 2
        )
        onHeightChange?(height)
    }
}

final class ResearchInlineCodeLayoutManager: NSLayoutManager {
    static let attribute = NSAttributedString.Key(
        "com.gtht.factortester.inline-code"
    )
    static let horizontalBackgroundOutset: CGFloat = 1
    static let verticalBackgroundOutset: CGFloat = 1
    static let cornerRadius: CGFloat = 5

    override func drawBackground(
        forGlyphRange glyphsToShow: NSRange, at origin: NSPoint
    ) {
        super.drawBackground(forGlyphRange: glyphsToShow, at: origin)
        guard let textStorage, let container = textContainers.first else { return }
        let characters = characterRange(
            forGlyphRange: glyphsToShow, actualGlyphRange: nil
        )
        textStorage.enumerateAttribute(
            Self.attribute, in: characters
        ) { value, characterRange, _ in
            guard value != nil else { return }
            let glyphRange = self.glyphRange(
                forCharacterRange: characterRange, actualCharacterRange: nil
            )
            self.enumerateEnclosingRects(
                forGlyphRange: glyphRange,
                withinSelectedGlyphRange: NSRange(location: NSNotFound, length: 0),
                in: container
            ) { rect, _ in
                let background = rect
                    .offsetBy(dx: origin.x, dy: origin.y)
                    .insetBy(
                        dx: -Self.horizontalBackgroundOutset,
                        dy: -Self.verticalBackgroundOutset
                    )
                NSColor.labelColor.withAlphaComponent(0.10).setFill()
                NSBezierPath(
                    roundedRect: background,
                    xRadius: Self.cornerRadius,
                    yRadius: Self.cornerRadius
                ).fill()
            }
        }
    }
}

enum ResearchInlineAttributedString {
    /// A four-per-em space gives inline code visible breathing room without
    /// creating the oversized gap of a normal word space.
    static let horizontalPadding = "\u{2005}"

    static func make(_ source: String) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for segment in ResearchDocumentTypedLinkParser.segments(in: source) {
            switch segment {
            case let .text(value):
                result.append(markdown(value))
            case let .reference(reference):
                result.append(referenceText(reference))
            }
        }
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = ResearchDocumentTextMetrics.lineSpacing
        paragraph.lineBreakMode = .byWordWrapping
        result.addAttribute(
            .paragraphStyle, value: paragraph,
            range: NSRange(location: 0, length: result.length)
        )
        return result
    }

    private static func markdown(_ source: String) -> NSAttributedString {
        let value = ResearchDocumentInlineTextStyle.markdown(source)
        var codeRanges: [NSRange] = []
        let characters = value.characters
        for run in value.runs {
            let start = characters.distance(
                from: characters.startIndex, to: run.range.lowerBound
            )
            let length = characters.distance(
                from: run.range.lowerBound, to: run.range.upperBound
            )
            if run.inlinePresentationIntent?.contains(.code) == true {
                codeRanges.append(NSRange(location: start, length: length))
            }
        }
        let rendered = NSMutableAttributedString(
            attributedString: NSAttributedString(value)
        )
        rendered.addAttribute(
            .font, value: NSFont.preferredFont(forTextStyle: .body),
            range: NSRange(location: 0, length: rendered.length)
        )
        for range in codeRanges.reversed() {
            let attributes: [NSAttributedString.Key: Any] = [
                .font: NSFont.monospacedSystemFont(
                    ofSize: NSFont.preferredFont(forTextStyle: .body).pointSize,
                    weight: .regular
                ),
                ResearchInlineCodeLayoutManager.attribute: true,
            ]
            rendered.removeAttribute(.backgroundColor, range: range)
            rendered.addAttributes(attributes, range: range)
            rendered.insert(
                NSAttributedString(
                    string: horizontalPadding, attributes: attributes
                ),
                at: NSMaxRange(range)
            )
            rendered.insert(
                NSAttributedString(
                    string: horizontalPadding, attributes: attributes
                ),
                at: range.location
            )
        }
        return rendered
    }

    private static func referenceText(
        _ reference: ResearchDocumentTypedLink
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        if let image = NSImage(systemSymbolName:
            ResearchDocumentTypedLinkPresentation.symbol(for: reference.kind),
            accessibilityDescription: nil
        ) {
            let attachment = NSTextAttachment()
            attachment.image = image.withSymbolConfiguration(
                .init(pointSize: 12, weight: .regular)
            )
            attachment.bounds = NSRect(x: 0, y: -2, width: 14, height: 14)
            let icon = NSMutableAttributedString(attachment: attachment)
            icon.addAttribute(
                .link, value: reference.url as Any,
                range: NSRange(location: 0, length: icon.length)
            )
            result.append(icon)
        }
        let label = NSMutableAttributedString(
            string: " \(reference.label)",
            attributes: [
                .font: NSFont.preferredFont(forTextStyle: .body),
                .foregroundColor: NSColor.controlAccentColor,
                .link: reference.url as Any,
            ]
        )
        result.append(label)
        return result
    }
}
#endif
