import Foundation

struct CanonicalFactorLibraryState {
    let root: String
    let gitHead: String
    let branch: String
    let dirty: Bool
    let customCount: Int
    let publicCount: Int
    let source: String

    init(json: [String: Any], source: String) {
        root = json.string("workspace_root")
        gitHead = json.string("git_head")
        branch = json.string("git_current_branch")
        dirty = json["git_dirty"] as? Bool ?? false
        customCount = json["custom_factor_count"] as? Int ??
            Self.countFiles(json, kind: "custom")
        publicCount = json["public_factor_count"] as? Int ??
            Self.countFiles(json, kind: "public")
        self.source = source
    }

    private static func countFiles(_ json: [String: Any], kind: String) -> Int {
        let prefix = kind == "custom" ? "custom_factors/" : "public_factors/"
        return (json["files"] as? [[String: Any]] ?? []).filter {
            ($0["path"] as? String)?.hasPrefix(prefix) == true
        }.count
    }
}
