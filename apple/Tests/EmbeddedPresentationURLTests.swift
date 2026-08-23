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

    func testDocumentationDeepLinkUsesTheSharedEmbeddedWebRoute() {
        let source = URL(
            string: "https://example.test/docs/system-overview#main-flow"
        )!

        XCTAssertEqual(
            EmbeddedPresentationURL.add(to: source)?.absoluteString,
            "https://example.test/docs/system-overview?presentation=embedded#main-flow"
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

    func testStandaloneManagerPathRemovesEmbeddedPresentation() {
        let source = URL(
            string: "http://127.0.0.1:7998/sqlite-web/?presentation=embedded&a=1"
        )!

        XCTAssertEqual(
            EmbeddedPresentationURL.standalone(to: source)?.absoluteString,
            "http://127.0.0.1:7998/sqlite-web/?a=1"
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
