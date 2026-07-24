#if os(macOS)
import Foundation
import Sparkle

/// Owns Sparkle's updater while the existing release UI is migrated.
///
/// Feed selection is supplied through the delegate on every request. We do
/// avoid Sparkle's deprecated persisted feed setter because a stale
/// user default could silently move a Main client onto the Beta feed.
@MainActor
final class SparkleUpdateCoordinator: NSObject, SPUUpdaterDelegate {
    private let feedURL: () -> URL?
    private lazy var updaterController = SPUStandardUpdaterController(
        startingUpdater: true,
        updaterDelegate: self,
        userDriverDelegate: nil
    )

    init(feedURL: @escaping () -> URL?) {
        self.feedURL = feedURL
        super.init()
        _ = updaterController
    }

    func feedURLString(for updater: SPUUpdater) -> String? {
        feedURL()?.absoluteString
    }

    func checkForUpdates() {
        updaterController.checkForUpdates(nil)
    }

    func checkForUpdatesInBackground() {
        updaterController.updater.checkForUpdatesInBackground()
    }

    var automaticallyChecksForUpdates: Bool {
        get { updaterController.updater.automaticallyChecksForUpdates }
        set { updaterController.updater.automaticallyChecksForUpdates = newValue }
    }

    var automaticallyDownloadsUpdates: Bool {
        get { updaterController.updater.automaticallyDownloadsUpdates }
        set { updaterController.updater.automaticallyDownloadsUpdates = newValue }
    }
}
#endif
