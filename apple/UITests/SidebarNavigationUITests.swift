import XCTest

final class SidebarNavigationUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += [
            "-AppleLanguages", "(zh-Hans)",
            "-ApplePersistenceIgnoreState", "YES",
        ]
        app.launch()
        XCTAssertTrue(
            app.buttons["sidebar.launch.home"].waitForExistence(timeout: 8)
        )
    }

    func testEveryPinnedSidebarDestinationOpens() {
        open("sidebar.launch.home", marker: "FactorTester")
        open("sidebar.launch.research", marker: "研究进度")
        open("sidebar.launch.profiles", marker: "Profiles")
        open("sidebar.launch.account", marker: "账户")
        open("sidebar.launch.settings", marker: "服务器")

        openWeb("sidebar.launch.web:factor-library")
        openWeb("sidebar.launch.web:products")
    }

    private func open(_ identifier: String, marker: String) {
        let item = app.buttons[identifier]
        XCTAssertTrue(item.waitForExistence(timeout: 3), identifier)
        item.click()
        XCTAssertTrue(
            app.staticTexts[marker].waitForExistence(timeout: 5),
            "\(identifier) did not open \(marker)"
        )
    }

    private func openWeb(_ identifier: String) {
        let item = app.buttons[identifier]
        XCTAssertTrue(item.waitForExistence(timeout: 3), identifier)
        item.click()
        let web = app.webViews.firstMatch
        let failure = app.staticTexts["页面无法打开"]
        XCTAssertTrue(
            web.waitForExistence(timeout: 5)
                || failure.waitForExistence(timeout: 1),
            "\(identifier) did not open a web surface or explicit error"
        )
    }
}
