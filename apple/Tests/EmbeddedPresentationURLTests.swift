import XCTest
@testable import FTClient

final class EmbeddedPresentationURLTests: XCTestCase {
    func testAddingPresentationPreservesQueryAndFragment() {
        let source = URL(string: "https://example.test/docs?a=1#part")!
        let result = EmbeddedPresentationURL.add(to: source)

        XCTAssertEqual(
            result?.absoluteString,
            "https://example.test/docs?a=1&presentation=embedded#part"
        )
    }

    func testAddingPresentationReplacesExistingValue() {
        let source = URL(
            string: "https://example.test/docs?presentation=standalone"
        )!

        XCTAssertEqual(
            EmbeddedPresentationURL.add(to: source)?.absoluteString,
            "https://example.test/docs?presentation=embedded"
        )
    }

    func testRewriteOnlyAppliesToSameOriginTopLevelNavigation() {
        let origin = URL(string: "https://example.test:8141")!
        let sameOrigin = URL(string: "https://example.test:8141/products")!
        let otherPort = URL(string: "https://example.test:7899/")!

        XCTAssertEqual(
            EmbeddedPresentationURL.rewrite(sameOrigin, serverOrigin: origin),
            URL(string: "https://example.test:8141/products?presentation=embedded")
        )
        XCTAssertNil(
            EmbeddedPresentationURL.rewrite(otherPort, serverOrigin: origin)
        )
    }
}
