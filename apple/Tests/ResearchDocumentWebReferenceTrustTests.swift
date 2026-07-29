import WebKit
import XCTest
@testable import FTClient

@MainActor
final class ResearchDocumentWebReferenceTrustTests: XCTestCase {
    func testUnboundMathRichTextRendersPlainAgentLabel() throws {
        let html = try XCTUnwrap(MathRichTextDocument.makeHTML(source))
        let result = try render(html, selector: "#content")

        XCTAssertEqual(result.references, 0)
        XCTAssertTrue(result.text.contains("Agent 标签"))
        XCTAssertFalse(result.text.contains("factortester://"))
    }

    func testBoundMathTableRendersClickableAgentLabel() throws {
        let key = ResearchDocumentReferenceScope.webKey(
            kind: "evidence",
            targetRef: "evidence:one"
        )
        let html = try XCTUnwrap(MathTableDocument.makeHTML(
            columns: ["说明"],
            rows: [[source]],
            trustedReferenceKeys: [key]
        ))
        let result = try render(html, selector: "#table")

        XCTAssertEqual(result.references, 1)
        XCTAssertTrue(result.text.contains("Agent 标签"))
    }

    private var source: String {
        "[Agent 标签](factortester://evidence/evidence%3Aone) 与 \\(IC>0\\)"
    }

    private func render(
        _ html: String,
        selector: String
    ) throws -> WebResult {
        let loaded = expectation(description: "document loaded")
        let observer = TrustNavigationObserver(finished: loaded)
        let webView = WKWebView()
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [loaded], timeout: 3)

        let evaluated = expectation(description: "DOM inspected")
        var result: WebResult?
        webView.evaluateJavaScript("""
        ({references:document.querySelectorAll('.ft-reference').length,
          text:document.querySelector('\(selector)').textContent})
        """) { value, _ in
            if let payload = value as? [String: Any] {
                result = WebResult(
                    references: payload["references"] as? Int ?? -1,
                    text: payload["text"] as? String ?? ""
                )
            }
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)
        return try XCTUnwrap(result)
    }
}

private struct WebResult {
    let references: Int
    let text: String
}

private final class TrustNavigationObserver: NSObject, WKNavigationDelegate {
    let finished: XCTestExpectation

    init(finished: XCTestExpectation) {
        self.finished = finished
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        finished.fulfill()
    }
}
