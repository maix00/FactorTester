import Foundation

enum LocalProfileLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed
}

@MainActor
final class LocalProfileController: ObservableObject {
    @Published var profiles: [LocalProfileModel] = []
    @Published var isWorking = false
    @Published var loadState: LocalProfileLoadState = .loading
    @Published var error: String?
    @Published var lifecycleReceipt: ProfileLifecycleReceipt?
    let snapshotStore: LocalProfileSnapshotStore
    var localFileFingerprint: String
    var refreshInFlight = false
    var authoritativeLoadCompleted = false
    static var sharedProfileListTask:
        Task<[[String: Any]], Error>?

    init(
        defaults: UserDefaults = .standard,
        profileDirectory: URL? = nil
    ) {
        let store = LocalProfileSnapshotStore(
            defaults: defaults,
            profileDirectory: profileDirectory
        )
        snapshotStore = store
        localFileFingerprint = store.fileFingerprint()
        profiles = store.hydrate().map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
        loadState = profiles.isEmpty ? .loading : .loaded
    }
    var cliPath: String {
        ClientCLIResolution.executable()
    }

}
