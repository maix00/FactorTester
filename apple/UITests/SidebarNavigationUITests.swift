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

final class ResearchReportNavigationUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += [
            "--ui-test-report-navigation",
            "-AppleLanguages", "(zh-Hans)",
            "-ApplePersistenceIgnoreState", "YES",
        ]
        app.launch()
    }

    func testNavigationLoadsTargetBeforeScrollingAndDoesNotRebound() {
        let latest = node(8)
        XCTAssertTrue(latest.waitForExistence(timeout: 8))
        waitUntilCurrent(latest)

        let second = node(2)
        second.click()
        let secondChapter = app.descendants(matching: .any)[
            "research.report.chapter.chapter-2"
        ]
        XCTAssertTrue(secondChapter.waitForExistence(timeout: 5))
        waitUntilCurrent(second)

        Thread.sleep(forTimeInterval: 0.8)
        XCTAssertEqual(second.value as? String, "当前节点")
        XCTAssertNotEqual(node(1).value as? String, "当前节点")

        let seventh = node(7)
        seventh.click()
        XCTAssertTrue(app.descendants(matching: .any)[
            "research.report.chapter.chapter-7"
        ].waitForExistence(timeout: 5))
        waitUntilCurrent(seventh)
        Thread.sleep(forTimeInterval: 0.8)
        XCTAssertEqual(seventh.value as? String, "当前节点")
    }

    func testNaturalScrollingAdvancesThroughNeighboringChapters() {
        let second = node(2)
        XCTAssertTrue(second.waitForExistence(timeout: 8))
        second.click()
        waitUntilCurrent(second)

        let report = app.scrollViews["research.report.page"]
        XCTAssertTrue(report.waitForExistence(timeout: 3))
        report.swipeUp()

        let advanced = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                [3, 4].contains {
                    self.node($0).value as? String == "当前节点"
                }
            },
            object: nil
        )
        XCTAssertEqual(
            XCTWaiter.wait(for: [advanced], timeout: 5),
            .completed
        )
        XCTAssertNotEqual(node(1).value as? String, "当前节点")
    }

    private func node(_ number: Int) -> XCUIElement {
        app.buttons["research.report.node.chapter-\(number)"]
    }

    private func waitUntilCurrent(
        _ element: XCUIElement,
        timeout: TimeInterval = 5
    ) {
        let expectation = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "当前节点"),
            object: element
        )
        XCTAssertEqual(
            XCTWaiter.wait(for: [expectation], timeout: timeout),
            .completed
        )
    }
}
