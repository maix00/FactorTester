import Foundation

final class ResearchReportTreeFileObserver: NSObject, ObservableObject,
    NSFilePresenter {
    let presentedItemURL: URL?
    let presentedItemOperationQueue: OperationQueue = .main

    @Published private(set) var revision = 0
    private var observing = false
    private var pendingNotification: DispatchWorkItem?

    init(localRef: String) {
        if let url = URL(string: localRef), url.isFileURL {
            presentedItemURL = url.deletingLastPathComponent()
        } else {
            presentedItemURL = nil
        }
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
    func presentedSubitemDidAppear(at _: URL) { notify() }
    func presentedSubitem(at _: URL, didMoveTo _: URL) { notify() }
    deinit {
        pendingNotification?.cancel()
        stop()
    }

    private func notify() {
        pendingNotification?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.revision &+= 1 }
        pendingNotification = work
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(120), execute: work)
    }
}
