import Foundation

struct ProfileResearchListResponse: Decodable {
    let schemaVersion: Int
    let workspaceRef: String
    let items: [ProfileResearchSummary]
    let nextCursor: String?
    let etag: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case workspaceRef = "workspace_ref"
        case items
        case nextCursor = "next_cursor"
        case etag
    }
}

struct ProfileResearchSummary: Decodable, Identifiable {
    let researchRef: String
    let label: String
    let currentNode: String
    let status: String
    let trialPlanRef: String?
    let latestTraceRef: String?
    let updatedAt: String?
    let detailHref: String
    let reportLookupRef: String?

    var id: String { researchRef }

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case label
        case currentNode = "current_node"
        case status
        case trialPlanRef = "trial_plan_ref"
        case latestTraceRef = "latest_trace_ref"
        case updatedAt = "updated_at"
        case detailHref = "detail_href"
        case reportLookupRef = "report_lookup_ref"
    }
}
