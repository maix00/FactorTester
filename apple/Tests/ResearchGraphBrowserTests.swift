import XCTest
@testable import FTClient

final class ResearchGraphBrowserTests: XCTestCase {
    func testNodeAndEdgeRequirementsResolveFromVersionedCatalog() throws {
        let graph = try JSONDecoder().decode(
            ResearchGraphVersion.self,
            from: Data(Self.graphJSON.utf8)
        )

        XCTAssertEqual(
            graph.requirements(forNode: "factor_semantics").map(\.id),
            ["factor_semantics.expression_validity"]
        )
        XCTAssertEqual(
            graph.requirements(forEdge: "semantics__validation").map(\.id),
            ["trial_validity.sample_partition"]
        )
        XCTAssertEqual(
            graph.requirements(forEdge: "validation__audit").map(\.id),
            ["evidence_integrity.claim_scope"]
        )
        XCTAssertEqual(
            graph.requirements(forEdge: "semantics__validation").first?.categoryTitle,
            "试验有效性"
        )
        XCTAssertEqual(graph.node(id: "factor_semantics")?.kind, "validation")
        XCTAssertEqual(
            graph.edge(id: "semantics__validation")?.toNode,
            "validation_design"
        )
        XCTAssertEqual(
            graph.outgoingEdges(from: "factor_semantics").map(\.id),
            ["semantics__validation"]
        )
    }

    func testVersionListAndActivePointerUseReadOnlyGetRequests() async throws {
        let transport = ResearchGraphTransport(responses: [
            .init(data: Data("{\"success\":true,\"versions\":[\(Self.graphJSON)]}".utf8), statusCode: 200, etag: nil),
            .init(data: Data("{\"success\":true,\"graph\":\(Self.graphJSON)}".utf8), statusCode: 200, etag: nil),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "https://example.test")!,
            transport: transport
        )

        let versions = try await service.researchGraphVersions(
            graphID: "factor-research"
        )
        let active = try await service.activeResearchGraph(
            graphID: "factor-research"
        )

        XCTAssertEqual(versions.map(\.version), [12])
        XCTAssertEqual(active.version, 12)
        XCTAssertEqual(transport.requests.map(\.httpMethod), ["GET", "GET"])
        XCTAssertEqual(
            transport.requests.map { $0.url?.path },
            [
                "/api/catalog/research-graphs/factor-research/versions",
                "/api/catalog/research-graphs/factor-research/active",
            ]
        )
    }

    @MainActor
    func testChoosingVersionChangesOnlyBrowserSelection() async throws {
        let newer = try JSONDecoder().decode(
            ResearchGraphVersion.self,
            from: Data(Self.graphJSON.utf8)
        )
        let older = try JSONDecoder().decode(
            ResearchGraphVersion.self,
            from: Data(
                Self.graphJSON.replacingOccurrences(
                    of: "\"version\":12",
                    with: "\"version\":11"
                ).utf8
            )
        )
        var loadCount = 0
        let endpoint = ResearchGraphEndpoint(
            serverURL: URL(string: "https://example.test")!
        )
        let controller = ResearchGraphBrowserController(
            endpoints: [endpoint]
        ) { _ in
            loadCount += 1
            return ([older, newer], older)
        }

        await controller.refresh()
        XCTAssertEqual(controller.selectedVersion, 11)
        XCTAssertEqual(controller.activeVersion, 11)

        controller.selectVersion(12)

        XCTAssertEqual(controller.selectedVersion, 12)
        XCTAssertEqual(controller.activeVersion, 11)
        XCTAssertEqual(loadCount, 1)
    }

    @MainActor
    func testRefreshRestoresRememberedVersionWhenStillAvailable() async throws {
        let newer = try Self.graph(version: 12)
        let older = try Self.graph(version: 11)
        let endpoint = ResearchGraphEndpoint(
            serverURL: URL(string: "https://example.test")!
        )
        let controller = ResearchGraphBrowserController(
            endpoints: [endpoint],
            initialEndpointID: endpoint.id,
            initialVersion: 12
        ) { _ in ([older, newer], older) }

        await controller.refresh()

        XCTAssertEqual(controller.selectedEndpointID, endpoint.id)
        XCTAssertEqual(controller.selectedVersion, 12)
        XCTAssertEqual(controller.activeVersion, 11)
    }

    @MainActor
    func testVersionNavigationUsesStableOlderAndNewerNeighbors() async throws {
        let newer = try Self.graph(version: 12)
        let older = try Self.graph(version: 11)
        let endpoint = ResearchGraphEndpoint(
            serverURL: URL(string: "https://example.test")!
        )
        let controller = ResearchGraphBrowserController(
            endpoints: [endpoint]
        ) { _ in ([older, newer], older) }

        await controller.refresh()
        XCTAssertEqual(controller.newerVersion, 12)
        XCTAssertNil(controller.olderVersion)

        controller.selectVersion(12)
        XCTAssertNil(controller.newerVersion)
        XCTAssertEqual(controller.olderVersion, 11)
    }

    func testCanvasLayoutPlacesConnectedNodesAndHitTestsEdge() throws {
        let graph = try Self.graph(version: 12)
        let layout = ResearchGraphCanvasLayout(graph: graph)
        let source = try XCTUnwrap(layout.nodeFrames["factor_semantics"])
        let target = try XCTUnwrap(layout.nodeFrames["validation_design"])
        let route = try XCTUnwrap(layout.edgeRoutes["semantics__validation"])

        XCTAssertLessThan(source.maxX, target.minX)
        XCTAssertFalse(source.intersects(target))
        XCTAssertEqual(
            layout.nearestEdge(to: route.point(at: 0.42)),
            "semantics__validation"
        )
    }

    private static func graph(version: Int) throws -> ResearchGraphVersion {
        try JSONDecoder().decode(
            ResearchGraphVersion.self,
            from: Data(
                graphJSON.replacingOccurrences(
                    of: "\"version\":12",
                    with: "\"version\":\(version)"
                ).utf8
            )
        )
    }

    private static let graphJSON = """
    {
      "schema_version":2,
      "graph_id":"factor-research",
      "version":12,
      "lifecycle":"draft",
      "parent_version":11,
      "content_hash":"hhhh",
      "entry_node":"factor_semantics",
      "nodes":[
        {
          "node_id":"factor_semantics",
          "kind":"validation",
          "purpose":"Validate factor meaning.",
          "entry_requirement_refs":["factor_semantics.expression_validity"],
          "entry_report_refs":[],
          "node_report_refs":[]
        },
        {
          "node_id":"validation_design",
          "kind":"validation",
          "purpose":"Freeze validation design.",
          "entry_requirement_refs":[],
          "entry_report_refs":[],
          "node_report_refs":[]
        }
      ],
      "edges":[
        {
          "edge_id":"semantics__validation",
          "edge_type":"conditional",
          "from_node":"factor_semantics",
          "to_node":"validation_design",
          "obligation_requirement_refs":["trial_validity.sample_partition"],
          "report_requirement_refs":[]
        },
        {
          "edge_id":"validation__audit",
          "edge_type":"conditional",
          "from_node":"validation_design",
          "to_node":"result_audit",
          "obligation_requirement_refs":[],
          "report_requirement_refs":["report.edge.validation__audit"]
        }
      ],
      "requirement_catalog":{
        "catalog_revision":4,
        "categories":[
          {"category_id":"factor_semantics","title_zh":"因子语义","description_zh":""},
          {"category_id":"trial_validity","title_zh":"试验有效性","description_zh":""},
          {"category_id":"evidence_integrity","title_zh":"证据完整性","description_zh":""}
        ],
        "requirements":[
          {"requirement_id":"factor_semantics.expression_validity","category_id":"factor_semantics","revision":2,"title_zh":"表达式有效性","question_zh":"表达式是否实现了机制？"},
          {"requirement_id":"trial_validity.sample_partition","category_id":"trial_validity","revision":3,"title_zh":"样本分割","question_zh":"选择样本和留出样本是否分离？"},
          {"requirement_id":"evidence_integrity.claim_scope","category_id":"evidence_integrity","revision":1,"title_zh":"主张范围","question_zh":"证据支持哪一范围的主张？"}
        ]
      },
      "report_requirements":[
        {"report_requirement_id":"report.edge.validation__audit","anchor_kind":"edge","anchor_ref":"validation__audit","requirement_ref":"evidence_integrity.claim_scope","title_zh":"审计主张范围"}
      ]
    }
    """
}

private final class ResearchGraphTransport: ProfileResearchTransport {
    private var responses: [ResearchHTTPResponse]
    private(set) var requests: [URLRequest] = []

    init(responses: [ResearchHTTPResponse]) {
        self.responses = responses
    }

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        requests.append(request)
        return responses.removeFirst()
    }

    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}
