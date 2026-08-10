import XCTest
@testable import FTClient

final class ClientLocalCatalogBridgeTests: XCTestCase {
    func testReadRequestUsesBoundedClientCatalogCommand() throws {
        let arguments = try ClientLocalCatalogBridgeContract.arguments(message: [
            "action": "request",
            "path": "/api/client/product_sources?data_source=Tiger",
            "method": "GET",
        ])

        XCTAssertEqual(arguments, [
            "client", "catalog", "source", "request",
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
            "/api/catalog/sources",
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
