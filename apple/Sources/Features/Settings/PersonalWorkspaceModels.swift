import Foundation

struct UserLayoutPaths {
    let userRoot: String
    let personalWorkspace: String
    let factorLibrary: String
    let profilesRoot: String
    let legacyQuarantine: String

    init(json: [String: Any]) {
        userRoot = json.string("user_root")
        personalWorkspace = json.string("personal_workspace")
        factorLibrary = json.string("factor_library")
        profilesRoot = json.string("profiles_root")
        legacyQuarantine = json.string("legacy_quarantine")
    }
}

struct PersonalCanonicalWorkspace {
    let path: String
    let ownerRef: String
    let repositoryRef: String

    init(json: [String: Any], principal: String = "") {
        if !json.string("source").isEmpty {
            path = json.string("source")
        } else if !json.string("target").isEmpty {
            path = json.string("target")
        } else {
            path = json.string("path")
        }
        if !json.string("principal_ref").isEmpty {
            ownerRef = json.string("principal_ref")
        } else if !json.string("owner_ref").isEmpty {
            ownerRef = json.string("owner_ref")
        } else {
            ownerRef = principal
        }
        repositoryRef = json.string("canonical_repo_ref")
    }
}

struct PersonalWorkspaceMigrationPlan {
    let layout: UserLayoutPaths
    let source: String
    let target: String
    let dirtyCount: Int
    let linkedProfiles: [String]
    let linkedWorktrees: [String]
    let legacyQuarantine: [String]
    let ready: Bool
    let preservesBranches: Bool
    let preservesCommits: Bool
    let preservesUncommitted: Bool

    init(json: [String: Any]) {
        layout = UserLayoutPaths(
            json: json["target_layout"] as? [String: Any] ?? [:]
        )
        let canonical = json["canonical"] as? [String: Any] ?? [:]
        source = canonical.string("source")
        target = canonical.string("target")
        dirtyCount = canonical["dirty_file_count"] as? Int ?? 0
        linkedProfiles = (
            json["profiles"] as? [[String: Any]] ?? []
        ).compactMap { $0["profile_id"] as? String }
        linkedWorktrees = (
            json["worktrees"] as? [[String: Any]] ?? []
        ).compactMap { $0["new_path"] as? String }
        legacyQuarantine = (
            json["legacy_quarantine"] as? [[String: Any]] ?? []
        ).compactMap { $0["target"] as? String }
        ready = json.bool("ready") ?? false
        let isMigration =
            json.string("operation") == "principal_user_layout_migration"
        preservesBranches = isMigration
        preservesCommits = isMigration
        preservesUncommitted = isMigration
    }
}

struct PersonalWorkspaceReceipt {
    let id: String
    let status: String
    let receiptRef: String

    init(json: [String: Any]) {
        id = json.string("migration_id")
        status = json.string("status").isEmpty
            ? (json.bool("valid") == true ? "verified" : "invalid")
            : json.string("status")
        receiptRef = json.string("receipt_ref")
    }
}
