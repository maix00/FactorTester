import XCTest
@testable import FTClient

final class ClientTabSelectionTests: XCTestCase {
    func testEveryPinnedSelectionMountsDestinationBeforeSelectingIt() {
        let destinations = [
            ClientTab.research, .jobs, .factorLibrary, .products, .profiles,
            .accountSettings,
        ]

        for destination in destinations {
            var tabs = [ClientTab.home]
            var selection = ClientTab.home.id
            var mountedWhenSelected = false
            let router = ClientTabSelectionRouter(
                tabs: { tabs },
                setTabs: { tabs = $0 },
                setSelection: { selectedID in
                    mountedWhenSelected = tabs.contains {
                        $0.id == selectedID
                    }
                    selection = selectedID
                }
            )

            router.select(destination.id)

            XCTAssertTrue(
                tabs.contains { $0.id == destination.id },
                destination.id
            )
            XCTAssertEqual(selection, destination.id)
            XCTAssertTrue(mountedWhenSelected, destination.id)
        }
    }

    func testUnknownSelectionDoesNotInventATab() {
        var tabs = [ClientTab.home]
        var selection = ClientTab.home.id
        let router = ClientTabSelectionRouter(
            tabs: { tabs },
            setTabs: { tabs = $0 },
            setSelection: { selection = $0 }
        )

        router.select("work-package:not-mounted")

        XCTAssertEqual(tabs.map(\.id), [ClientTab.home.id])
        XCTAssertEqual(selection, "work-package:not-mounted")
    }

    func testEachTestLauncherCreatesANewClosablePage() {
        for launcher in [ClientTab.icTestLauncher, .backtestLauncher] {
            var tabs = [ClientTab.home]
            var selection = ClientTab.home.id
            let router = ClientTabSelectionRouter(
                tabs: { tabs },
                setTabs: { tabs = $0 },
                setSelection: { selection = $0 }
            )

            router.select(launcher.id)
            let first = selection
            router.select(launcher.id)

            XCTAssertNotEqual(first, selection)
            XCTAssertEqual(tabs.count, 3)
            XCTAssertTrue(tabs.dropFirst().allSatisfy(\.isClosable))
            XCTAssertFalse(tabs.contains { $0.id == launcher.id })
        }
    }

    func testReportObjectsOpenDedicatedWebTabs() {
        let cases: [(String, String, String)] = [
            ("factor", "factor:v1:abc", "/factors/factor/"),
            ("factor", "factor-family:v1:abc", "/factors/family/"),
            ("factor_set", "factor-set:v1:abc", "/factors/set/"),
            ("product", "product:CNFutures/A.DCE", "/products/product/"),
            ("product_group", "product-group:day", "/products/group/"),
            ("continuous_contract", "continuous-contract:A.DCE", "/products/continuous-contract/"),
            ("profile", "profile:maxa", "/profiles/"),
            ("job", "research-job:abc123", "/jobs/"),
        ]
        for (kind, targetRef, prefix) in cases {
            let tab = ClientTab.reference(.init(
                kind: kind, targetRef: targetRef, label: "对象"
            ))
            guard case let .web(path)? = tab?.content else {
                return XCTFail("\(kind) did not produce a Web tab")
            }
            XCTAssertTrue(path.hasPrefix(prefix), path)
            XCTAssertTrue(tab?.isClosable == true)
        }
        XCTAssertNil(ClientTab.reference(.init(
            kind: "evidence", targetRef: "evidence:1", label: "证据"
        )))
    }

    func testResearchShellIsPinnedAndReportIsDedicatedTab() {
        XCTAssertFalse(ClientTab.research.isClosable)

        let report = ClientTab.researchReport(path: "/research/local:report-1")
        XCTAssertTrue(report.isClosable)
        XCTAssertEqual(report.id, "web:research-report:/research/local:report-1")
        guard case let .web(path) = report.content else {
            return XCTFail("research report must be rendered in a dedicated Web tab")
        }
        XCTAssertEqual(path, "/research/local:report-1")
    }
}
