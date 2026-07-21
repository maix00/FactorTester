import CryptoKit
import Foundation

struct CachedInstaller: Codable, Equatable {
    let version: String
    let sha256: String
    let filename: String
    let downloadedAt: Date
    let manifestHash: String?
    let source: String?
}

struct AppUpdateReceipt: Codable {
    var installers: [CachedInstaller] = []
}

struct AppUpdateStore {
    let root: URL

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0].appendingPathComponent("FactorTester/app-updates")
    }

    func save(
        temporaryURL: URL,
        version: String,
        expectedSHA256: String,
        manifestHash: String? = nil,
        source: String? = nil
    ) throws -> CachedInstaller {
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        let filename = "FactorTester-Client-\(version).dmg"
        let destination = root.appendingPathComponent(filename)
        let staging = root.appendingPathComponent(".\(filename).staging")
        try? FileManager.default.removeItem(at: staging)
        do {
            try FileManager.default.copyItem(at: temporaryURL, to: staging)
            let stagedDigest = try Self.sha256(staging)
            guard stagedDigest.caseInsensitiveCompare(
                expectedSHA256
            ) == .orderedSame else {
                throw AppUpdateError.checksumMismatch
            }
        } catch {
            try? FileManager.default.removeItem(at: staging)
            throw error
        }
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: staging, to: destination)

        let item = CachedInstaller(
            version: version,
            sha256: expectedSHA256.lowercased(),
            filename: filename,
            downloadedAt: Date(),
            manifestHash: manifestHash,
            source: source
        )
        var receipt = loadReceipt()
        receipt.installers.removeAll { $0.version == version }
        receipt.installers.append(item)
        receipt.installers = Array(
            receipt.installers.sorted { $0.downloadedAt > $1.downloadedAt }
                .prefix(2)
        )
        try writeReceipt(receipt)
        removeUnreferencedFiles(receipt)
        return item
    }

    func previousInstaller(excluding versions: Set<String>) -> URL? {
        let item = loadReceipt().installers.first {
            !versions.contains($0.version)
        }
        guard let item else { return nil }
        let url = root.appendingPathComponent(item.filename)
        guard FileManager.default.fileExists(atPath: url.path),
              (try? Self.sha256(url)) == item.sha256 else {
            return nil
        }
        return url
    }

    private var receiptURL: URL {
        root.appendingPathComponent("receipt.json")
    }

    private func loadReceipt() -> AppUpdateReceipt {
        guard let data = try? Data(contentsOf: receiptURL),
              let value = try? JSONDecoder().decode(
                AppUpdateReceipt.self,
                from: data
              ) else {
            return AppUpdateReceipt()
        }
        return value
    }

    private func writeReceipt(_ receipt: AppUpdateReceipt) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(receipt)
        let staging = root.appendingPathComponent(".receipt.json.staging")
        try data.write(to: staging, options: .atomic)
        try? FileManager.default.removeItem(at: receiptURL)
        try FileManager.default.moveItem(at: staging, to: receiptURL)
    }

    private func removeUnreferencedFiles(_ receipt: AppUpdateReceipt) {
        let retained = Set(receipt.installers.map(\.filename))
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: nil
        ) else { return }
        for url in urls where
            url.pathExtension == "dmg" && !retained.contains(url.lastPathComponent)
        {
            try? FileManager.default.removeItem(at: url)
        }
    }

    static func sha256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let data = try handle.read(upToCount: 1024 * 1024), !data.isEmpty {
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

enum AppUpdateError: LocalizedError {
    case invalidRelease
    case missingDigest
    case checksumMismatch
    case manifestDigestMismatch
    case manifestSignatureMismatch
    case invalidManifest
    case incompatibleClient
    case bundleIdentityMismatch
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidRelease:
            return L10n.text("公开 Release 必须且只能包含一个 FactorTester-Client.dmg。")
        case .missingDigest:
            return L10n.text("GitHub Release 未提供 DMG 的 SHA-256 digest。")
        case .checksumMismatch:
            return L10n.text("下载的 DMG 校验失败，未保存也未打开。")
        case .manifestDigestMismatch:
            return L10n.text("更新清单摘要与 GitHub 记录不一致。")
        case .manifestSignatureMismatch:
            return L10n.text("更新清单签名无效。")
        case .invalidManifest:
            return L10n.text("更新清单的渠道、版本或 Bundle 身份无效。")
        case .incompatibleClient:
            return L10n.text("当前客户端版本低于该更新要求的最低版本。")
        case .bundleIdentityMismatch:
            return L10n.text("DMG 内 App 的 Bundle ID 或版本与清单不一致。")
        case .server(let detail):
            return detail
        }
    }
}
