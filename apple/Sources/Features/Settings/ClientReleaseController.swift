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

    private let defaults: UserDefaults
    private var pendingExternalAction: String?
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
            sparkle.checkForUpdates()
        case "download":
            if hasAvailableUpdate {
                sparkle.downloadAvailableUpdate()
            } else {
                pendingExternalAction = action
                sparkle.checkForUpdates()
            }
        case "restart":
            if isUpdateReady {
                sparkle.installAndRelaunch()
            } else {
                pendingExternalAction = action
                sparkle.checkForUpdates()
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
