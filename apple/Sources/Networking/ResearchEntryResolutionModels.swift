import Foundation

struct ResearchEntryResolutionDelta: Decodable {
    let reason: String
    let assessedRequirementIDs: [String]
    let reusedRequirementIDs: [String]
    let referenceOnlyRequirementIDs: [String]
    let unresolvedRequirementIDs: [String]
    let items: [ResearchEntryRequirementItem]
    let resumeNode: String

    enum CodingKeys: String, CodingKey {
        case reason
        case assessedRequirementIDs = "assessed_requirement_ids"
        case reusedRequirementIDs = "reused_requirement_ids"
        case referenceOnlyRequirementIDs = "reference_only_requirement_ids"
        case unresolvedRequirementIDs = "unresolved_requirement_ids"
        case items
        case resumeNode = "resume_node"
    }
}

struct ResearchEntryRequirementItem: Decodable, Identifiable {
    let requirementID: String
    let titleZh: String
    let assessed: Bool
    let changeKind: String
    let resolutionStatus: String

    var id: String { requirementID }

    enum CodingKeys: String, CodingKey {
        case requirementID = "requirement_id"
        case titleZh = "title_zh"
        case assessed
        case changeKind = "change_kind"
        case resolutionStatus = "resolution_status"
    }
}
