import CryptoKit
import XCTest
@testable import FTClient

final class ResearchDocumentAssetViewTests: XCTestCase {
    func testLoadsHashVerifiedPackageAsset() async throws {
        let fixture = try Fixture(svg: #"<svg xmlns="http://www.w3.org/2000/svg"/>"#)
        defer { fixture.remove() }

        let loaded = try await ResearchDocumentAssetLoader.load(
            asset: fixture.asset, reportRef: fixture.head.absoluteString
        )

        XCTAssertEqual(loaded, fixture.data)
    }

    func testRejectsActiveSVG() async throws {
        let fixture = try Fixture(svg: #"<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>"#)
        defer { fixture.remove() }

        do {
            _ = try await ResearchDocumentAssetLoader.load(
                asset: fixture.asset, reportRef: fixture.head.absoluteString
            )
            XCTFail("active SVG must not render")
        } catch let error as ResearchDocumentAssetError {
            guard case .unsafeSVG = error else { return XCTFail("unexpected error") }
        }
    }

    func testCachedJobArtifactDoesNotRequirePersonalWorkspaceAccess() throws {
        let fixture = try Fixture(svg: #"<svg xmlns="http://www.w3.org/2000/svg"/>"#)
        defer { fixture.remove() }
        let cacheRoot = fixture.root.appendingPathComponent("jobs", isDirectory: true)
        let jobDirectory = cacheRoot.appendingPathComponent("job-1", isDirectory: true)
        try FileManager.default.createDirectory(
            at: jobDirectory, withIntermediateDirectories: true
        )
        let asset = ResearchDocumentAsset(
            id: "job-asset", assetRef: "job-artifact:job-1:equity_curve_report",
            mediaType: "image/svg+xml", filename: "equity_curve_report.svg",
            caption: "", altText: "", contentHash: "",
            externalRef: "factortester-artifact://jobs/job-1/equity_curve_report",
            localRef: ""
        )

        let resolved = try ResearchDocumentAssetLoader.resolvedFile(
            asset, reportURL: fixture.head, jobCacheRoot: cacheRoot
        )

        XCTAssertEqual(
            resolved.url,
            jobDirectory.appendingPathComponent("equity_curve_report.svg")
        )
        XCTAssertEqual(resolved.access, .appManagedJobCache)
    }
}

private struct Fixture {
    let root: URL
    let head: URL
    let data: Data
    let asset: ResearchDocumentAsset

    init(svg: String) throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        head = root.appendingPathComponent("branches/main/authoring/HEAD.json")
        data = Data(svg.utf8)
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let assets = root.appendingPathComponent("assets", isDirectory: true)
        try FileManager.default.createDirectory(at: assets, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: head.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: head)
        try data.write(to: assets.appendingPathComponent("chart.svg"))
        asset = ResearchDocumentAsset(
            id: "asset", assetRef: "asset", mediaType: "image/svg+xml",
            filename: "chart.svg", caption: "", altText: "", contentHash: hash,
            externalRef: "", localRef: "assets/chart.svg"
        )
    }

    func remove() { try? FileManager.default.removeItem(at: root) }
}
