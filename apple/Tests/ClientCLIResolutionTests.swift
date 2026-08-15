import XCTest
@testable import FTClient

final class ClientCLIResolutionTests: XCTestCase {
    func testBundledCLIWinsOverStaleConfiguredPath() {
        let resolved = ClientCLIResolution.resolve(
            bundledPath: "/Applications/FTClient.app/bundled/factortester",
            configuredPath: "/old/conda/bin/factortester",
            isExecutable: { $0.contains("bundled") }
        )

        XCTAssertEqual(
            resolved,
            "/Applications/FTClient.app/bundled/factortester"
        )
    }

    func testConfiguredPathRemainsFallbackWithoutBundledRuntime() {
        let resolved = ClientCLIResolution.resolve(
            bundledPath: "/missing/bundled/factortester",
            configuredPath: "/developer/bin/factortester",
            isExecutable: { _ in false }
        )

        XCTAssertEqual(resolved, "/developer/bin/factortester")
    }

    func testManagerResolutionUsesItsBundledExecutableAndFallbackName() {
        let resolved = ClientCLIResolution.resolve(
            bundledPath: "/Applications/FTClient.app/bundled/factortester-manager",
            configuredPath: "/developer/bin/factortester-manager",
            isExecutable: { $0.contains("bundled") }
        )

        XCTAssertEqual(
            resolved,
            "/Applications/FTClient.app/bundled/factortester-manager"
        )

        let fallback = ClientCLIResolution.resolve(
            bundledPath: "/missing/factortester-manager",
            configuredPath: nil,
            isExecutable: { _ in false }
        )
        XCTAssertEqual(fallback, "factortester-manager")
    }
}
