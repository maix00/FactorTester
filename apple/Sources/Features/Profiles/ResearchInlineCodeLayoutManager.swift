#if os(macOS)
import AppKit

final class ResearchInlineCodeLayoutManager: NSLayoutManager {
    static let attribute = NSAttributedString.Key(
        "com.gtht.factortester.inline-code"
    )
    static let horizontalBackgroundOutset: CGFloat = 1
    static let verticalBackgroundOutset: CGFloat = 1
    static let cornerRadius: CGFloat = 5

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
            let glyphRange = self.glyphRange(
                forCharacterRange: characterRange,
                actualCharacterRange: nil
            )
            self.enumerateEnclosingRects(
                forGlyphRange: glyphRange,
                withinSelectedGlyphRange: NSRange(
                    location: NSNotFound,
                    length: 0
                ),
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
#endif
