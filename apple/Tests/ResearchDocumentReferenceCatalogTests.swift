import XCTest
@testable import FTClient

final class ResearchDocumentReferenceCatalogTests: XCTestCase {
    func testSemanticKindsShareOneNativeAndWebCatalog() {
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.descriptor(for: "evidence").tint,
            .evidence
        )
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.descriptor(for: "factor").tint,
            .factor
        )
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.descriptor(for: "profile_revision").tint,
            .profile
        )
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.descriptor(for: "contract").tint,
            .product
        )
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.descriptor(
                for: "continuous_contract"
            ).symbol,
            "chart.line.uptrend.xyaxis"
        )
        XCTAssertTrue(
            ResearchDocumentReferenceCatalog.webBootstrap.contains(
                #""profile_revision":{"icon":"♙","tone":"profile"}"#
            )
        )
        XCTAssertTrue(
            ResearchDocumentReferenceCatalog.webBootstrap.contains(
                #""evidence":{"icon":"⌕","tone":"evidence"}"#
            )
        )
        XCTAssertTrue(ResearchMathRuntime.renderer.contains("target.slice(15)"))
        XCTAssertTrue(
            ResearchMathRuntime.renderer.contains(
                "label:this.dataset.referenceLabel"
            )
        )
        XCTAssertTrue(
            ResearchDocumentReferenceCatalog.webCSS.contains(
                "--ft-ref-product"
            )
        )
    }

    func testPlainProductTextIsNeverGuessedAsAReference() {
        XCTAssertEqual(
            ResearchDocumentTypedLinkParser.segments(
                in: "SI.GFE 与工业硅只是普通正文"
            ),
            [.text("SI.GFE 与工业硅只是普通正文")]
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkParser.segments(
                in: "[伪对象](factortester://unregistered/value)"
            ),
            [.text("[伪对象](factortester://unregistered/value)")]
        )
    }

}
