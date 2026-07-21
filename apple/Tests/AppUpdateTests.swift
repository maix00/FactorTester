import XCTest
@testable import FTClient

final class AppUpdateTests: XCTestCase {
    func testVersionOrderIsNumericAndMonotonic() {
        XCTAssertTrue(VersionOrder.isNewer("1.10.0", than: "1.9.9"))
        XCTAssertFalse(VersionOrder.isNewer("1.2.0", than: "1.2.0"))
        XCTAssertFalse(VersionOrder.isNewer("1.1.9", than: "1.2.0"))
        XCTAssertTrue(VersionOrder.isNewer("1.2.0", than: "1.2.0-beta.2"))
        XCTAssertTrue(VersionOrder.isNewer("1.2.0-beta.10", than: "1.2.0-beta.2"))
        XCTAssertTrue(VersionOrder.isNewerRelease(
            version: "1.2.0", build: 13, thanVersion: "1.2.0", build: 12
        ))
    }

    func testSignedChannelContractDecodesExactInstallerMetadata() throws {
        let data = """
        {"schema_version":1,"version":"1.2.0","build":12,"channel":"stable",
         "dmg_url":"https://example.test/FactorTester-Client.dmg",
         "sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
         "minimum_client":"1.0.0","mandatory":false,
         "published_at":"2026-07-20T12:00:00Z",
         "signature":{"algorithm":"ecdsa-sha256","key_id":"key","value":"sig"}}
        """.data(using: .utf8)!
        let manifest = try JSONDecoder().decode(AppUpdateManifest.self, from: data)

        XCTAssertEqual(manifest.version, "1.2.0")
        XCTAssertEqual(manifest.build, 12)
        XCTAssertEqual(manifest.channel, "stable")
        XCTAssertEqual(manifest.dmgURL.scheme, "https")
    }

    func testUpdateTransportAllowsOnlyHTTPSOrLoopbackHTTP() {
        XCTAssertTrue(TrustedUpdateURL.accepts(
            URL(string: "http://127.0.0.1:8141/FTClient.dmg")!
        ))
        XCTAssertTrue(TrustedUpdateURL.accepts(
            URL(string: "http://[::1]:8141/FTClient.dmg")!
        ))
        XCTAssertTrue(TrustedUpdateURL.accepts(
            URL(string: "https://example.test/FTClient.dmg")!
        ))
        XCTAssertFalse(TrustedUpdateURL.accepts(
            URL(string: "http://example.test/FTClient.dmg")!
        ))
        XCTAssertFalse(TrustedUpdateURL.sameOrigin(
            URL(string: "http://127.0.0.1:8141/FTClient.dmg")!,
            URL(string: "http://127.0.0.1:8142/beta.json")!
        ))
    }

    func testMinimumClientCompatibilityFailsClosed() {
        XCTAssertFalse(ClientCompatibility.accepts(
            installed: "1.1.9", minimum: "1.2.0"
        ))
        XCTAssertTrue(ClientCompatibility.accepts(
            installed: "1.2.0", minimum: "1.2.0"
        ))
        XCTAssertTrue(ClientCompatibility.accepts(
            installed: "1.3.0", minimum: "1.2.0"
        ))
        XCTAssertFalse(ClientCompatibility.accepts(
            installed: "unknown", minimum: "1.2.0"
        ))
        XCTAssertFalse(ClientCompatibility.accepts(
            installed: "1.2.0", minimum: "01.2.0"
        ))
    }
}
