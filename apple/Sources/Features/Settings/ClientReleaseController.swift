import AppKit
import Combine
import Foundation

@MainActor
final class ClientReleaseController: ObservableObject {
    private let endpoint = URL(
        string: "https://api.github.com/repos/maix00/FactorTester-Client/releases/latest"
    )!
    private let store = AppUpdateStore()

    @Published private(set) var installedVersion =
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
    @Published private(set) var latestVersion = ""
    @Published private(set) var compatible: Bool?
    @Published private(set) var healthy: Bool?
    @Published private(set) var signatureText = "检查中…"
    @Published private(set) var canRollback = false
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    private var release: GitHubRelease?

    func refresh() async {
        await perform {
            let signature = await AppSignatureStatus.inspect()
            self.signatureText = signature.acceptedByGatekeeper
                ? "Developer ID 已签名并通过 Gatekeeper"
                : (signature.signed ? "已签名，但未通过 Gatekeeper" : "未签名开发版本")
            self.healthy = signature.signed
            self.release = try await self.fetchLatestRelease()
            self.latestVersion = self.release?.version ?? ""
            self.compatible = self.release?.installer?.sha256 != nil
            self.canRollback = self.store.previousInstaller(
                excluding: [self.installedVersion, self.latestVersion]
            ) != nil
        }
    }

    func update() async {
        await perform {
            let release = try await self.fetchLatestRelease()
            guard let asset = release.installer else {
                throw AppUpdateError.invalidRelease
            }
            guard let digest = asset.sha256 else {
                throw AppUpdateError.missingDigest
            }
            let (temporary, response) = try await URLSession.shared.download(
                from: asset.browserDownloadURL
            )
            guard let http = response as? HTTPURLResponse,
                  (200..<300).contains(http.statusCode) else {
                throw AppUpdateError.server("DMG 下载失败。")
            }
            let installer = try self.store.save(
                temporaryURL: temporary,
                version: release.version,
                expectedSHA256: digest
            )
            let url = self.store.root.appendingPathComponent(installer.filename)
            NSWorkspace.shared.open(url)
            self.lastError = "DMG 已校验并打开。请拖入 Applications，然后重新启动客户端。"
            self.canRollback = self.store.previousInstaller(
                excluding: [self.installedVersion, release.version]
            ) != nil
        }
    }

    func rollback() async {
        guard let installer = store.previousInstaller(
            excluding: [installedVersion, latestVersion]
        ) else {
            lastError = "没有可用的上一版已验证 DMG。"
            return
        }
        NSWorkspace.shared.open(installer)
        lastError = "上一版 DMG 已打开。请拖入 Applications 完成回滚。"
    }

    private func fetchLatestRelease() async throws -> GitHubRelease {
        var request = URLRequest(url: endpoint)
        request.setValue(
            "FactorTester-Client/\(installedVersion)",
            forHTTPHeaderField: "User-Agent"
        )
        request.setValue(
            "application/vnd.github+json",
            forHTTPHeaderField: "Accept"
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            throw AppUpdateError.server("无法读取公开 GitHub Release。")
        }
        let value = try JSONDecoder().decode(GitHubRelease.self, from: data)
        guard !value.draft, !value.prerelease, value.installer != nil else {
            throw AppUpdateError.invalidRelease
        }
        return value
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        lastError = nil
        defer { isWorking = false }
        do {
            try await operation()
        } catch {
            compatible = false
            lastError = error.localizedDescription
        }
    }
}
