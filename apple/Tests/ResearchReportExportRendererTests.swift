#if os(macOS)
import Foundation
import XCTest
@testable import FTClient

@MainActor
final class ResearchReportExportRendererTests: XCTestCase {
    func testMarkdownRendererUsesMaterializedReportNextToAuthoringTree() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let authoring = root.appendingPathComponent("authoring")
        try FileManager.default.createDirectory(
            at: authoring, withIntermediateDirectories: true
        )
        let head = authoring.appendingPathComponent("HEAD.json")
        let report = root.appendingPathComponent("REPORT.md")
        try Data("{}".utf8).write(to: head)
        try Data("# 研究报告\n\n结论".utf8).write(to: report)

        let source = try ResearchReportExportSource(reportRef: head.absoluteString)
        let output = try ResearchReportMarkdownRenderer().render(source)

        XCTAssertEqual(source.markdownURL, report)
        XCTAssertEqual(String(decoding: output, as: UTF8.self), "# 研究报告\n\n结论")
    }

    func testPDFRendererProducesARealPDFDocument() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let authoring = root.appendingPathComponent("authoring")
        try FileManager.default.createDirectory(
            at: authoring, withIntermediateDirectories: true
        )
        let head = authoring.appendingPathComponent("HEAD.json")
        let report = root.appendingPathComponent("REPORT.md")
        try Data("{}".utf8).write(to: head)
        try Data("# 研究报告\n\n- 第一项\n- 第二项".utf8).write(to: report)

        let source = try ResearchReportExportSource(reportRef: head.absoluteString)
        let output = try ResearchReportPDFRenderer().render(source)

        XCTAssertTrue(output.starts(with: Data("%PDF".utf8)))
        XCTAssertGreaterThan(output.count, 500)
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
