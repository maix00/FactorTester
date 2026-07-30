#if os(macOS)
import AppKit
import XCTest
@testable import FTClient

@MainActor
final class ResearchInlineTextViewLinkTests: XCTestCase {
    func testMouseHitRoutesWebReferenceThroughTextViewDelegate() throws {
        let view = ResearchInlineTextView()
        let delegate = LinkDelegate()
        view.delegate = delegate
        view.setFrameSize(NSSize(width: 420, height: 40))
        view.textStorage?.setAttributedString(
            ResearchInlineAttributedString.make(
                "参见 [论文](https://example.com/research.pdf)"
            )
        )
        view.measureHeight()

        let labelRange = (view.string as NSString).range(of: "论文")
        XCTAssertNotEqual(labelRange.location, NSNotFound)
        let storedLink = view.textStorage?.attribute(
            .link,
            at: labelRange.location,
            effectiveRange: nil
        )
        let storedURL = try XCTUnwrap(storedLink as? URL)
        XCTAssertEqual(storedURL.scheme, "factortester")
        XCTAssertNotNil(ResearchDocumentTypedLinkParser.reference(from: storedURL))
        let point = try linkPoint(label: "论文", in: view)
        XCTAssertTrue(view.activateLink(at: point))
        XCTAssertEqual(delegate.reference?.kind, "url")
        XCTAssertEqual(
            delegate.reference?.targetRef,
            "https://example.com/research.pdf"
        )
    }

    func testMouseHitRoutesRootReportFile() throws {
        let view = ResearchInlineTextView()
        let delegate = LinkDelegate()
        view.delegate = delegate
        view.setFrameSize(NSSize(width: 420, height: 40))
        view.textStorage?.setAttributedString(
            ResearchInlineAttributedString.make(
                "参见 [上下文](CONTEXT.md)"
            )
        )
        view.measureHeight()

        let point = try linkPoint(label: "上下文", in: view)
        XCTAssertTrue(view.activateLink(at: point))
        XCTAssertEqual(delegate.reference?.kind, "file")
        XCTAssertEqual(delegate.reference?.targetRef, "CONTEXT.md")
    }

    private func linkPoint(
        label: String,
        in view: ResearchInlineTextView
    ) throws -> NSPoint {
        let storage = try XCTUnwrap(view.textStorage)
        let layout = try XCTUnwrap(view.layoutManager)
        let container = try XCTUnwrap(view.textContainer)
        layout.ensureLayout(for: container)
        let characters = (storage.string as NSString).range(of: label)
        XCTAssertNotEqual(characters.location, NSNotFound)
        let glyphs = layout.glyphRange(
            forCharacterRange: characters,
            actualCharacterRange: nil
        )
        let rect = layout.boundingRect(
            forGlyphRange: NSRange(location: glyphs.location, length: 1),
            in: container
        )
        return NSPoint(
            x: rect.midX + view.textContainerOrigin.x,
            y: rect.midY + view.textContainerOrigin.y
        )
    }
}

private final class LinkDelegate: NSObject, NSTextViewDelegate {
    var reference: ResearchDocumentTypedLink?

    func textView(
        _ textView: NSTextView,
        clickedOnLink link: Any,
        at charIndex: Int
    ) -> Bool {
        guard let url = link as? URL else { return false }
        reference = ResearchDocumentTypedLinkParser.reference(from: url)
        return reference != nil
    }
}
#endif
