import Foundation
import Darwin

final class ResearchReportTreeFileObserver: NSObject, ObservableObject,
    NSFilePresenter {
    let presentedItemURL: URL?
    private let headURL: URL?
    let presentedItemOperationQueue: OperationQueue = .main

    @Published private(set) var revision = 0
    private var observing = false
    private var pendingNotification: DispatchWorkItem?
    private var directorySource: DispatchSourceFileSystemObject?
    private var observedGeneration: Int?

    init(localRef: String) {
        if let url = URL(string: localRef), url.isFileURL {
            headURL = url
            presentedItemURL = url.deletingLastPathComponent()
        } else {
            headURL = nil
            presentedItemURL = nil
        }
    }

    func start() {
        guard !observing, presentedItemURL != nil else { return }
        observing = true
        observedGeneration = readGeneration()
        NSFileCoordinator.addFilePresenter(self)
        startDirectoryWatch()
    }

    func stop() {
        guard observing else { return }
        observing = false
        pendingNotification?.cancel()
        pendingNotification = nil
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
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.observing, let headURL = self.headURL else {
                return
            }
            DispatchQueue.global(qos: .utility).async { [weak self] in
                let generation = Self.readGeneration(at: headURL)
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.observing,
                          let generation,
                          generation != self.observedGeneration else { return }
                    self.observedGeneration = generation
                    self.revision &+= 1
                }
            }
        }
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

    private func readGeneration() -> Int? {
        guard let headURL else { return nil }
        return Self.readGeneration(at: headURL)
    }

    private static func readGeneration(at headURL: URL) -> Int? {
        try? PersonalWorkspaceAccessStore.withAccess(to: headURL) {
            let data = try Data(contentsOf: headURL, options: .mappedIfSafe)
            return (try JSONSerialization.jsonObject(with: data)
                    as? [String: Any])?["generation"] as? Int
        }
    }
}
