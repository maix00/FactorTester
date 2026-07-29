#if os(macOS)
import Foundation
import Sparkle

enum SparkleUpdateEvent {
    case checking
    case found(version: String)
    case downloading(version: String)
    case ready(version: String)
    case current
    case failed(String)
}

/// Thin product-facing adapter. Sparkle owns network verification, extraction,
/// installation, rollback-on-failure, termination, and relaunch.
@MainActor
final class SparkleUpdateCoordinator: NSObject, SPUUpdaterDelegate {
    private let feedURL: () -> URL?
    private let channel: () -> String
    private let event: (SparkleUpdateEvent) -> Void
    private lazy var userDriver = SparkleUpdateUserDriver(event: event)
    private lazy var updater = SPUUpdater(
        hostBundle: .main,
        applicationBundle: .main,
        userDriver: userDriver,
        delegate: self
    )

    init(
        feedURL: @escaping () -> URL?,
        channel: @escaping () -> String,
        event: @escaping (SparkleUpdateEvent) -> Void
    ) {
        self.feedURL = feedURL
        self.channel = channel
        self.event = event
        super.init()
        do {
            try updater.start()
        } catch {
            event(.failed(error.localizedDescription))
        }
    }

    func feedURLString(for updater: SPUUpdater) -> String? {
        feedURL()?.absoluteString
    }

    func allowedChannels(for updater: SPUUpdater) -> Set<String> {
        channel() == "beta" ? ["beta"] : []
    }

    func checkForUpdates() {
        event(.checking)
        updater.checkForUpdates()
    }

    func checkForUpdatesInBackground() {
        event(.checking)
        updater.checkForUpdatesInBackground()
    }

    func downloadAvailableUpdate() {
        userDriver.downloadAvailableUpdate()
    }

    func installAndRelaunch() {
        userDriver.installAndRelaunch()
    }

    var automaticallyChecksForUpdates: Bool {
        get { updater.automaticallyChecksForUpdates }
        set { updater.automaticallyChecksForUpdates = newValue }
    }

    var automaticallyDownloadsUpdates: Bool {
        get { updater.automaticallyDownloadsUpdates }
        set { updater.automaticallyDownloadsUpdates = newValue }
    }
}

@MainActor
private final class SparkleUpdateUserDriver: NSObject, SPUUserDriver {
    private let event: (SparkleUpdateEvent) -> Void
    private var version = ""
    private var downloadReply: ((SPUUserUpdateChoice) -> Void)?
    private var installReply: ((SPUUserUpdateChoice) -> Void)?

    init(event: @escaping (SparkleUpdateEvent) -> Void) {
        self.event = event
    }

    func show(
        _ request: SPUUpdatePermissionRequest,
        reply: @escaping (SUUpdatePermissionResponse) -> Void
    ) {
        reply(SUUpdatePermissionResponse(
            automaticUpdateChecks: true,
            automaticUpdateDownloading: false,
            sendSystemProfile: false
        ))
    }

    func showUserInitiatedUpdateCheck(
        cancellation: @escaping () -> Void
    ) {
        event(.checking)
    }

    func showUpdateFound(
        with appcastItem: SUAppcastItem,
        state: SPUUserUpdateState,
        reply: @escaping (SPUUserUpdateChoice) -> Void
    ) {
        version = appcastItem.displayVersionString
        if state.stage == .downloaded {
            downloadReply = reply
            reply(.install)
        } else if state.stage == .installing {
            installReply = reply
            event(.ready(version: version))
        } else {
            downloadReply = reply
            event(.found(version: version))
        }
    }

    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {}

    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: Error) {}

    func showUpdateNotFoundWithError(
        _ error: Error,
        acknowledgement: @escaping () -> Void
    ) {
        event(.current)
        acknowledgement()
    }

    func showUpdaterError(
        _ error: Error,
        acknowledgement: @escaping () -> Void
    ) {
        event(.failed(error.localizedDescription))
        acknowledgement()
    }

    func showDownloadInitiated(cancellation: @escaping () -> Void) {
        event(.downloading(version: version))
    }

    func showDownloadDidReceiveExpectedContentLength(
        _ expectedContentLength: UInt64
    ) {}

    func showDownloadDidReceiveData(ofLength length: UInt64) {}

    func showDownloadDidStartExtractingUpdate() {}

    func showExtractionReceivedProgress(_ progress: Double) {}

    func showReady(
        toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void
    ) {
        installReply = reply
        event(.ready(version: version))
    }

    func showInstallingUpdate(
        withApplicationTerminated applicationTerminated: Bool,
        retryTerminatingApplication: @escaping () -> Void
    ) {}

    func showUpdateInstalledAndRelaunched(
        _ relaunched: Bool,
        acknowledgement: @escaping () -> Void
    ) {
        acknowledgement()
    }

    func dismissUpdateInstallation() {
        downloadReply = nil
        installReply = nil
    }

    func showUpdateInFocus() {
        // The client renders update state in Settings instead of presenting
        // Sparkle's modal UI. This callback is still required when an update
        // check arrives while the existing update choice is open.
    }

    func downloadAvailableUpdate() {
        let reply = downloadReply
        downloadReply = nil
        reply?(.install)
    }

    func installAndRelaunch() {
        let reply = installReply
        installReply = nil
        reply?(.install)
    }
}
#endif
