import Foundation

struct ResearchGraphVersion: Decodable, Identifiable {
    let schemaVersion: Int
    let graphID: String
    let version: Int
    let lifecycle: String
    let parentVersion: Int
    let contentHash: String
    let entryNode: String
    let nodes: [ResearchGraphNode]
    let edges: [ResearchGraphEdge]
    let requirementCatalog: ResearchGraphRequirementCatalog
    let reportRequirements: [ResearchGraphReportRequirement]

    private let edgesBySource: [String: [ResearchGraphEdge]]
    private let nodeByID: [String: ResearchGraphNode]
    private let edgeByID: [String: ResearchGraphEdge]
    private let requirementByID: [String: ResearchGraphRequirementDescriptor]
    private let categoryByID: [String: ResearchGraphRequirementCategory]
    private let requirementsByNode: [String: [ResearchGraphRequirement]]
    private let requirementsByEdge: [String: [ResearchGraphRequirement]]

    var id: String { "\(graphID)@v\(version)" }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case graphID = "graph_id"
        case version
        case lifecycle
        case parentVersion = "parent_version"
        case contentHash = "content_hash"
        case entryNode = "entry_node"
        case nodes
        case edges
        case requirementCatalog = "requirement_catalog"
        case reportRequirements = "report_requirements"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decodeIfPresent(
            Int.self,
            forKey: .schemaVersion
        ) ?? 1
        graphID = try values.decode(String.self, forKey: .graphID)
        version = try values.decode(Int.self, forKey: .version)
        lifecycle = try values.decodeIfPresent(
            String.self,
            forKey: .lifecycle
        ) ?? ""
        parentVersion = try values.decodeIfPresent(
            Int.self,
            forKey: .parentVersion
        ) ?? 0
        contentHash = try values.decodeIfPresent(
            String.self,
            forKey: .contentHash
        ) ?? ""
        entryNode = try values.decodeIfPresent(
            String.self,
            forKey: .entryNode
        ) ?? ""
        let decodedNodes = try values.decodeIfPresent(
            [ResearchGraphNode].self,
            forKey: .nodes
        ) ?? []
        let decodedEdges = try values.decodeIfPresent(
            [ResearchGraphEdge].self,
            forKey: .edges
        ) ?? []
        let decodedCatalog = try values.decodeIfPresent(
            ResearchGraphRequirementCatalog.self,
            forKey: .requirementCatalog
        ) ?? ResearchGraphRequirementCatalog()
        let decodedReportRequirements = try values.decodeIfPresent(
            [ResearchGraphReportRequirement].self,
            forKey: .reportRequirements
        ) ?? []

        nodes = decodedNodes
        edges = decodedEdges
        requirementCatalog = decodedCatalog
        reportRequirements = decodedReportRequirements

        let decodedRequirementByID = Self.index(decodedCatalog.requirements)
        let decodedCategoryByID = Self.index(decodedCatalog.categories)
        nodeByID = Self.index(decodedNodes)
        edgeByID = Self.index(decodedEdges)
        edgesBySource = Dictionary(grouping: decodedEdges, by: \.fromNode)
        requirementByID = decodedRequirementByID
        categoryByID = decodedCategoryByID

        var requirementReferenceByReportID: [String: String] = [:]
        for report in decodedReportRequirements {
            requirementReferenceByReportID[report.id] = report.requirementRef
        }
        var decodedRequirementsByNode: [String: [ResearchGraphRequirement]] = [:]
        for node in decodedNodes {
            let inherited = (node.entryReportRefs + node.nodeReportRefs)
                .compactMap { requirementReferenceByReportID[$0] }
            decodedRequirementsByNode[node.id] = Self.resolveRequirements(
                node.entryRequirementRefs + inherited,
                requirements: decodedRequirementByID,
                categories: decodedCategoryByID
            )
        }
        requirementsByNode = decodedRequirementsByNode

        var decodedRequirementsByEdge: [String: [ResearchGraphRequirement]] = [:]
        for edge in decodedEdges {
            let inherited = edge.reportRequirementRefs.compactMap {
                requirementReferenceByReportID[$0]
            }
            decodedRequirementsByEdge[edge.id] = Self.resolveRequirements(
                edge.obligationRequirementRefs + inherited,
                requirements: decodedRequirementByID,
                categories: decodedCategoryByID
            )
        }
        requirementsByEdge = decodedRequirementsByEdge
    }

    func requirements(forNode nodeID: String) -> [ResearchGraphRequirement] {
        requirementsByNode[nodeID] ?? []
    }

    func requirements(forEdge edgeID: String) -> [ResearchGraphRequirement] {
        requirementsByEdge[edgeID] ?? []
    }

    func node(id nodeID: String) -> ResearchGraphNode? {
        nodeByID[nodeID]
    }

    func edge(id edgeID: String) -> ResearchGraphEdge? {
        edgeByID[edgeID]
    }

    func outgoingEdges(from nodeID: String) -> [ResearchGraphEdge] {
        edgesBySource[nodeID] ?? []
    }

    private static func index<Element: Identifiable>(
        _ values: [Element]
    ) -> [Element.ID: Element] {
        var result: [Element.ID: Element] = [:]
        for value in values {
            result[value.id] = value
        }
        return result
    }

    private static func resolveRequirements(
        _ references: [String],
        requirements: [String: ResearchGraphRequirementDescriptor],
        categories: [String: ResearchGraphRequirementCategory]
    ) -> [ResearchGraphRequirement] {
        var seen: Set<String> = []
        return references.compactMap { rawReference in
            let reference = rawReference.replacingOccurrences(
                of: "requirement:",
                with: ""
            )
            guard seen.insert(reference).inserted,
                  let descriptor = requirements[reference] else {
                return nil
            }
            return ResearchGraphRequirement(
                descriptor: descriptor,
                categoryTitle: categories[descriptor.categoryID]?.titleZh
                    ?? descriptor.categoryID
            )
        }
    }
}

struct ResearchGraphNode: Decodable, Identifiable {
    let id: String
    let kind: String
    let purpose: String
    let entryRequirementRefs: [String]
    let entryReportRefs: [String]
    let nodeReportRefs: [String]

    enum CodingKeys: String, CodingKey {
        case id = "node_id"
        case kind
        case purpose
        case entryRequirementRefs = "entry_requirement_refs"
        case entryReportRefs = "entry_report_refs"
        case nodeReportRefs = "node_report_refs"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        kind = try values.decodeIfPresent(String.self, forKey: .kind) ?? ""
        purpose = try values.decodeIfPresent(
            String.self,
            forKey: .purpose
        ) ?? ""
        entryRequirementRefs = try values.decodeIfPresent(
            [String].self,
            forKey: .entryRequirementRefs
        ) ?? []
        entryReportRefs = try values.decodeIfPresent(
            [String].self,
            forKey: .entryReportRefs
        ) ?? []
        nodeReportRefs = try values.decodeIfPresent(
            [String].self,
            forKey: .nodeReportRefs
        ) ?? []
    }
}

struct ResearchGraphEdge: Decodable, Identifiable {
    let id: String
    let type: String
    let fromNode: String
    let toNode: String
    let obligationRequirementRefs: [String]
    let reportRequirementRefs: [String]

    enum CodingKeys: String, CodingKey {
        case id = "edge_id"
        case type = "edge_type"
        case fromNode = "from_node"
        case toNode = "to_node"
        case obligationRequirementRefs = "obligation_requirement_refs"
        case reportRequirementRefs = "report_requirement_refs"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        type = try values.decodeIfPresent(String.self, forKey: .type) ?? ""
        fromNode = try values.decodeIfPresent(
            String.self,
            forKey: .fromNode
        ) ?? ""
        toNode = try values.decodeIfPresent(
            String.self,
            forKey: .toNode
        ) ?? ""
        obligationRequirementRefs = try values.decodeIfPresent(
            [String].self,
            forKey: .obligationRequirementRefs
        ) ?? []
        reportRequirementRefs = try values.decodeIfPresent(
            [String].self,
            forKey: .reportRequirementRefs
        ) ?? []
    }
}

struct ResearchGraphReportRequirement: Decodable, Identifiable {
    let id: String
    let anchorKind: String
    let anchorRef: String
    let requirementRef: String?
    let titleZh: String

    enum CodingKeys: String, CodingKey {
        case id = "report_requirement_id"
        case anchorKind = "anchor_kind"
        case anchorRef = "anchor_ref"
        case requirementRef = "requirement_ref"
        case titleZh = "title_zh"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        anchorKind = try values.decodeIfPresent(
            String.self,
            forKey: .anchorKind
        ) ?? ""
        anchorRef = try values.decodeIfPresent(
            String.self,
            forKey: .anchorRef
        ) ?? ""
        requirementRef = try values.decodeIfPresent(
            String.self,
            forKey: .requirementRef
        )
        titleZh = try values.decodeIfPresent(
            String.self,
            forKey: .titleZh
        ) ?? id
    }
}
