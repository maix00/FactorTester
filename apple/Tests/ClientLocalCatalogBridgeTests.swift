import XCTest
@testable import FTClient

final class ClientLocalCatalogBridgeTests: XCTestCase {
    func testEmbeddedCatalogPagesIncludeBothTestWorkbenches() {
        let factorRef = String(repeating: "a", count: 43)
        for path in [
            "/products?source=local",
            "/products/product/JNI.OSE?source=local",
            "/factors",
            "/ic-test",
            "/ic-test/session-one",
            "/backtest?presentation=embedded",
            "/factor-series?factor_ref=factor%3Av2%3A\(factorRef)",
        ] {
            XCTAssertTrue(
                ClientLocalCatalogBridgeContract.allowsEmbeddedPage(path: path),
                path
            )
        }
    }

    func testEmbeddedCatalogPolicyRejectsUnrelatedOrExternalPages() {
        for path in [
            "/manager",
            "/ic-testing",
            "/backtester",
            "https://example.test/products",
        ] {
            XCTAssertFalse(
                ClientLocalCatalogBridgeContract.allowsEmbeddedPage(path: path),
                path
            )
        }
    }

    func testReadRequestUsesBoundedClientCatalogCommand() throws {
        let arguments = try ClientLocalCatalogBridgeContract.arguments(message: [
            "action": "request",
            "path": "/api/client/product_sources?data_source=Tiger",
            "method": "GET",
        ])

        XCTAssertEqual(arguments, [
            "client", "source", "request",
            "--path", "/api/client/product_sources?data_source=Tiger",
            "--method", "GET", "--json",
        ])
    }

    func testPostRequestValidatesAndForwardsJSONObject() throws {
        let arguments = try ClientLocalCatalogBridgeContract.arguments(message: [
            "action": "request",
            "path": "/api/client/product_prices",
            "method": "POST",
            "body": "{\"product_name\":\"JNI.OSE\"}",
        ])

        XCTAssertEqual(arguments.suffix(3), [
            "--body-json", "{\"product_name\":\"JNI.OSE\"}", "--json",
        ])
    }

    func testBridgeRejectsServerAndExternalRoutes() {
        for path in [
            "/api/product-library/data-sources",
            "https://example.test/api/client/product_sources",
        ] {
            XCTAssertThrowsError(
                try ClientLocalCatalogBridgeContract.arguments(message: [
                    "action": "request", "path": path,
                ])
            )
        }
    }
}
