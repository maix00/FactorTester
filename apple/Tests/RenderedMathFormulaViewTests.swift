import XCTest
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

    func testMathJaxRuntimeIsBundledWithTheApplication() {
        let url = Bundle.main.url(
            forResource: MathFormulaDocument.resourceName,
            withExtension: "js"
        )

        XCTAssertNotNil(url)
        let html = MathFormulaDocument.makeHTML(
            latex: #"x_t=\\frac{p_t}{p_{t-1}}"#,
            fallback: "收益率定义"
        )
        XCTAssertTrue(html?.contains("window.MathJax") == true)
        XCTAssertTrue(html?.contains(
            #"<script src="mathjax-tex-svg.js"></script>"#
        ) == true)
        XCTAssertTrue(html?.contains("<script src=\"http") == false)
        XCTAssertLessThan(html?.utf8.count ?? .max, 8_000)
    }

    func testFormulaDenseTableUsesOneLocalMathJaxDocument() {
        let html = MathTableDocument.makeHTML(
            columns: ["指标", "定义"],
            rows: [["IR", #"\\(\\frac{\\mu}{\\sigma}\\)"#]]
        )

        XCTAssertTrue(html?.contains("window.MathJax") == true)
        XCTAssertTrue(html?.contains("<table id=\"table\"></table>") == true)
        XCTAssertTrue(html?.contains("window.ftAppendResearchRichText") == true)
        XCTAssertTrue(html?.contains(".ft-reference") == true)
        XCTAssertTrue(html?.contains("th code,td code") == true)
        XCTAssertTrue(html?.contains(
            #"<script src="mathjax-tex-svg.js"></script>"#
        ) == true)
        XCTAssertTrue(html?.contains("<script src=\"http") == false)
        XCTAssertLessThan(html?.utf8.count ?? .max, 8_000)
    }

}
