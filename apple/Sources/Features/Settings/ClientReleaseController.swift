import AppKit
import Combine
import Foundation

@MainActor
final class ClientReleaseController: ObservableObject {
    enum SignatureState: Sendable {
        case checking
        case accepted
        case signedButNotAccepted
        case unsigned

        var localizedText: String {
            switch self {
            case .checking: return L10n.text("检查中…")
            case .accepted: return L10n.text("Developer ID 已签名并通过 Gatekeeper")
            case .signedButNotAccepted: return L10n.text("已签名，但未通过 Gatekeeper")
            case .unsigned: return L10n.text("未签名开发版本")
            }
        }
    }

    @Published private(set) var installedVersion =
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
    @Published private(set) var latestVersion = ""
    @Published private(set) var compatible: Bool?
    @Published private(set) var healthy: Bool?
    @Published private(set) var signatureState: SignatureState = .checking
    @Published private(set) var isWorking = false
    @Published private(set) var lastChecked: Date?
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

    /// Resolves the current display language at render time rather than when
    /// the controller was initialized. This keeps the Settings page in sync
    /// when the user switches languages without another update check.
    var signatureText: String { signatureState.localizedText }

    private let defaults: UserDefaults
    private var pendingExternalAction: String?
    private lazy var sparkle = SparkleUpdateCoordinator(
        feedURL: { [weak self] in self?.sparkleFeedURL },
        channel: { [weak self] in self?.channel ?? "stable" },
        event: { [weak self] event in self?.handleSparkle(event) }
    )

    init(
        defaults: UserDefaults = .standard
    ) {
        self.defaults = defaults
        channel = defaults.string(forKey: Keys.channel) ?? "stable"
        automaticallyUpdates = defaults.object(forKey: Keys.automatic) as? Bool ?? false
        lastChecked = defaults.object(forKey: Keys.lastChecked) as? Date
        AppUpdateStatusStore.write(
            state: "idle",
            installedVersion: installedVersion,
            latestVersion: latestVersion
        )
        sparkle.automaticallyChecksForUpdates = true
        sparkle.automaticallyDownloadsUpdates = automaticallyUpdates
    }

    func refresh(force: Bool = true) async {
        if !force, !shouldCheckAtLaunch { return }
        let signature = await AppSignatureStatus.inspect()
        signatureState = signature.acceptedByGatekeeper
            ? .accepted
            : (signature.signed ? .signedButNotAccepted : .unsigned)
        healthy = signature.signed
        guard !isWorking, !hasAvailableUpdate else { return }
        sparkle.checkForUpdates()
    }

    func checkAtLaunch() async {
        guard shouldCheckAtLaunch, !isWorking, !hasAvailableUpdate else { return }
        sparkle.checkForUpdatesInBackground()
    }

    var hasAvailableUpdate: Bool {
        !latestVersion.isEmpty && !sparkleUpdateReady
    }

    func update() async {
        sparkle.downloadAvailableUpdate()
    }

    func restartToApply() async {
        guard sparkleUpdateReady else {
            lastError = L10n.text("当前没有已准备好的更新。")
            return
        }
        sparkle.installAndRelaunch()
    }

    func handleUpdateCommand(_ url: URL) {
        guard url.scheme == "factortester",
              url.host == "app-update",
              let components = URLComponents(
                url: url,
                resolvingAgainstBaseURL: false
              ),
              let action = components.queryItems?.first(
                where: { $0.name == "action" }
              )?.value else {
            lastError = L10n.text("忽略了无效的更新命令。")
            return
        }
        switch action {
        case "check":
            // Sparkle keeps the update reply open after it reports an
            // available update. Starting another check at that point causes
            // its user driver to receive a re-entrant check request.
            guard !isWorking, !hasAvailableUpdate else { return }
            sparkle.checkForUpdates()
        case "download":
            if isUpdateReady { return }
            if hasAvailableUpdate {
                pendingExternalAction = nil
                sparkle.downloadAvailableUpdate()
            } else {
                pendingExternalAction = action
                if !isWorking {
                    sparkle.checkForUpdates()
                }
            }
        case "restart":
            if isUpdateReady {
                sparkle.installAndRelaunch()
            } else if hasAvailableUpdate {
                pendingExternalAction = action
                sparkle.downloadAvailableUpdate()
            } else {
                pendingExternalAction = action
                if !isWorking {
                    sparkle.checkForUpdates()
                }
            }
        default:
            lastError = L10n.text("忽略了无效的更新命令。")
        }
    }

    private var shouldCheckAtLaunch: Bool {
        guard let lastChecked else { return true }
        return Date().timeIntervalSince(lastChecked) >= 6 * 60 * 60
    }

    var isUpdateReady: Bool {
        sparkleUpdateReady
    }

    var pendingVersion: String? {
        sparkleUpdateReady ? latestVersion : nil
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
            if pendingExternalAction == "download" {
                pendingExternalAction = nil
                sparkle.downloadAvailableUpdate()
            }
        case let .downloading(version):
            isWorking = true
            latestVersion = version
        case let .ready(version):
            isWorking = false
            latestVersion = version
            sparkleUpdateReady = true
            lastError = L10n.text("更新已下载并验证，可在方便时重启。")
            if pendingExternalAction == "restart" {
                pendingExternalAction = nil
                sparkle.installAndRelaunch()
            }
        case .current:
            isWorking = false
            latestVersion = ""
            sparkleUpdateReady = false
            compatible = true
            pendingExternalAction = nil
        case let .failed(message):
            isWorking = false
            compatible = false
            lastError = message
            pendingExternalAction = nil
        }
        AppUpdateStatusStore.write(
            state: statusState(for: event),
            installedVersion: installedVersion,
            latestVersion: latestVersion,
            error: lastError
        )
        let now = Date()
        lastChecked = now
        defaults.set(now, forKey: Keys.lastChecked)
    }

    private func statusState(for event: SparkleUpdateEvent) -> String {
        switch event {
        case .checking: return "checking"
        case .found: return "available"
        case .downloading: return "downloading"
        case .ready: return "ready"
        case .current: return "current"
        case .failed: return "failed"
        }
    }

}

private enum Keys {
    static let channel = "client.update.channel"
    static let automatic = "client.update.automaticDownloads"
    static let lastChecked = "client.update.lastChecked"
}
