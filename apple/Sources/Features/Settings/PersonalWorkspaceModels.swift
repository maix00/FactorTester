import Foundation

struct PersonalCanonicalWorkspace {
    let path: String
    let ownerRef: String
    let repositoryRef: String

    init(json: [String: Any], principal: String = "") {
        path = json.string("path")
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
