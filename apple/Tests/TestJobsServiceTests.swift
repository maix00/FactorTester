import Foundation
import XCTest
@testable import FTClient

final class TestJobsServiceTests: XCTestCase {
    func testArtifactTablePreservesTypedFactorReferenceColumns() throws {
        let data = Data(#"""
        {
          "schema_version": 1,
          "column_presentations": {
            "factor_alias": {
              "presentation": "reference",
              "kind": "factor",
              "target_ref_field": "factor_ref"
            }
          },
          "rows": [{
            "factor_alias": "MmRateOfChg|P:[CA]|N:20d|$F:1d",
            "factor_ref": "factor-expr:MmRateOfChg|P:[CA]|N:20d|$F:1d@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "ic_mean": 0.12
          }]
        }
        """#.utf8)

        let table = try TestJobsService.decodeArtifactTable(data)

        XCTAssertEqual(table.rows.count, 1)
        XCTAssertEqual(table.visibleColumns, ["factor_alias", "ic_mean"])
        XCTAssertEqual(table.presentation(for: "factor_alias")?.kind, "factor")
        XCTAssertEqual(
            table.referenceTarget(column: "factor_alias", row: table.rows[0]),
            "factor-expr:MmRateOfChg|P:[CA]|N:20d|$F:1d@sha256:" + String(repeating: "a", count: 64)
        )
    }

    func testSafeJSONDataRejectsInvalidNestedValues() {
        let value: [String: Any] = [
            "timestamp": Date(),
            "object": NSObject(),
        ]

        XCTAssertNil(TestJobsService.safeJSONData(value))
    }

    func testSafeJSONDataSupportsScalarResultValues() throws {
        let data = try XCTUnwrap(
            TestJobsService.safeJSONData("historical result")
        )

        XCTAssertEqual(
            try JSONSerialization.jsonObject(
                with: data,
                options: [.fragmentsAllowed]
            ) as? String,
            "historical result"
        )
    }
}
