#if os(macOS)
import AppKit
import XCTest
@testable import FTClient

@MainActor
final class ResearchDocumentSelectionCoordinatorTests: XCTestCase {
    func testSelectionCanSpanMultipleNativeTextViewsAndCopyInOrder() {
        let coordinator = ResearchDocumentSelectionCoordinator()
        let first = textView("第一段文字")
        let second = textView("第二段文字")
        coordinator.register(first)
        coordinator.register(second)

        coordinator.beginSelection(in: first, characterIndex: 2)
        coordinator.extendSelection(to: second, characterIndex: 3)

        XCTAssertEqual(first.selectedRange(), NSRange(location: 2, length: 3))
        XCTAssertEqual(second.selectedRange(), NSRange(location: 0, length: 3))
        XCTAssertEqual(coordinator.selectedPlainText, "段文字\n第二段")
        XCTAssertTrue(coordinator.hasCrossViewSelection)
    }

    func testClearSelectionRemovesInactiveGrayHighlightsImmediately() {
        let coordinator = ResearchDocumentSelectionCoordinator()
        let first = textView("第一段")
        let second = textView("第二段")
        coordinator.register(first)
        coordinator.register(second)
        coordinator.beginSelection(in: first, characterIndex: 1)
        coordinator.extendSelection(to: second, characterIndex: 2)

        coordinator.clearSelection()

        XCTAssertEqual(first.selectedRange().length, 0)
        XCTAssertEqual(second.selectedRange().length, 0)
        XCTAssertFalse(coordinator.hasSelection)
    }

    private func textView(_ value: String) -> ResearchInlineTextView {
        let view = ResearchInlineTextView()
        view.string = value
        return view
    }
}
#endif
