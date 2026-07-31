import XCTest

final class ResearchReportSectionBridgeUITests: XCTestCase {
    func testBridgeIsContinuousAtEveryNestingLevel() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments += [
            "--ui-test-report-section-bridge",
            "-AppleLanguages", "(zh-Hans)",
            "-ApplePersistenceIgnoreState", "YES",
        ]
        app.launch()
        app.activate()

        let report = app.scrollViews["research.report.page"]
        XCTAssertTrue(report.waitForExistence(timeout: 12))
        XCTAssertEqual(
            app.otherElements.matching(
                identifier: "research.report.section.bridge"
            ).count,
            2
        )
        XCTAssertTrue(app.staticTexts["普通小节内容默认展示"].exists)
        XCTAssertTrue(app.staticTexts["路径后的普通内容默认展示"].exists)
        XCTAssertTrue(app.staticTexts["嵌套普通内容默认展示"].exists)
        XCTAssertFalse(app.staticTexts["特殊小节内容点击后展示"].exists)
        XCTAssertFalse(app.staticTexts["路径后的特殊内容"].exists)
        XCTAssertFalse(app.staticTexts["嵌套特殊内容点击后展示"].exists)

        expand("特殊小节", in: app)
        XCTAssertTrue(
            app.staticTexts["特殊小节内容点击后展示"]
                .waitForExistence(timeout: 3)
        )
        XCTAssertTrue(app.buttons["研究路径选择"].exists)

        expand("嵌套特殊小节", in: app)
        XCTAssertTrue(
            app.staticTexts["嵌套特殊内容点击后展示"]
                .waitForExistence(timeout: 3)
        )
    }

    private func expand(_ title: String, in app: XCUIApplication) {
        let button = app.buttons.matching(
            NSPredicate(format: "label CONTAINS %@", title)
        ).firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 3))
        button.click()
    }
}
