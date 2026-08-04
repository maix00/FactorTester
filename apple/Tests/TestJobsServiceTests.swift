import Foundation
import XCTest
@testable import FTClient

final class TestJobsServiceTests: XCTestCase {
    func testResultArtifactResolverUsesDeclaredChartAndTableArtifacts() {
        let artifacts = [
            TestJobArtifact(
                id: "chart", name: "ic_series_report", description: "",
                sizeBytes: 10, state: "active", contentType: "image/svg+xml",
                serverFileName: "ic-series.svg"
            ),
            TestJobArtifact(
                id: "table-csv-receipt", name: "ic_statistics_csv_receipt", description: "",
                sizeBytes: 10, state: "active", contentType: "application/json",
                serverFileName: "ic-statistics-csv-receipt.json"
            ),
            TestJobArtifact(
                id: "table-json", name: "ic_statistics_data", description: "",
                sizeBytes: 10, state: "active", contentType: "application/json",
                serverFileName: "ic-statistics.json"
            ),
            TestJobArtifact(
                id: "table-json-receipt", name: "ic_statistics_data_receipt", description: "",
                sizeBytes: 10, state: "active", contentType: "application/json",
                serverFileName: "ic-statistics-data-receipt.json"
            ),
            TestJobArtifact(
                id: "table-csv", name: "ic_statistics_csv", description: "",
                sizeBytes: 10, state: "active", contentType: "text/csv",
                serverFileName: "ic-statistics.csv"
            ),
        ]
        let chart = TestJobOutputDeclaration(
            id: "ic_series", name: "ic_series", label: "IC 序列",
            presentation: "chart", viewer: "line_chart", formats: ["svg", "json"],
            artifacts: ["ic_series_report", "ic_series_data"]
        )
        let table = TestJobOutputDeclaration(
            id: "ic_statistics", name: "ic_statistics", label: "IC 统计",
            presentation: "table", viewer: "data_table", formats: ["csv", "json"],
            artifacts: [
                "ic_statistics_csv", "ic_statistics_csv_receipt",
                "ic_statistics_data", "ic_statistics_data_receipt",
            ]
        )

        XCTAssertEqual(
            TestJobResultArtifactResolver.image(for: chart, in: artifacts)?.name,
            "ic_series_report"
        )
        XCTAssertEqual(
            TestJobResultArtifactResolver.table(for: table, in: artifacts)?.name,
            "ic_statistics_data"
        )
    }

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
