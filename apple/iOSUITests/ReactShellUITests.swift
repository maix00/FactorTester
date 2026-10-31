import XCTest

final class ReactShellUITests: XCTestCase {
    func testLocalManagerReactLoginOpensKeycloak() {
        let app = XCUIApplication()
        app.launchArguments += ["-manager.scheme", "http", "-manager.host", "127.0.0.1",
                                "-manager.port", "7998", "-manager.selection-source", "manual"]
        app.launch()
        let english = app.buttons["Continue with your organization account"]
        let chinese = app.buttons["使用组织账户继续"]
        let login = english.waitForExistence(timeout: 20) ? english : chinese
        XCTAssertTrue(login.waitForExistence(timeout: 5), "React sign-in entry is missing")
        login.tap()
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 20), "Keycloak sign-in form did not open")
    }
}
