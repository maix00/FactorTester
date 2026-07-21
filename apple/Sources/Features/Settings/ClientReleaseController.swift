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
    @Published private(set) var pendingUpdate: PendingApplicationUpdate?
    @Published var lastError: String?
    @Published var channel: String {
        didSet { defaults.set(channel, forKey: Keys.channel) }
    }
    @Published var automaticallyUpdates: Bool {
        didSet { defaults.set(automaticallyUpdates, forKey: Keys.automatic) }
    }

    private let store = AppUpdateStore()
    private let defaults: UserDefaults
    private var resolved: VerifiedAppUpdate?

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
        guard automaticallyUpdates else { return }
        await refresh(force: false)
        guard let resolved,
              VersionOrder.isNewerRelease(
                version: resolved.manifest.version,
                build: resolved.manifest.build,
                thanVersion: installedVersion,
                build: Int(installedBuild) ?? 0
              ), pendingUpdate == nil else { return }
        await update()
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
            let staged = self.store.root
                .appendingPathComponent("pending")
                .appendingPathComponent(value.manifest.version)
                .appendingPathComponent("FTClient.app")
            let stagedApp = try await AppInstallerInspector.stage(
                url,
                at: staged,
                expected: inspection
            )
            self.pendingUpdate = try self.store.savePendingApplication(
                version: value.manifest.version,
                build: String(value.manifest.build),
                channel: value.manifest.channel,
                appURL: stagedApp,
                sha256: value.manifest.sha256
            )
            self.lastError = L10n.text(
                "更新已下载并验证。请点击左下角‘设置’旁的‘重启更新’。"
            )
        }
    }

    func restartToApply() async {
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
    static let automatic = "client.update.automaticDownloads"
    static let lastChecked = "client.update.lastChecked"
}
