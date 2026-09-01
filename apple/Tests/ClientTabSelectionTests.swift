import XCTest
@testable import FTClient

final class ClientTabSelectionTests: XCTestCase {
    func testTestsPageUsesTypeTabAndKeepsTestTypeDestinationsIndependent() {
        XCTAssertEqual(ClientTab.jobs.title, "测试")
        guard case .jobs = ClientTab.jobs.content else {
            return XCTFail("the Tests feature must own the jobs page")
        }

        for path in ["/ic-test", "/backtest"] {
            let first = ClientTab.embeddedNavigationDestination(for: path)
            let second = ClientTab.embeddedNavigationDestination(for: path)
            XCTAssertNotNil(first, path)
            XCTAssertNotNil(second, path)
            XCTAssertNotEqual(first?.id, second?.id, path)
            XCTAssertTrue(first?.isClosable == true, path)
        }
    }

    func testEmbeddedDocumentationLinksOpenTestPagesInSwiftTabs() {
        for path in ["/ic-test", "/backtest"] {
            XCTAssertEqual(
                ResearchDocumentWebNavigationMessage.path(from: ["path": path]),
                path
            )
            let destination = ClientTab.embeddedNavigationDestination(for: path)
            XCTAssertNotNil(destination, path)
            XCTAssertTrue(destination?.isClosable == true, path)
        }
    }

    func testHomeIsAvailableInTheFallbackFeatureEntry() {
        let home = Module.fallbackModules.first { $0.id == "home" }
        XCTAssertEqual(home?.title, "主页")
        XCTAssertEqual(home?.path, "/")
        XCTAssertTrue(home?.sidebarVisible == true)
        XCTAssertFalse(home?.homeVisible == true)
    }

    func testDashboardTestModulesUseFreshWebDestinations() throws {
        for (id, path) in [
            ("ic-test", "/ic-test"),
            ("backtest", "/backtest"),
        ] {
            let module = try module(id: id, path: path)
            let first = ClientTab.module(module)
            let second = ClientTab.module(module)

            XCTAssertNotEqual(first.id, second.id, id)
            XCTAssertTrue(first.isClosable, id)
            guard case let .web(destination) = first.content else {
                return XCTFail("\(id) must use the callback-wired Web tab")
            }
            XCTAssertEqual(destination, path)
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

    func testModuleDecodesResearchChildrenAndBackendTabBehavior() throws {
        let data = #"""
        {
          "id":"research",
          "title":"研究",
          "desc":"研究报告、研究图与研究身份",
          "icon":"chart",
          "sfSymbol":"chart.xyaxis.line",
          "path":"/research?section=shared",
          "requiresAuth":false,
          "roles":[],
          "children":[
            {"id":"research.profiles","title":"研究身份","path":"/research?section=profiles","requiresAuth":true}
          ],
          "sidebarVisible":true,
          "homeVisible":true,
          "pinned":true
        }
        """#.data(using: .utf8)!
        let research = try JSONDecoder().decode(Module.self, from: data)
        XCTAssertEqual(research.children.map(\.id), ["research.profiles"])
        XCTAssertEqual(research.children.first?.path, "/research?section=profiles")

        let newTabData = #"""
        {
          "id":"docs","title":"技术文档","path":"/docs","requiresAuth":false,"roles":[],"tab_behavior":"new"
        }
        """#.data(using: .utf8)!
        let docs = try JSONDecoder().decode(Module.self, from: newTabData)
        XCTAssertEqual(docs.tabBehavior, "new")
        XCTAssertNotEqual(ClientTab.module(docs).id, ClientTab.module(docs).id)
    }

    func testReportObjectsOpenDedicatedWebTabs() {
        let factorRef = "factor:v2:" + String(repeating: "a", count: 43)
        let familyRef = "factor-family:v2:" + String(repeating: "b", count: 43)
        let setRef = "factor-set:v2:" + String(repeating: "c", count: 43)
        let cases: [(String, String, String)] = [
            ("factor", factorRef, "/factors/factor/"),
            ("factor", familyRef, "/factors/family/"),
            ("factor_set", setRef, "/factors/set/"),
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

    func testHyphenatedAndUnderscoredKindsUseTheSameReferenceTemplate() {
        let familyRef = "factor-family:v2:" + String(repeating: "a", count: 43)
        let hyphenated = ClientTab.reference(.init(
            kind: "factor-family",
            targetRef: familyRef,
            label: "动量因子家族"
        ))
        let underscored = ClientTab.reference(.init(
            kind: "factor_family",
            targetRef: familyRef,
            label: "动量因子家族"
        ))

        guard case let .web(hyphenatedPath)? = hyphenated?.content,
              case let .web(underscoredPath)? = underscored?.content else {
            return XCTFail("both spellings must use a Swift-owned Web tab")
        }
        XCTAssertEqual(hyphenatedPath, underscoredPath)
        XCTAssertEqual(hyphenated?.id, underscored?.id)
        XCTAssertEqual(
            ResearchDocumentReferenceCatalog.canonicalKind("factor-family"),
            "factor_family"
        )

        let encoded = familyRef.addingPercentEncoding(
            withAllowedCharacters: .alphanumerics
        )!
        let parsed = ResearchDocumentTypedLinkParser.reference(
            from: URL(string: "factortester://factor-family/\(encoded)")!
        )
        XCTAssertEqual(parsed?.kind, "factor_family")
        XCTAssertEqual(parsed?.targetRef, familyRef)

        let web = ResearchDocumentWebReferenceMessage.decode([
            "href": "https://example.com/research?q=1",
            "label": "外部研究来源",
        ])
        XCTAssertEqual(web?.kind, "url")
        XCTAssertEqual(web?.targetRef, "https://example.com/research?q=1")
        XCTAssertEqual(web?.label, "外部研究来源")
    }

    func testGenericReferenceKindsUseTheSharedSwiftWebTemplate() {
        let cases: [(String, String)] = [
            ("obligation", "obligation:one"),
            ("report_requirement", "report.requirement.factor_semantics"),
            ("entry_requirement", "data.quality_and_continuity"),
            ("obligation_requirement", "data.source_availability"),
            ("trial_plan", "trial-plan:sha256:\(String(repeating: "a", count: 64))"),
            ("run_spec", "runspec:sha256:\(String(repeating: "b", count: 64))"),
            ("run", "run:run-1"),
            ("file", "factortester-local://assets/notes.md"),
        ]

        for (kind, target) in cases {
            let tab = ClientTab.reference(.init(
                kind: kind, targetRef: target, label: "引用 \(kind)"
            ))
            guard case let .web(path)? = tab?.content else {
                return XCTFail("\(kind) must use the shared Swift-owned Web template")
            }
            XCTAssertTrue(tab?.isClosable == true, kind)
            if kind == "trial_plan" || kind == "run_spec" {
                let query = URLComponents(string: path)?.queryItems ?? []
                XCTAssertEqual(query.first(where: { $0.name == "kind" })?.value, kind)
                XCTAssertEqual(query.first(where: { $0.name == "target" })?.value, target)
            } else {
                XCTAssertTrue(path.hasPrefix("/reference?"), path)
            }
        }
    }

    func testProfileRevisionUsesGenericReferenceTemplate() {
        let revision = "profile-revision:v1:maxa:sha256:\(String(repeating: "a", count: 64))"
        let tab = ClientTab.reference(.init(
            kind: "profile_revision",
            targetRef: revision,
            label: "MaxA 配置版本"
        ))
        guard case let .web(path)? = tab?.content else {
            return XCTFail("profile revisions do not have a profile directory route")
        }
        XCTAssertTrue(path.hasPrefix("/reference?"), path)
        XCTAssertFalse(path.hasPrefix("/profiles/"), path)
        let query = URLComponents(string: path)?.queryItems ?? []
        XCTAssertEqual(query.first(where: { $0.name == "kind" })?.value, "profile_revision")
        XCTAssertEqual(query.first(where: { $0.name == "target" })?.value, revision)
    }

    func testJobReferenceCarriesBoundServicePortIntoItsWebTab() {
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "research-job:abc123",
            label: "IC 任务",
            detailFields: [.init(name: "port", value: "8176")]
        )
        guard case let .web(path)? = ClientTab.reference(reference)?.content else {
            return XCTFail("job reference must open a Web tab")
        }
        XCTAssertEqual(path, "/jobs/8176/abc123")
        XCTAssertTrue(ClientTab.reference(reference)?.id.contains(":port:8176") == true)
    }

    func testJobReferenceCarriesBoundServerIntoItsWebTab() {
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "job:abc123",
            label: "回测任务",
            detailFields: [
                .init(name: "server_id", value: "remote-main"),
                .init(name: "port", value: "8176"),
            ]
        )
        guard case let .web(path)? = ClientTab.reference(reference)?.content else {
            return XCTFail("job reference must open a Web tab")
        }
        XCTAssertEqual(path, "/jobs/8176/abc123?server_id=remote-main")
        XCTAssertTrue(ClientTab.reference(reference)?.id.contains(":server:remote-main") == true)
    }

    func testJobReferenceCanRouteByServerIdentityWithoutPort() {
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "job:abc123",
            label: "回测任务",
            detailFields: [.init(name: "server_id", value: "remote-main")]
        )
        guard case let .web(path)? = ClientTab.reference(reference)?.content else {
            return XCTFail("server-only Job reference must open a Web tab")
        }
        XCTAssertEqual(path, "/jobs/abc123?server_id=remote-main")
    }

    func testJobIdentityIsPortScopedButRunSpecIdentityIsContentAddressed() {
        let jobTarget = "research-job:shared"
        let firstJob = ClientTab.reference(.init(
            kind: "job",
            targetRef: jobTarget,
            label: "测试任务",
            detailFields: [.init(name: "port", value: "8141")]
        ))
        let secondJob = ClientTab.reference(.init(
            kind: "job",
            targetRef: jobTarget,
            label: "测试任务",
            detailFields: [.init(name: "port", value: "8142")]
        ))
        let target = "runspec:sha256:\(String(repeating: "b", count: 64))"
        let first = ClientTab.reference(.init(
            kind: "run_spec",
            targetRef: target,
            label: "运行配置",
            detailFields: [.init(name: "port", value: "8141")]
        ))
        let second = ClientTab.reference(.init(
            kind: "run_spec",
            targetRef: target,
            label: "运行配置",
            detailFields: [.init(name: "port", value: "8142")]
        ))

        XCTAssertNotEqual(firstJob?.id, secondJob?.id)
        XCTAssertTrue(firstJob?.id.contains(":port:8141") == true)
        XCTAssertTrue(secondJob?.id.contains(":port:8142") == true)
        XCTAssertEqual(first?.id, second?.id)
        XCTAssertFalse(first?.id.contains(":port:") == true)
        XCTAssertEqual(first?.title, "运行配置")
        let alternatePrefix = ClientTab.reference(.init(
            kind: "run-spec",
            targetRef: target.replacingOccurrences(
                of: "runspec:sha256:", with: "run_spec:sha256:"
            ),
            label: "另一个显示名称"
        ))
        XCTAssertEqual(first?.id, alternatePrefix?.id)
        XCTAssertEqual(alternatePrefix?.title, "运行配置")
        guard case let .web(firstPath)? = first?.content else {
            return XCTFail("RunSpec reference must use a Web tab")
        }
        let reopened = ClientTab.web(
            id: "reopened-run-spec",
            title: "运行配置",
            systemImage: "slider.horizontal.3",
            path: firstPath
        )
        XCTAssertEqual(reopened.servicePort, 8141)
    }

    func testEmbeddedJobInheritsPortWhileRunSpecUsesItsContentIdentity() {
        let job = ClientTab.embeddedNavigationDestination(
            for: "/jobs/8176/job-one"
        )
        let runSpec = ClientTab.embeddedNavigationDestination(
            for: "/reference?kind=run-spec&target=runspec%3Asha256%3Aabc",
            sourceServicePort: 8176
        )

        XCTAssertTrue(job?.id.contains(":port:8176") == true)
        XCTAssertFalse(runSpec?.id.contains(":port:") == true)
        XCTAssertEqual(runSpec?.title, "运行配置")
        guard case let .web(jobPath)? = job?.content,
              case let .web(runSpecPath)? = runSpec?.content else {
            return XCTFail("embedded backend links must create Swift Web tabs")
        }
        XCTAssertEqual(jobPath, "/jobs/8176/job-one")
        XCTAssertTrue(runSpecPath.hasPrefix("/reference?"))
    }

    func testEmbeddedProductAndFactorDestinationsCreateSwiftTabs() {
        let factorRef = String(repeating: "a", count: 43)
        let cases = [
            "/products/group/product-group%3Atiger?source=local",
            "/products/product/JNI.OSE?source=local",
            "/products/contract/JNI2609?source=local",
            "/products/continuous-contract/JNI.OSE?source=local",
            "/factors/family/factor-family%3Amomentum",
            "/factors/factor/factor%3Amomentum",
            "/factors/set/factor-set%3Amomentum",
            "/factor-series?factor_ref=factor%3Av2%3A\(factorRef)&group_ref=product-group%3Atiger",
        ]

        for path in cases {
            guard let destination = ClientTab.embeddedNavigationDestination(
                for: path
            ) else {
                return XCTFail("\(path) must resolve to a Swift tab")
            }
            XCTAssertTrue(destination.isClosable, path)
            guard case .web = destination.content else {
                return XCTFail("\(path) must create a Swift-owned Web tab")
            }
        }
    }

    func testEmbeddedFactorSeriesPreservesFrozenFactorAndProductGroup() {
        let factorRef = String(repeating: "a", count: 43)
        let path = "/factor-series?factor_ref=factor%3Av2%3A\(factorRef)"
            + "&group_ref=product-group%3Atiger&source=local"
        guard let destination = ClientTab.embeddedNavigationDestination(
            for: path
        ) else {
            return XCTFail("factor series must resolve to a Swift tab")
        }
        XCTAssertEqual(destination.title, "查看因子序列")
        guard case let .web(destinationPath) = destination.content else {
            return XCTFail("factor series must remain an embedded Web page")
        }
        XCTAssertEqual(destinationPath, path)
    }

    func testEmbeddedWebReferenceCarriesComponentAndDetailFields() {
        let reference = ResearchDocumentWebReferenceMessage.decode([
            "href": "factortester://job/research-job%3Aabc123",
            "label": "IC 任务",
            "component_id": "result-component",
            "detail_fields": ["port": 8176],
        ])
        XCTAssertEqual(reference?.componentID, "result-component")
        XCTAssertEqual(
            reference?.detailFields.first(where: { $0.name == "port" })?.value,
            "8176"
        )
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

    func testEmbeddedWebFactorNavigationReachesNativeTabBridge() {
        let digest = String(repeating: "a", count: 43)
        let paths = [
            "/factors/family/factor-family%3Av2%3A\(digest)",
            "/factors/factor/factor%3Av2%3A\(digest)",
            "/factors/set/factor-set%3Av2%3A\(digest)",
            "/factor-series?factor_ref=factor%3Av2%3A\(digest)&group_ref=product-group%3Atiger",
        ]
        for path in paths {
            XCTAssertEqual(
                ResearchDocumentWebNavigationMessage.path(from: ["path": path]),
                path
            )
        }
        XCTAssertNil(
            ResearchDocumentWebNavigationMessage.path(from: ["path": "/factors"])
        )
    }

    func testEmbeddedTypedReferenceNavigationReachesNativeTabBridge() {
        let path = "/reference?kind=run-spec&target=runspec%3Asha256%3Aabc"
        XCTAssertEqual(
            ResearchDocumentWebNavigationMessage.path(from: ["path": path]),
            path
        )
        XCTAssertNil(
            ResearchDocumentWebNavigationMessage.path(from: ["path": "/reference"])
        )
    }

    func testFactorDetailBuildsStableNativeTab() {
        let setRef = "factor-set:v2:" + String(repeating: "a", count: 43)
        let tab = ClientTab.factorDetail(
            setRef,
            kind: "set"
        )
        XCTAssertEqual(tab.id, "web:factor-set:\(setRef)")
        XCTAssertEqual(tab.systemImage, "square.stack.3d.up")
        guard case let .web(path) = tab.content else {
            return XCTFail("factor detail must use the shared Web renderer")
        }
        XCTAssertTrue(path.hasPrefix("/factors/set/"))
    }

    func testEmbeddedResearchSectionNavigationUpdatesOnlyLightweightSession() {
        XCTAssertEqual(
            ResearchModuleSection.fromResearchPath("/research?section=graph"),
            .graph
        )
        XCTAssertEqual(
            ResearchModuleSection.fromResearchPath("/research?section=local"),
            .reports
        )
        XCTAssertEqual(
            ResearchModuleSection.fromResearchPath("/research?section=evidence"),
            .evidence
        )
        XCTAssertNil(
            ResearchModuleSection.fromResearchPath("/research/local:report-1")
        )
        XCTAssertNil(
            ResearchModuleSection.fromResearchPath("/jobs/8141/job-1")
        )
        XCTAssertEqual(
            ResearchDocumentWebNavigationMessage.path(from: [
                "path": "/research?section=graph",
            ]),
            "/research?section=graph"
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

    private func module(id: String, path: String) throws -> Module {
        let data = """
        {
          "id": "\(id)",
          "title": "Test",
          "desc": "",
          "icon": "",
          "sfSymbol": "chart.xyaxis.line",
          "path": "\(path)",
          "requiresAuth": true,
          "roles": []
        }
        """.data(using: .utf8)!
        return try JSONDecoder().decode(Module.self, from: data)
    }
}
