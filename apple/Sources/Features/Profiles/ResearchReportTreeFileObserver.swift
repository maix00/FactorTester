import Foundation
import Darwin

final class ResearchReportTreeFileObserver: NSObject, ObservableObject,
    NSFilePresenter {
    let presentedItemURL: URL?
    let presentedItemOperationQueue: OperationQueue = .main

    @Published private(set) var revision = 0
    private var observing = false
    private var pendingNotification: DispatchWorkItem?
    private var directorySource: DispatchSourceFileSystemObject?

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
        startDirectoryWatch()
    }

    func stop() {
        guard observing else { return }
        observing = false
        NSFileCoordinator.removeFilePresenter(self)
        directorySource?.cancel()
        directorySource = nil
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

    private func startDirectoryWatch() {
        guard directorySource == nil, let directory = presentedItemURL else { return }
        let descriptor = (try? PersonalWorkspaceAccessStore.withAccess(to: directory) {
            Darwin.open(directory.path, O_EVTONLY)
        }) ?? -1
        guard descriptor >= 0 else { return }
        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .rename, .delete],
            queue: .main
        )
        source.setEventHandler { [weak self] in self?.notify() }
        source.setCancelHandler { Darwin.close(descriptor) }
        directorySource = source
        source.resume()
    }
}
