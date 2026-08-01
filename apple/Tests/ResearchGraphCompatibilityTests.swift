import XCTest
@testable import FTClient

final class ResearchGraphCompatibilityTests: XCTestCase {
    func testSchemaOneVersionWithoutCatalogStillDisplaysTopology() throws {
        let graph = try JSONDecoder().decode(
            ResearchGraphVersion.self,
            from: Data(
                """
                {
                  "schema_version":1,
                  "graph_id":"factor-research",
                  "version":4,
                  "lifecycle":"draft",
                  "parent_version":3,
                  "content_hash":"hhhh",
                  "entry_node":"hypothesis",
                  "nodes":[
                    {"node_id":"hypothesis","kind":"research","purpose":""},
                    {"node_id":"validation","kind":"validation","purpose":""}
                  ],
                  "edges":[
                    {"edge_id":"hypothesis__validation","edge_type":"conditional","from_node":"hypothesis","to_node":"validation"}
                  ]
                }
                """.utf8
            )
        )

        XCTAssertEqual(graph.nodes.map(\.id), ["hypothesis", "validation"])
        XCTAssertEqual(graph.edges.map(\.id), ["hypothesis__validation"])
        XCTAssertTrue(graph.requirements(forNode: "hypothesis").isEmpty)
        XCTAssertTrue(
            graph.requirements(forEdge: "hypothesis__validation").isEmpty
        )
    }
}
