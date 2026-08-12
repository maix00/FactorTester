import CryptoKit
import XCTest
@testable import FTClient

final class ThirdPartyRuntimeTests: XCTestCase {
    func testBundledKaTeXMatchesPinnedManifest() throws {
        let directory = try XCTUnwrap(BundledKaTeXRuntime.baseURL)
        let data = try Data(
            contentsOf: directory.appendingPathComponent("checksums.json")
        )
        let manifest = try JSONDecoder().decode(
            ThirdPartyChecksumManifest.self,
            from: data
        )

        XCTAssertEqual(manifest.version, "0.16.45")
        XCTAssertTrue(manifest.source.hasSuffix("katex-0.16.45.tgz"))
        for (path, expected) in manifest.files {
            let content = try Data(
                contentsOf: directory.appendingPathComponent(path)
            )
            let actual = SHA256.hash(data: content).map {
                String(format: "%02x", $0)
            }.joined()
            XCTAssertEqual(actual, expected, path)
        }
    }
}

private struct ThirdPartyChecksumManifest: Decodable {
    let version: String
    let source: String
    let files: [String: String]
}
