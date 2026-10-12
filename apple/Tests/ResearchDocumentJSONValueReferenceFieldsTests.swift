import XCTest
@testable import FTClient

final class ResearchDocumentJSONValueReferenceFieldsTests: XCTestCase {
    func testObjectFieldsKeepTheirContextAndFlattenNestedValues() {
        let value = ResearchJSONValue.object([
            "portfolio": .object([
                "source": .string("ticks"),
                "assets": .array([
                    .string("equity.csv"),
                    .string("rates.csv"),
                ]),
                "optional": .null,
            ]),
        ])

        XCTAssertEqual(
            value.referenceFields(prefix: "适用范围"),
            [
                .init(name: "适用范围.portfolio.assets", value: "equity.csv、rates.csv"),
                .init(name: "适用范围.portfolio.source", value: "ticks"),
            ]
        )
    }

    func testScalarValuesUseTheSuppliedFieldName() {
        XCTAssertEqual(
            ResearchJSONValue.boolean(true).referenceFields(prefix: "启用"),
            [.init(name: "启用", value: "是")]
        )
        XCTAssertEqual(
            ResearchJSONValue.null.referenceFields(prefix: "空值"),
            []
        )
    }
}
