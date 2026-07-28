import Foundation

final class ResearchReportTreeFileObserver: NSObject, ObservableObject,
    NSFilePresenter {
    let presentedItemURL: URL?
    let presentedItemOperationQueue: OperationQueue = .main

    @Published private(set) var revision = 0
    private var observing = false

    init(localRef: String) {
        presentedItemURL = URL(string: localRef)?.isFileURL == true
            ? URL(string: localRef)?.deletingLastPathComponent() : nil
    }

    func start() {
        guard !observing, presentedItemURL != nil else { return }
        observing = true
        NSFileCoordinator.addFilePresenter(self)
    }

    func stop() {
        guard observing else { return }
        observing = false
        NSFileCoordinator.removeFilePresenter(self)
    }

    func presentedItemDidChange() { notify() }
    func presentedSubitemDidChange(at _: URL) { notify() }
    deinit { stop() }

    private func notify() {
        DispatchQueue.main.async { [weak self] in self?.revision &+= 1 }
    }
}
