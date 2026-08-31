import Foundation

struct ResearchCatalogAccess: Decodable, Equatable {
    let canView: Bool
    let canPreview: Bool
    let canDownload: Bool
    let canManage: Bool
    let accessBasis: String

    enum CodingKeys: String, CodingKey {
        case canView = "can_view"
        case canPreview = "can_preview"
        case canDownload = "can_download"
        case canManage = "can_manage"
        case accessBasis = "access_basis"
    }
}

struct ResearchCatalogItem: Decodable, Equatable {
    let researchID: String
    let ownerRef: String
    let title: String
    let description: String
    let status: String
    let visibility: String
    let authorizedUsers: [String]
    let access: ResearchCatalogAccess

    enum CodingKeys: String, CodingKey {
        case researchID = "research_id"
        case ownerRef = "owner_ref"
        case title, description, status, visibility, access
        case authorizedUsers = "authorized_users"
    }
}

struct ResearchCatalogMembership: Decodable, Equatable {
    let researchID: String
    let principalRef: String
    let profileRef: String
    let role: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case researchID = "research_id"
        case principalRef = "principal_ref"
        case profileRef = "profile_ref"
        case role, status
    }
}

struct ResearchCatalogWorkspace: Decodable, Equatable {
    let workspaceID: String
    let researchID: String
    let principalRef: String
    let profileRef: String
    let title: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case researchID = "research_id"
        case principalRef = "principal_ref"
        case profileRef = "profile_ref"
        case title, status
    }
}

struct ResearchCatalogReport: Decodable, Equatable {
    let reportID: String
    let researchID: String
    let ownerRef: String
    let title: String
    let profileRef: String
    let workspaceID: String
    let buildSource: String
    let visibility: String
    let access: ResearchCatalogAccess

    enum CodingKeys: String, CodingKey {
        case reportID = "report_id"
        case researchID = "research_id"
        case ownerRef = "owner_ref"
        case title
        case profileRef = "profile_ref"
        case workspaceID = "workspace_id"
        case buildSource = "build_source"
        case visibility, access
    }
}

struct ResearchCatalogDetail: Decodable, Equatable {
    let researchID: String
    let ownerRef: String
    let title: String
    let description: String
    let status: String
    let visibility: String
    let authorizedUsers: [String]
    let access: ResearchCatalogAccess
    let members: [ResearchCatalogMembership]
    let workspaces: [ResearchCatalogWorkspace]
    let reports: [ResearchCatalogReport]

    enum CodingKeys: String, CodingKey {
        case researchID = "research_id"
        case ownerRef = "owner_ref"
        case title, description, status, visibility, access
        case authorizedUsers = "authorized_users"
        case members, workspaces, reports
    }
}

struct ResearchCatalogListEnvelope: Decodable {
    let researches: [ResearchCatalogItem]
}

struct ResearchCatalogDetailEnvelope: Decodable {
    let research: ResearchCatalogDetail
}

struct ResearchCatalogCreateEnvelope: Decodable {
    let research: ResearchCatalogItem
}

struct ResearchCatalogMemberEnvelope: Decodable {
    let member: ResearchCatalogMembership
}

struct ResearchCatalogWorkspaceEnvelope: Decodable {
    let workspace: ResearchCatalogWorkspace
}

struct ResearchCatalogReportEnvelope: Decodable {
    let report: ResearchCatalogReport
}
