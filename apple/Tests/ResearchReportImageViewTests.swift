import CryptoKit
import XCTest
@testable import FTClient

final class ResearchReportImageViewTests: XCTestCase {
    func testLoadsHashVerifiedAssetFromWorkPackageAssetsDirectory() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let package = root.appendingPathComponent("research/wp", isDirectory: true)
        let branch = package.appendingPathComponent(
            "branches/main",
            isDirectory: true
        )
        let assets = package.appendingPathComponent("assets", isDirectory: true)
        try FileManager.default.createDirectory(
            at: branch,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: assets,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let data = Data(
            #"<svg xmlns="http://www.w3.org/2000/svg"><title>净值</title></svg>"#
                .utf8
        )
        let digest = sha256(data)
        try data.write(to: assets.appendingPathComponent("\(digest).svg"))
        let report = branch.appendingPathComponent("REPORT.md")
        try Data("# 报告".utf8).write(to: report)
        let asset = descriptor(hash: digest)

        let loaded = try await ResearchReportAssetLoader.load(
            asset: asset,
            reportRef: report.absoluteString
        )

        XCTAssertEqual(loaded, data)
    }

    func testRejectsTamperedOrActiveSVG() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let package = root.appendingPathComponent("research/wp", isDirectory: true)
        let branch = package.appendingPathComponent(
            "branches/main",
            isDirectory: true
        )
        let assets = package.appendingPathComponent("assets", isDirectory: true)
        try FileManager.default.createDirectory(
            at: branch,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: assets,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let active = Data(
            #"<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>"#
                .utf8
        )
        let digest = sha256(active)
        try active.write(to: assets.appendingPathComponent("\(digest).svg"))
        let report = branch.appendingPathComponent("REPORT.md")
        try Data("# 报告".utf8).write(to: report)

        do {
            _ = try await ResearchReportAssetLoader.load(
                asset: descriptor(hash: digest),
                reportRef: report.absoluteString
            )
            XCTFail("active SVG must not render")
        } catch let error as ResearchReportAssetError {
            guard case .unsafeSVG = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    private func descriptor(hash: String) -> ResearchJournalAsset {
        ResearchJournalAsset(
            assetRef: "report-asset:sha256:\(hash)",
            contentHash: hash,
            mediaType: "image/svg+xml",
            filename: "\(hash).svg",
            caption: "净值曲线与回撤",
            altText: "回测净值曲线",
            availability: "available",
            provenanceRefs: ["job:job-1"]
        )
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
