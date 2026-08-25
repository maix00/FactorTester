import XCTest
import WebKit
@testable import FTClient

final class RenderedMathFormulaViewTests: XCTestCase {
    func testDisplayFormulaRoutesVerticalWheelToOuterReport() {
        XCTAssertEqual(
            ResearchMathWheelRouting.destination(
                deltaX: 0,
                deltaY: 12,
                hasHorizontalOverflow: true
            ),
            .outerReport
        )
    }

    func testDisplayFormulaOnlyKeepsHorizontalWheelWhenContentOverflows() {
        XCTAssertEqual(
            ResearchMathWheelRouting.destination(
                deltaX: 12,
                deltaY: 0,
                hasHorizontalOverflow: false
            ),
            .outerReport
        )
        XCTAssertEqual(
            ResearchMathWheelRouting.destination(
                deltaX: 12,
                deltaY: 0,
                hasHorizontalOverflow: true
            ),
            .webContent
        )
    }

    func testContainedComponentKeepsVerticalWheelOnlyWhenItOverflows() {
        XCTAssertEqual(
            ResearchMathWheelRouting.destination(
                deltaX: 0,
                deltaY: 12,
                hasHorizontalOverflow: true,
                hasVerticalOverflow: false
            ),
            .outerReport
        )
        XCTAssertEqual(
            ResearchMathWheelRouting.destination(
                deltaX: 0,
                deltaY: 12,
                hasHorizontalOverflow: false,
                hasVerticalOverflow: true
            ),
            .webContent
        )
    }

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
        XCTAssertTrue(html?.contains(
            #"#vertical{box-sizing:border-box;width:100%;height:100%;overflow-x:hidden;overflow-y:auto}"#
        ) == true)
        XCTAssertTrue(html?.contains(
            #"#horizontal{box-sizing:border-box;width:100%;overflow-x:auto;overflow-y:hidden}"#
        ) == true)
        XCTAssertTrue(html?.contains("data-ft-measure-height") == true)
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
        XCTAssertLessThan(html?.utf8.count ?? .max, 9_000)
    }

    @MainActor
    func testWideShortFormulaTableOnlyOverflowsHorizontally() throws {
        let html = try XCTUnwrap(MathTableDocument.makeHTML(
            columns: ["指标", "很宽的公式"],
            rows: [["IR", String(repeating: #"\(x_t+y_t\) "#, count: 30)]]
        ))
        let finished = expectation(description: "wide formula table loaded")
        let observer = MathNavigationObserver(finished: finished)
        let webView = WKWebView(frame: CGRect(x: 0, y: 0, width: 320, height: 400))
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [finished], timeout: 3)

        let evaluated = expectation(description: "table axes inspected")
        var result: [String: Any]?
        webView.evaluateJavaScript("""
        (function(){
          const horizontal=document.getElementById('horizontal');
          const vertical=document.getElementById('vertical');
          return {
            horizontalOverflow:horizontal.scrollWidth>horizontal.clientWidth+1,
            verticalOverflow:vertical.scrollHeight>vertical.clientHeight+1
          };
        })()
        """) { value, _ in
            result = value as? [String: Any]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?["horizontalOverflow"] as? Bool, true)
        XCTAssertEqual(result?["verticalOverflow"] as? Bool, false)
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
        let target = "factor:v2:" + String(repeating: "a", count: 43)
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
        let target = "factor-family:v2:" + String(repeating: "a", count: 43)
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
          const icon=reference?.querySelector('.ft-reference-icon');
          return {
            separator:reference?.nextSibling?.textContent,
            iconMask:getComputedStyle(icon).webkitMaskImage,
            iconWidth:icon?.getBoundingClientRect().width,
            color:getComputedStyle(reference).color,
            decoration:getComputedStyle(reference).textDecorationLine
          };
        })()
        """) { value, _ in
            result = value as? [String: Any]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?["separator"] as? String, " = ")
        XCTAssertTrue(
            (result?["iconMask"] as? String)?.contains(
                "data:image/png;base64,"
            ) == true
        )
        XCTAssertGreaterThan(result?["iconWidth"] as? Double ?? 0, 0)
        XCTAssertTrue(
            ["rgb(203, 48, 224)", "rgb(219, 52, 242)"]
                .contains(result?["color"] as? String ?? "")
        )
        XCTAssertEqual(result?["decoration"] as? String, "none")
    }

    func testHeightMeasurementUsesRenderedChildrenNotTheViewport() {
        XCTAssertTrue(
            ResearchMathRuntime.renderer.contains(
                "Array.from(body.children)"
            )
        )
        XCTAssertTrue(
            ResearchMathRuntime.renderer.contains(
                "Math.ceil(Math.max(1,bottom-origin))"
            )
        )
        XCTAssertFalse(
            ResearchMathRuntime.renderer.contains(
                "document.documentElement.scrollHeight"
            )
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

    func testWebReferenceMessageDecodesExternalAndLocalReferences() {
        let webTarget = "https://example.com/research.pdf"
        let fileTarget = "assets/results/equity.csv"
        let web = ResearchDocumentWebReferenceMessage.decode([
            "href": "factortester://url/"
                + webTarget.addingPercentEncoding(
                    withAllowedCharacters: .alphanumerics
                )!,
            "label": "研究论文",
        ])
        let file = ResearchDocumentWebReferenceMessage.decode([
            "href": "factortester://file/"
                + fileTarget.addingPercentEncoding(
                    withAllowedCharacters: .alphanumerics
                )!,
            "label": "权益曲线",
        ])

        XCTAssertEqual(web?.kind, "url")
        XCTAssertEqual(web?.targetRef, webTarget)
        XCTAssertEqual(web?.label, "研究论文")
        XCTAssertEqual(file?.kind, "file")
        XCTAssertEqual(file?.targetRef, fileTarget)
        XCTAssertEqual(file?.label, "权益曲线")
    }

    @MainActor
    func testRichTextRoutesWebAndLocalLinksThroughReferenceHandler() throws {
        let html = try XCTUnwrap(MathRichTextDocument.makeHTML(
            "参见 [论文](https://example.com/research.pdf)、"
                + "[结果](assets/results/equity.csv)、"
                + "[上下文](CONTEXT.md)，且 \\(IC>0\\)"
        ))
        let finished = expectation(description: "external links loaded")
        let observer = MathNavigationObserver(finished: finished)
        let webView = WKWebView()
        webView.navigationDelegate = observer
        webView.loadHTMLString(html, baseURL: BundledKaTeXRuntime.baseURL)
        wait(for: [finished], timeout: 3)

        let evaluated = expectation(description: "external link DOM inspected")
        var result: [[String: String]]?
        webView.evaluateJavaScript("""
        Array.from(document.querySelectorAll('.ft-reference')).map(link => ({
          href:link.href,label:link.dataset.referenceLabel
        }))
        """) { value, _ in
            result = value as? [[String: String]]
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 3)

        XCTAssertEqual(result?.count, 3)
        XCTAssertTrue(result?[0]["href"]?.hasPrefix("factortester://url/") == true)
        XCTAssertEqual(result?[0]["label"], "论文")
        XCTAssertTrue(result?[1]["href"]?.hasPrefix("factortester://file/") == true)
        XCTAssertEqual(result?[1]["label"], "结果")
        XCTAssertTrue(result?[2]["href"]?.hasPrefix("factortester://file/") == true)
        XCTAssertEqual(result?[2]["label"], "上下文")
        let web = ResearchDocumentWebReferenceMessage.decode([
            "href": result?[0]["href"] as Any,
            "label": result?[0]["label"] as Any,
        ])
        let file = ResearchDocumentWebReferenceMessage.decode([
            "href": result?[1]["href"] as Any,
            "label": result?[1]["label"] as Any,
        ])
        XCTAssertEqual(web?.targetRef, "https://example.com/research.pdf")
        XCTAssertEqual(file?.targetRef, "assets/results/equity.csv")
        let rootFile = ResearchDocumentWebReferenceMessage.decode([
            "href": result?[2]["href"] as Any,
            "label": result?[2]["label"] as Any,
        ])
        XCTAssertEqual(rootFile?.targetRef, "CONTEXT.md")
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
