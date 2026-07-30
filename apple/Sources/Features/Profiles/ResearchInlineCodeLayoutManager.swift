#if os(macOS)
import AppKit

final class ResearchInlineCodeLayoutManager: NSLayoutManager {
    static let attribute = NSAttributedString.Key(
        "com.gtht.factortester.inline-code"
    )
    static let horizontalBackgroundOutset: CGFloat = 4
    static let verticalBackgroundOutset: CGFloat = 0.5
    static let cornerRadius: CGFloat = 6

    override func drawBackground(
        forGlyphRange glyphsToShow: NSRange,
        at origin: NSPoint
    ) {
        super.drawBackground(forGlyphRange: glyphsToShow, at: origin)
        guard let textStorage,
              let container = textContainers.first else {
            return
        }
        let characters = characterRange(
            forGlyphRange: glyphsToShow,
            actualGlyphRange: nil
        )
        textStorage.enumerateAttribute(
            Self.attribute,
            in: characters
        ) { value, characterRange, _ in
            guard value != nil else { return }
            for background in self.backgroundRects(
                forCharacterRange: characterRange,
                visibleGlyphRange: glyphsToShow,
                in: container,
                at: origin
            ) {
                NSColor.labelColor.withAlphaComponent(0.10).setFill()
                NSBezierPath(
                    roundedRect: background,
                    xRadius: Self.cornerRadius,
                    yRadius: Self.cornerRadius
                ).fill()
            }
        }
    }

    func backgroundRects(
        forCharacterRange characterRange: NSRange,
        visibleGlyphRange: NSRange,
        in container: NSTextContainer,
        at origin: NSPoint = .zero
    ) -> [NSRect] {
        guard let textStorage,
              characterRange.length > 0,
              characterRange.location < textStorage.length else {
            return []
        }
        let codeGlyphs = glyphRange(
            forCharacterRange: characterRange,
            actualCharacterRange: nil
        )
        let visibleCodeGlyphs = NSIntersectionRange(
            codeGlyphs,
            visibleGlyphRange
        )
        guard visibleCodeGlyphs.length > 0 else { return [] }
        let font = textStorage.attribute(
            .font,
            at: characterRange.location,
            effectiveRange: nil
        ) as? NSFont ?? NSFont.monospacedSystemFont(
            ofSize: NSFont.systemFontSize,
            weight: .regular
        )
        let glyphHeight = ceil(font.ascender - font.descender)
        var result: [NSRect] = []
        enumerateEnclosingRects(
            forGlyphRange: visibleCodeGlyphs,
            withinSelectedGlyphRange: NSRange(
                location: NSNotFound,
                length: 0
            ),
            in: container
        ) { rect, _ in
            guard rect.width > 0.5, rect.height > 0.5 else { return }
            let compactHeight = min(rect.height, glyphHeight)
            let compact = NSRect(
                x: rect.minX,
                y: rect.midY - compactHeight / 2,
                width: rect.width,
                height: compactHeight
            )
            result.append(
                compact
                    .offsetBy(dx: origin.x, dy: origin.y)
                    .insetBy(
                        dx: -Self.horizontalBackgroundOutset,
                        dy: -Self.verticalBackgroundOutset
                    )
            )
        }
        return result
    }
}
#endif
