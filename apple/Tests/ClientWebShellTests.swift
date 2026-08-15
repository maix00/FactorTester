import XCTest
@testable import FTClient

final class ClientWebShellTests: XCTestCase {
    func testMainClientUsesStandaloneWebPresentation() {
        XCTAssertFalse(WebPresentationMode.standalone.usesEmbeddedShell)
        XCTAssertTrue(WebPresentationMode.embedded.usesEmbeddedShell)
    }

    func testStandalonePresentationKeepsWebOwnedNavigation() {
        let source = URL(string: "http://127.0.0.1:7998/?lang=en")!
        let result = EmbeddedPresentationURL.standalone(to: source)

        XCTAssertEqual(result?.path, "/")
        XCTAssertEqual(
            URLComponents(url: result!, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "presentation" })?.value,
            nil
        )
        XCTAssertEqual(
            URLComponents(url: result!, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "lang" })?.value,
            "en"
        )
    }
}
