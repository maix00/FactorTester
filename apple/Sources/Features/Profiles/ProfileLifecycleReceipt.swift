import Foundation

struct ProfileLifecycleReceipt: Identifiable {
    let id = UUID()
    let action: String
    let status: String
    let profileID: String
    let detail: String
    let branchRetained: Bool
    let commitsRetained: Bool
    let receiptRef: String
    let serverSyncStatus: String
    let serverSyncPending: Bool
    let serverSyncReason: String

    init(json: [String: Any], fallbackAction: String) {
        action = json.string("action").isEmpty
            ? fallbackAction : json.string("action")
        status = json.string("status")
        profileID = json.string("profile_id")
        branchRetained = json.bool("branch_retained") ?? true
        commitsRetained = json.bool("commits_retained") ?? true
        receiptRef = json.string("receipt_ref")
        detail = json.string("message")
        let sync = json["control_profile_sync"] as? [String: Any] ?? [:]
        serverSyncStatus = sync.string("status")
        serverSyncPending = json.bool("server_visibility_pending")
            ?? sync.bool("pending")
            ?? false
        serverSyncReason = sync.string("reason")
    }
}
