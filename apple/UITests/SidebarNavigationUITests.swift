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
        ]
        app.launch()
        app.activate()
        let report = app.scrollViews["research.report.page"]
        XCTAssertTrue(
            report.waitForExistence(timeout: 12)
        )
    }

    func testNavigationLoadsTargetBeforeScrollingAndDoesNotRebound() {
        let latest = node(18)
        XCTAssertTrue(latest.waitForExistence(timeout: 8))
        let report = app.scrollViews["research.report.page"]
        XCTAssertTrue(report.waitForExistence(timeout: 3))
        let latestChapter = chapterHeading(18)
        XCTAssertTrue(latestChapter.waitForExistence(timeout: 5))
        waitUntilVisible(latestChapter, inside: report)
        waitUntilCurrent(latest)

        let second = node(2)
        second.click()
        let secondChapter = chapterHeading(2)
        XCTAssertTrue(secondChapter.waitForExistence(timeout: 5))
        waitUntilVisible(secondChapter, inside: report)
        waitUntilCurrent(second)

        Thread.sleep(forTimeInterval: 0.8)
        XCTAssertEqual(second.value as? String, "当前节点")
        XCTAssertNotEqual(node(1).value as? String, "当前节点")

        let seventeenth = node(17)
        seventeenth.click()
        let seventeenthChapter = chapterHeading(17)
        XCTAssertTrue(seventeenthChapter.waitForExistence(timeout: 5))
        waitUntilVisible(seventeenthChapter, inside: report)
        waitUntilCurrent(seventeenth)
        Thread.sleep(forTimeInterval: 0.8)
        XCTAssertEqual(seventeenth.value as? String, "当前节点")
        XCTAssertFalse(app.staticTexts["正在加载研究节点…"].exists)
    }

    func testGeneratedListHeadingIsHiddenAndLongListExpands() {
        let latest = node(18)
        XCTAssertTrue(latest.waitForExistence(timeout: 8))

        let report = app.scrollViews["research.report.page"]
        let latestChapter = chapterHeading(18)
        XCTAssertTrue(latestChapter.waitForExistence(timeout: 5))
        waitUntilVisible(latestChapter, inside: report)
        waitUntilCurrent(latest)

        XCTAssertFalse(app.staticTexts["列表"].exists)
        let toggle = app.buttons["research.report.list.toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 3))
        XCTAssertEqual(toggle.label, "显示其余 2 项")
        toggle.click()
        XCTAssertTrue(latestChapter.exists)
        waitUntilCurrent(latest)
        XCTAssertFalse(app.staticTexts["正在加载研究节点…"].exists)
    }

    func testNaturalScrollingAdvancesThroughNeighboringChapters() {
        let second = node(2)
        XCTAssertTrue(second.waitForExistence(timeout: 8))
        second.click()
        waitUntilCurrent(second)

        let report = app.scrollViews["research.report.page"]
        XCTAssertTrue(report.waitForExistence(timeout: 3))
        report.scroll(byDeltaX: 0, deltaY: -420)

        let advanced = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                [3, 4].contains {
                    self.node($0).value as? String == "当前节点"
                }
            },
            object: nil
        )
        let result = XCTWaiter.wait(for: [advanced], timeout: 5)
        let values = (1...8).map {
            "\($0)=\(node($0).value as? String ?? "-")"
        }.joined(separator: ",")
        XCTAssertEqual(
            result,
            .completed,
            "Unexpected current-node values after natural scroll: \(values)"
        )
        XCTAssertNotEqual(node(1).value as? String, "当前节点")
    }

    private func node(_ number: Int) -> XCUIElement {
        app.buttons["research.report.node.chapter-\(number)"]
    }

    private func chapterHeading(_ number: Int) -> XCUIElement {
        app.staticTexts["研究节点 \(number)"].firstMatch
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

    private func waitUntilVisible(
        _ element: XCUIElement,
        inside container: XCUIElement,
        timeout: TimeInterval = 5
    ) {
        let expectation = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                guard element.exists, container.exists else { return false }
                return element.frame.intersects(container.frame)
                    && element.frame.height > 0
            },
            object: nil
        )
        XCTAssertEqual(
            XCTWaiter.wait(for: [expectation], timeout: timeout),
            .completed
        )
    }
}
