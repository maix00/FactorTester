#if os(macOS)
import Foundation
import XCTest
@testable import FTClient

@MainActor
final class ResearchReportExportRendererTests: XCTestCase {
    func testExportRequestUsesTheAuthoritativeCLICommand() {
        let request = ResearchReportExportRequest(
            profileID: "maxa",
            reportWorkspaceID: "work-one",
            branchID: "branch-one",
            format: .pdf
        )
        let output = URL(fileURLWithPath: "/tmp/研究报告.pdf")

        XCTAssertEqual(request.arguments(output: output), [
            "report", "export",
            "--profile", "maxa",
            "--report-workspace-id", "work-one",
            "--branch-id", "branch-one",
            "--format", "pdf",
            "--output", "/tmp/研究报告.pdf",
            "--force",
            "--json",
        ])
    }

    func testExportFormatsKeepIndependentExtensionsAndLabels() {
        XCTAssertEqual(ResearchReportExportFormat.markdown.extensionName, "md")
        XCTAssertEqual(ResearchReportExportFormat.pdf.extensionName, "pdf")
        XCTAssertNotEqual(
            ResearchReportExportFormat.markdown.localizedTitle,
            ResearchReportExportFormat.pdf.localizedTitle
        )
    }
}
#endif
