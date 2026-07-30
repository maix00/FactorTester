import XCTest
import WebKit
@testable import FTClient

final class RenderedMathFormulaViewTests: XCTestCase {
    func testDocumentUsesSmallJSONBootstrapWithoutRemoteRuntime() {
        let script = MathFormulaDocument.bootstrapScript(
            latex: #"x_t < y_t & z_t"#,
            fallback: "价格 < 区间"
        )

        XCTAssertTrue(script.contains(#"x_t < y_t & z_t"#))
        XCTAssertTrue(script.contains("价格 < 区间"))
        XCTAssertFalse(script.contains("https://"))
        XCTAssertLessThan(script.utf8.count, 512)
    }

    func testKaTeXRuntimeIsBundledWithTheApplication() {
        let url = Bundle.main.url(
            forResource: "katex.min",
            withExtension: "js",
            subdirectory: BundledKaTeXRuntime.directoryName
        )

        XCTAssertNotNil(url)
        let html = MathFormulaDocument.makeHTML(
            latex: #"x_t=\\frac{p_t}{p_{t-1}}"#,
            fallback: "收益率定义"
        )
        XCTAssertTrue(html?.contains("katex.render") == true)
        XCTAssertTrue(html?.contains(
            #"<script src="katex.min.js"></script>"#
        ) == true)
        XCTAssertTrue(html?.contains("<script src=\"http") == false)
        XCTAssertLessThan(html?.utf8.count ?? .max, 8_000)
    }

    func testFormulaTableUsesOneLocalKaTeXDocument() {
        let html = MathTableDocument.makeHTML(
            columns: ["指标", "定义"],
            rows: [["IR", #"\\(\\frac{\\mu}{\\sigma}\\)"#]]
        )

        XCTAssertTrue(html?.contains("katex.render") == true)
        XCTAssertTrue(html?.contains("<table id=\"table\"></table>") == true)
        XCTAssertTrue(html?.contains("window.ftAppendResearchRichText") == true)
        XCTAssertTrue(html?.contains(".ft-reference") == true)
        XCTAssertTrue(html?.contains("messageHandlers.researchReference") == true)
        XCTAssertTrue(html?.contains("document.createElement('a')") == true)
        XCTAssertTrue(html?.contains("th code,td code") == true)
        XCTAssertTrue(html?.contains("box-decoration-break:clone") == true)
        XCTAssertTrue(html?.contains("line-height:1") == true)
        XCTAssertTrue(html?.contains(
            #"<script src="katex.min.js"></script>"#
        ) == true)
        XCTAssertTrue(html?.contains("<script src=\"http") == false)
        XCTAssertLessThan(html?.utf8.count ?? .max, 8_000)
    }

    func testFormulaAndReferenceAreDistinctRichTextTokens() {
        let html = MathRichTextDocument.makeHTML(
            #"结论见 [证据](factortester://evidence/evidence%3Aic)，且 \(IC>0\)"#
        )

        XCTAssertTrue(html?.contains("document.createElement('a')") == true)
        XCTAssertTrue(html?.contains(
            "document.createElement(match[4]!==undefined?'span':'div')"
        ) == true)
        XCTAssertTrue(html?.contains("katex.render(latex,root") == true)
        XCTAssertFalse(
            html?.contains("katex.render(label") == true,
            "reference labels must never be interpreted as formulas"
        )
    }

    @MainActor
    func testBundledRuntimeRendersFormulaBesideReference() throws {
        let html = try XCTUnwrap(MathRichTextDocument.makeHTML(
            #"结论见 [证据](factortester://evidence/evidence%3Aic)，且 \(IC>0\)"#,
            trustedReferenceKeys: [
                ResearchDocumentReferenceScope.webKey(
                    kind: "evidence",
                    targetRef: "evidence:ic"
                ),
            ]
        ))
        let finished = expectation(description: "KaTeX document loaded")
        let observer = MathNavigationObserver(finished: finished)
        let webView = WKWebView()
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [finished], timeout: 3)

        let evaluated = expectation(description: "rendered DOM inspected")
        var result: [String: Any]?
        webView.evaluateJavaScript("""
        ({formulaCount:document.querySelectorAll('.katex').length,
          referenceCount:document.querySelectorAll('.ft-reference').length,
          formulaInsideReference:document.querySelector('.ft-reference .katex')!==null})
        """) { value, _ in
            result = value as? [String: Any]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?["formulaCount"] as? Int, 1)
        XCTAssertEqual(result?["referenceCount"] as? Int, 1)
        XCTAssertEqual(result?["formulaInsideReference"] as? Bool, false)
    }

    @MainActor
    func testBundledRuntimeKeepsEscapedFactorParametersInsideLinkLabel()
        throws
    {
        let label = #"SgCPS|P:\[CA\]|N:20d|$F:1m|$Rev"#
        let target = "factor:v1:profile-maxa:cGF0aA:YWxpYXM:"
            + String(repeating: "a", count: 40)
            + ":" + String(repeating: "b", count: 40)
        let html = try XCTUnwrap(MathRichTextDocument.makeHTML(
            "[\(label)](factortester://factor/"
                + target.addingPercentEncoding(
                    withAllowedCharacters: .alphanumerics
                )!
                + ")",
            trustedReferenceKeys: [
                ResearchDocumentReferenceScope.webKey(
                    kind: "factor",
                    targetRef: target
                ),
            ]
        ))
        let finished = expectation(description: "factor link document loaded")
        let observer = MathNavigationObserver(finished: finished)
        let webView = WKWebView()
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [finished], timeout: 3)

        let evaluated = expectation(description: "factor link DOM inspected")
        var result: [String: Any]?
        webView.evaluateJavaScript("""
        ({referenceCount:document.querySelectorAll('.ft-reference').length,
          formulaCount:document.querySelectorAll('.katex').length,
          label:document.querySelector('.ft-reference')?.dataset.referenceLabel,
          text:document.body.innerText})
        """) { value, _ in
            result = value as? [String: Any]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?["referenceCount"] as? Int, 1)
        XCTAssertEqual(result?["formulaCount"] as? Int, 0)
        XCTAssertEqual(
            result?["label"] as? String,
            "SgCPS|P:[CA]|N:20d|$F:1m|$Rev"
        )
        XCTAssertTrue(
            (result?["text"] as? String)?.contains(
                "SgCPS|P:[CA]|N:20d|$F:1m|$Rev"
            ) == true
        )
    }

    @MainActor
    func testFactorAssignmentMatchesNativeColorIconAndSpacing() throws {
        let target = "factor-family:v1:momentum"
        let encoded = try XCTUnwrap(target.addingPercentEncoding(
            withAllowedCharacters: .alphanumerics
        ))
        let html = try XCTUnwrap(MathRichTextDocument.makeHTML(
            "[MmTrend](factortester://factor/\(encoded))=\\(P_t\\)",
            trustedReferenceKeys: [
                ResearchDocumentReferenceScope.webKey(
                    kind: "factor",
                    targetRef: target
                ),
            ]
        ))
        let finished = expectation(description: "factor assignment loaded")
        let observer = MathNavigationObserver(finished: finished)
        let webView = WKWebView()
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [finished], timeout: 3)

        let evaluated = expectation(description: "factor assignment inspected")
        var result: [String: Any]?
        webView.evaluateJavaScript("""
        (function(){
          const reference=document.querySelector('.ft-reference');
          return {
            separator:reference?.nextSibling?.textContent,
            icon:reference?.querySelector('.ft-reference-icon')?.innerText,
            color:getComputedStyle(reference).color
          };
        })()
        """) { value, _ in
            result = value as? [String: Any]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?["separator"] as? String, " = ")
        XCTAssertEqual(result?["icon"] as? String, "ƒ(x)")
        XCTAssertTrue(
            ["rgb(175, 82, 222)", "rgb(191, 90, 242)"]
                .contains(result?["color"] as? String ?? "")
        )
    }

    func testWebReferenceMessageAcceptsOnlyTypedResearchLinks() {
        let reference = ResearchDocumentWebReferenceMessage.decode([
            "href": "factortester://obligation/obligation%3Afees",
            "label": "手续费覆盖义务",
        ])

        XCTAssertEqual(reference?.kind, "obligation")
        XCTAssertEqual(reference?.targetRef, "obligation:fees")
        XCTAssertEqual(reference?.label, "手续费覆盖义务")
        XCTAssertNil(ResearchDocumentWebReferenceMessage.decode([
            "href": "file:///etc/passwd",
            "label": "无效",
        ]))
    }

}

private final class MathNavigationObserver: NSObject, WKNavigationDelegate {
    let finished: XCTestExpectation

    init(finished: XCTestExpectation) {
        self.finished = finished
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        finished.fulfill()
    }
}
