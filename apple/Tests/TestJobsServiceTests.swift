import Foundation
import CryptoKit
import XCTest
@testable import FTClient

final class TestJobsServiceTests: XCTestCase {
    func testVerifiedJobBackupIsScopedAndRejectsTampering() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let bytes = Data("job output".utf8)
        let digest = SHA256.hash(data: bytes)
            .map { String(format: "%02x", $0) }.joined()
        let artifact = TestJobArtifact(
            id: "result", name: "result", description: "",
            sizeBytes: bytes.count, state: "deleted",
            contentType: "text/plain", serverFileName: "result.txt",
            contentHash: digest
        )
        let manager = try XCTUnwrap(URL(string: "https://manager.example:7998"))
        let root = try TestJobBackupStore.save(
            principal: "alice", managerURL: manager,
            storageServerID: "data-a", jobID: "job-1",
            downloads: [.init(artifact: artifact, data: bytes)],
            baseDirectory: temporary
        )
        XCTAssertTrue(TestJobBackupStore.hasBackup(
            principal: "alice", managerURL: manager, jobID: "job-1",
            artifact: artifact, baseDirectory: temporary
        ))
        XCTAssertEqual(try TestJobBackupStore.data(
            principal: "alice", managerURL: manager, jobID: "job-1",
            artifact: artifact, baseDirectory: temporary
        ), bytes)
        XCTAssertFalse(TestJobBackupStore.hasBackup(
            principal: "bob", managerURL: manager, jobID: "job-1",
            artifact: artifact, baseDirectory: temporary
        ))
        XCTAssertFalse(TestJobBackupStore.hasBackup(
            principal: "alice", managerURL: URL(string: "https://other.example:7998"),
            jobID: "job-1", artifact: artifact, baseDirectory: temporary
        ))
        let manifestData = try Data(contentsOf: root.appendingPathComponent("backup.json"))
        let manifest = try JSONDecoder().decode(TestJobBackupStore.Manifest.self, from: manifestData)
        let file = try XCTUnwrap(manifest.items.first?.file)
        try Data("tampered".utf8).write(to: root.appendingPathComponent(file))
        XCTAssertThrowsError(try TestJobBackupStore.data(
            principal: "alice", managerURL: manager, jobID: "job-1",
            artifact: artifact, baseDirectory: temporary
        ))
    }
    func testArtifactTransferAccessRequiresHTTPURLAndCapability() throws {
        let data = Data(#"{"access":{"url":"https://factor.example:7997/v1/transfers/a/download","bearer":"capability","expected_size":6}}"#.utf8)

        let value = try TestJobsService.decodeArtifactTransferAccess(data)

        XCTAssertEqual(value.url.port, 7997)
        XCTAssertEqual(value.bearer, "capability")
        XCTAssertEqual(value.expectedSize, 6)
    }

    func testProgressDecoderReadsHeartbeatSnapshot() {
        let value = TestJobsService.decodeProgress(
            #"{"status":"running","latest_progress":{"event":"signal_progress","data":{"phase":"event_replay","completed":2,"total":4,"percent":50}}}"#
        )

        XCTAssertEqual(value?.phase, "event_replay")
        XCTAssertEqual(value?.completed, 2)
        XCTAssertEqual(value?.total, 4)
        XCTAssertEqual(value?.fraction, 0.5)
    }
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
