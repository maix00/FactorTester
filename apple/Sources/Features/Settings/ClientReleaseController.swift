import AppKit
import Combine
import Foundation

@MainActor
final class ClientReleaseController: ObservableObject {
    @Published private(set) var installedVersion =
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
    private let installedBuild =
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
    @Published private(set) var latestVersion = ""
    @Published private(set) var compatible: Bool?
    @Published private(set) var healthy: Bool?
    @Published private(set) var signatureText = L10n.text("检查中…")
    @Published private(set) var canRollback = false
    @Published private(set) var isWorking = false
    @Published private(set) var lastChecked: Date?
    @Published var lastError: String?
    @Published var channel: String {
        didSet { defaults.set(channel, forKey: Keys.channel) }
    }
    @Published var automaticallyChecks: Bool {
        didSet { defaults.set(automaticallyChecks, forKey: Keys.automatic) }
    }

    private let store = AppUpdateStore()
    private let installer: AppUpdateInstalling
    private let defaults: UserDefaults
    private var resolved: VerifiedAppUpdate?

    init(
        defaults: UserDefaults = .standard,
        installer: AppUpdateInstalling = HumanDMGInstaller()
    ) {
        self.defaults = defaults
        self.installer = installer
        channel = defaults.string(forKey: Keys.channel) ?? "stable"
        automaticallyChecks = defaults.object(forKey: Keys.automatic) as? Bool ?? true
        lastChecked = defaults.object(forKey: Keys.lastChecked) as? Date
    }

    func refresh(force: Bool = true) async {
        if !force, !shouldCheckAtLaunch { return }
        await perform {
            let signature = await AppSignatureStatus.inspect()
            self.signatureText = signature.acceptedByGatekeeper
                ? L10n.text("Developer ID 已签名并通过 Gatekeeper")
                : (signature.signed ? L10n.text("已签名，但未通过 Gatekeeper")
                                   : L10n.text("未签名开发版本"))
            self.healthy = signature.signed
            self.resolved = try await self.resolveRelease()
            self.latestVersion = self.resolved?.manifest.version ?? ""
            self.compatible = self.resolved != nil
            let now = Date()
            self.lastChecked = now
            self.defaults.set(now, forKey: Keys.lastChecked)
            self.canRollback = self.store.previousInstaller(
                excluding: [self.installedVersion, self.latestVersion]
            ) != nil
        }
    }

    func checkAtLaunch() async {
        guard automaticallyChecks else { return }
        await refresh(force: false)
    }

    func update() async {
        await perform {
            let value = try await self.resolveRelease()
            guard VersionOrder.isNewerRelease(
                version: value.manifest.version,
                build: value.manifest.build,
                thanVersion: self.installedVersion,
                build: Int(self.installedBuild) ?? 0
            ) else { throw AppUpdateError.invalidManifest }
            let (temporary, response) = try await URLSession.shared.download(
                from: value.manifest.dmgURL
            )
            try self.requireSuccess(response)
            guard let finalURL = response.url,
                  TrustedUpdateURL.accepts(finalURL),
                  value.manifest.channel != "beta"
                    || TrustedUpdateURL.sameOrigin(
                        finalURL, value.manifest.dmgURL
                    )
            else { throw AppUpdateError.invalidManifest }
            guard try AppUpdateStore.sha256(temporary)
                    .caseInsensitiveCompare(value.manifest.sha256) == .orderedSame
            else { throw AppUpdateError.checksumMismatch }
            let inspection = try await AppInstallerInspector.inspect(temporary)
            guard inspection.bundleID == "com.gtht.client",
                  inspection.version == value.manifest.version,
                  inspection.build == String(value.manifest.build)
            else { throw AppUpdateError.bundleIdentityMismatch }
            let cached = try self.store.save(
                temporaryURL: temporary,
                version: value.manifest.version,
                expectedSHA256: value.manifest.sha256,
                manifestHash: value.manifestHash,
                source: value.source
            )
            let url = self.store.root.appendingPathComponent(cached.filename)
            try self.installer.presentVerifiedInstaller(
                at: url, inspection: inspection
            )
            self.lastError = inspection.developerIDSigned && inspection.notarized
                ? L10n.text("已验证并打开 DMG。请拖入 Applications 完成安装。")
                : L10n.text("已验证并打开 DMG；当前构建尚未完成 Developer ID 公证，客户端不会静默替换 App。")
        }
    }

    func rollback() async {
        guard let installer = store.previousInstaller(
            excluding: [installedVersion, latestVersion]
        ) else {
            lastError = L10n.text("没有可用的上一版已验证 DMG。")
            return
        }
        NSWorkspace.shared.open(installer)
        lastError = L10n.text("上一版 DMG 已打开。请拖入 Applications 完成回滚。")
    }

    private var shouldCheckAtLaunch: Bool {
        guard let lastChecked else { return true }
        return Date().timeIntervalSince(lastChecked) >= 6 * 60 * 60
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        lastError = nil
        defer { isWorking = false }
        do { try await operation() }
        catch {
            compatible = false
            lastError = error.localizedDescription
        }
    }
}

private enum Keys {
    static let channel = "client.update.channel"
    static let automatic = "client.update.automaticChecks"
    static let lastChecked = "client.update.lastChecked"
}
