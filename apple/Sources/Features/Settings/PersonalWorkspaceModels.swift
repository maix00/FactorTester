import Foundation

struct PersonalCanonicalWorkspace {
    let path: String
    let ownerRef: String
    let repositoryRef: String

    init(json: [String: Any]) {
        path = json.string("source").isEmpty
            ? json.string("path") : json.string("source")
        ownerRef = json.string("principal_ref").isEmpty
            ? json.string("owner_ref") : json.string("principal_ref")
        repositoryRef = json.string("canonical_repo_ref")
    }
}

struct PersonalWorkspaceMigrationPlan {
    let source: String
    let target: String
    let dirtyCount: Int
    let linkedProfiles: [String]
    let linkedWorktrees: [String]
    let ready: Bool
    let preservesBranches: Bool
    let preservesCommits: Bool
    let preservesUncommitted: Bool

    init(json: [String: Any]) {
        source = json.string("source")
        target = json.string("target")
        dirtyCount = json["dirty_file_count"] as? Int ?? 0
        linkedProfiles = (
            json["linked_profiles"] as? [[String: Any]] ?? []
        ).compactMap { $0["profile_id"] as? String }
        linkedWorktrees = (
            json["worktrees"] as? [[String: Any]] ?? []
        ).compactMap { $0["path"] as? String }
        ready = json.bool("ready") ?? false
        // These are guarantees of the personal-workspace migration contract.
        preservesBranches =
            json.string("operation") == "personal_factor_workspace_migration"
        preservesCommits = preservesBranches
        preservesUncommitted = preservesBranches
    }
}

struct PersonalWorkspaceReceipt {
    let id: String
    let status: String
    let receiptRef: String

    init(json: [String: Any]) {
        id = json.string("migration_id")
        status = json.string("status")
        receiptRef = json.string("receipt_ref")
    }
}
