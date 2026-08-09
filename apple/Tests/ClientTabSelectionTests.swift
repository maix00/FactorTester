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

    func testManagerDocumentationAndDatabaseModulesAlwaysOpenNewTabs() throws {
        let data = #"{"id":"docs","title":"技术文档","desc":"","icon":"","sfSymbol":"book","path":"/docs","requiresAuth":false,"roles":[]}"#.data(using: .utf8)!
        let docs = try JSONDecoder().decode(Module.self, from: data)
        let first = ClientTab.module(docs)
        let second = ClientTab.module(docs)
        XCTAssertNotEqual(first.id, second.id)
        XCTAssertTrue(first.isClosable)

        let databaseData = #"{"id":"sqlite_web","title":"数据库","desc":"","icon":"","sfSymbol":"cylinder.split.1x2","path":"/sqlite-web/","requiresAuth":true,"roles":[]}"#.data(using: .utf8)!
        let database = try JSONDecoder().decode(Module.self, from: databaseData)
        XCTAssertNotEqual(ClientTab.module(database).id, ClientTab.module(database).id)
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
        let evidence = ClientTab.reference(.init(
            kind: "evidence", targetRef: "evidence:1", label: "证据"
        ))
        guard case let .web(path)? = evidence?.content else {
            return XCTFail("evidence must open a Swift-owned Web tab")
        }
        XCTAssertTrue(path.hasPrefix("/reference?"), path)
        let query = URLComponents(string: path)?.queryItems ?? []
        XCTAssertEqual(query.first(where: { $0.name == "kind" })?.value, "evidence")
        XCTAssertEqual(query.first(where: { $0.name == "target" })?.value, "evidence:1")

        let nestedTarget = "evidence:factor[P:[[CA]]]|N:20d"
        let nested = ClientTab.reference(.init(
            kind: "evidence", targetRef: nestedTarget, label: "嵌套参数证据"
        ))
        guard case let .web(nestedPath)? = nested?.content else {
            return XCTFail("nested reference must open a Web tab")
        }
        let nestedQuery = URLComponents(string: nestedPath)?.queryItems ?? []
        XCTAssertEqual(
            nestedQuery.first(where: { $0.name == "target" })?.value,
            nestedTarget,
        )

        let frozenPlan = ClientTab.reference(.init(
            kind: "trial_plan", targetRef: "trial-plan:sha256:abc", label: "试验计划"
        ))
        guard case let .web(planPath)? = frozenPlan?.content else {
            return XCTFail("TrialPlan must open a Swift-owned Web tab")
        }
        XCTAssertTrue(planPath.hasPrefix("/reference?"), planPath)
        XCTAssertTrue(planPath.contains("kind=trial_plan"), planPath)

        let url = ClientTab.reference(.init(
            kind: "url", targetRef: "https://example.com/a", label: "网页"
        ))
        guard case let .externalWeb(value)? = url?.content else {
            return XCTFail("URL must open a Swift-owned Web tab")
        }
        XCTAssertEqual(value.absoluteString, "https://example.com/a")
    }

    func testEmbeddedWebProductNavigationReachesNativeTabBridge() {
        let paths = [
            "/products/group/product-group:cn-futures",
            "/products/product/SI.GFE",
            "/products/contract/SI2409",
            "/products/continuous-contract/CNFutures.SI",
        ]
        for path in paths {
            XCTAssertEqual(
                ResearchDocumentWebNavigationMessage.path(from: ["path": path]),
                path
            )
        }
        XCTAssertNil(
            ResearchDocumentWebNavigationMessage.path(from: [
                "path": "https://example.com/products/product/SI.GFE"
            ])
        )
        XCTAssertNil(
            ResearchDocumentWebNavigationMessage.path(from: ["path": "/products"])
        )
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

    func testTestJobUsesEmbeddedWebDetailPath() {
        let job = TestJob(
            id: "job:one",
            kind: "ic",
            status: "succeeded",
            workspaceID: "",
            port: 8141,
            profile: "",
            updatedAt: nil,
            artifactCount: 0
        )
        let tab = ClientTab.testJob(job)
        guard case let .web(path) = tab.content else {
            return XCTFail("test job must use the embedded Web detail page")
        }
        XCTAssertEqual(path, "/jobs/8141/job%3Aone")
        XCTAssertTrue(tab.isClosable)
    }
}
