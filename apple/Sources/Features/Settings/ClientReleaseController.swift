import AppKit
import Combine
import Foundation

@MainActor
final class ClientReleaseController: ObservableObject {
    @Published private(set) var installedVersion =
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
    @Published private(set) var latestVersion = ""
    @Published private(set) var compatible: Bool?
    @Published private(set) var healthy: Bool?
    @Published private(set) var signatureText = L10n.text("检查中…")
    @Published private(set) var canRollback = false
    @Published private(set) var isWorking = false
    @Published private(set) var lastChecked: Date?
    @Published private(set) var pendingUpdate: PendingApplicationUpdate?
    @Published private(set) var sparkleUpdateReady = false
    @Published var lastError: String?
    @Published var channel: String {
        didSet { defaults.set(channel, forKey: Keys.channel) }
    }
    @Published var automaticallyUpdates: Bool {
        didSet {
            defaults.set(automaticallyUpdates, forKey: Keys.automatic)
            sparkle.automaticallyChecksForUpdates = true
            sparkle.automaticallyDownloadsUpdates = automaticallyUpdates
        }
    }

    private let store = AppUpdateStore()
    private let defaults: UserDefaults
    private lazy var sparkle = SparkleUpdateCoordinator(
        feedURL: { [weak self] in self?.sparkleFeedURL },
        event: { [weak self] event in self?.handleSparkle(event) }
    )

    init(
        defaults: UserDefaults = .standard
    ) {
        self.defaults = defaults
        channel = defaults.string(forKey: Keys.channel) ?? "stable"
        automaticallyUpdates = defaults.object(forKey: Keys.automatic) as? Bool ?? false
        lastChecked = defaults.object(forKey: Keys.lastChecked) as? Date
        let pending = store.loadPendingApplication()
        if pending?.version == installedVersion {
            store.clearPendingApplication()
            pendingUpdate = nil
        } else {
            pendingUpdate = pending
        }
        sparkle.automaticallyChecksForUpdates = true
        sparkle.automaticallyDownloadsUpdates = automaticallyUpdates
    }

    func refresh(force: Bool = true) async {
        if !force, !shouldCheckAtLaunch { return }
        let signature = await AppSignatureStatus.inspect()
        signatureText = signature.acceptedByGatekeeper
            ? L10n.text("Developer ID 已签名并通过 Gatekeeper")
            : (signature.signed ? L10n.text("已签名，但未通过 Gatekeeper")
                               : L10n.text("未签名开发版本"))
        healthy = signature.signed
        sparkle.checkForUpdates()
    }

    func checkAtLaunch() async {
        guard shouldCheckAtLaunch else { return }
        sparkle.checkForUpdatesInBackground()
    }

    var hasAvailableUpdate: Bool {
        !latestVersion.isEmpty && !sparkleUpdateReady
    }

    func update() async {
        sparkle.downloadAvailableUpdate()
    }

    func restartToApply() async {
        if sparkleUpdateReady {
            sparkle.installAndRelaunch()
            return
        }
        guard let pendingUpdate else {
            lastError = L10n.text("当前没有已准备好的更新。")
            return
        }
        do {
            try PendingApplicationUpdater.launch(
                pending: pendingUpdate,
                currentBundle: Bundle.main.bundleURL
            )
        } catch {
            lastError = error.localizedDescription
        }
    }

    func rollback() async {
        guard let installer = store.previousInstaller(
            excluding: [installedVersion, latestVersion]
        ) else {
            lastError = L10n.text("没有可用的上一版已验证 DMG。")
            return
        }
        do {
            let inspection = try await AppInstallerInspector.inspect(installer)
            guard inspection.bundleID == "com.gtht.client" else {
                throw AppUpdateError.bundleIdentityMismatch
            }
            let staged = self.store.root
                .appendingPathComponent("pending")
                .appendingPathComponent(inspection.version)
                .appendingPathComponent("FTClient.app")
            let stagedApp = try await AppInstallerInspector.stage(
                installer,
                at: staged,
                expected: inspection
            )
            pendingUpdate = try store.savePendingApplication(
                version: inspection.version,
                build: inspection.build,
                channel: "rollback",
                appURL: stagedApp,
                sha256: try AppUpdateStore.sha256(installer)
            )
            lastError = L10n.text(
                "上一版已准备好。请点击‘重启更新’完成回滚。"
            )
        } catch {
            lastError = error.localizedDescription
        }
    }

    private var shouldCheckAtLaunch: Bool {
        guard let lastChecked else { return true }
        return Date().timeIntervalSince(lastChecked) >= 6 * 60 * 60
    }

    var isUpdateReady: Bool {
        sparkleUpdateReady || pendingUpdate != nil
    }

    var pendingVersion: String? {
        sparkleUpdateReady ? latestVersion : pendingUpdate?.version
    }

    private var sparkleFeedURL: URL? {
        if channel == "beta" {
            return ServerConfig.shared.url(
                forPath: "/api/client/releases/beta.xml"
            )
        }
        return URL(
            string: "https://github.com/maix00/FactorTester-Client/releases/latest/download/appcast.xml"
        )
    }

    private func handleSparkle(_ event: SparkleUpdateEvent) {
        switch event {
        case .checking:
            isWorking = true
            lastError = nil
        case let .found(version):
            isWorking = false
            latestVersion = version
            sparkleUpdateReady = false
            compatible = true
        case let .downloading(version):
            isWorking = true
            latestVersion = version
        case let .ready(version):
            isWorking = false
            latestVersion = version
            sparkleUpdateReady = true
            lastError = L10n.text("更新已下载并验证，可在方便时重启。")
        case .current:
            isWorking = false
            latestVersion = ""
            sparkleUpdateReady = false
            compatible = true
        case let .failed(message):
            isWorking = false
            compatible = false
            lastError = message
        }
        let now = Date()
        lastChecked = now
        defaults.set(now, forKey: Keys.lastChecked)
    }

}

private enum Keys {
    static let channel = "client.update.channel"
    static let automatic = "client.update.automaticDownloads"
    static let lastChecked = "client.update.lastChecked"
}
