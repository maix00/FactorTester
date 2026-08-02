import Foundation
import Darwin

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
    private var directoryObserver: LocalProfileDirectoryObserver?
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
        directoryObserver = LocalProfileDirectoryObserver(
            directory: store.directoryURL
        ) { [weak self] in
            self?.reloadLocalFilesIfChanged()
        }
        directoryObserver?.start()
    }
    var cliPath: String {
        ClientCLIResolution.executable()
    }

}

private final class LocalProfileDirectoryObserver {
    private let directory: URL
    private let onChange: () -> Void
    private var source: DispatchSourceFileSystemObject?
    private var pendingNotification: DispatchWorkItem?

    init(directory: URL, onChange: @escaping () -> Void) {
        self.directory = directory
        self.onChange = onChange
    }

    func start() {
        guard source == nil else { return }
        let descriptor = Darwin.open(directory.path, O_EVTONLY)
        guard descriptor >= 0 else { return }
        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .rename, .delete],
            queue: .main
        )
        source.setEventHandler { [weak self] in self?.notify() }
        source.setCancelHandler { Darwin.close(descriptor) }
        self.source = source
        source.resume()
    }

    private func notify() {
        pendingNotification?.cancel()
        let notification = DispatchWorkItem { [weak self] in
            self?.onChange()
        }
        pendingNotification = notification
        DispatchQueue.main.asyncAfter(
            deadline: .now() + .milliseconds(120),
            execute: notification
        )
    }

    deinit {
        pendingNotification?.cancel()
        source?.cancel()
    }
}
