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

    init(json: [String: Any], fallbackAction: String) {
        action = json.string("action").isEmpty
            ? fallbackAction : json.string("action")
        status = json.string("status")
        profileID = json.string("profile_id")
        branchRetained = json.bool("branch_retained") ?? true
        commitsRetained = json.bool("commits_retained") ?? true
        receiptRef = json.string("receipt_ref")
        detail = json.string("message")
    }
}
