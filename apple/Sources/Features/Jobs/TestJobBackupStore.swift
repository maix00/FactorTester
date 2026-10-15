import CryptoKit
import Foundation

/// Locally verified copies of retained Job outputs. The manifest is scoped to
/// the logged-in principal and Manager origin; merely finding a matching job
/// ID on disk is never sufficient to display its bytes.
enum TestJobBackupStore {
    struct Item: Codable {
        let name: String
        let file: String
        let sizeBytes: Int
        let sha256: String
        let contentType: String
    }

    struct Manifest: Codable {
        let schemaVersion: Int
        let principal: String
        let managerOrigin: String
        let storageServerID: String
        let jobID: String
        let verifiedAt: Date
        let items: [Item]
    }

    struct Download {
        let artifact: TestJobArtifact
        let data: Data
    }

    static func save(
        principal: String, managerURL: URL?, storageServerID: String,
        jobID: String, downloads: [Download], baseDirectory: URL? = nil
    ) throws -> URL {
        guard !principal.isEmpty, !storageServerID.isEmpty,
              !jobID.isEmpty, !downloads.isEmpty,
              let origin = origin(managerURL) else {
            throw backupError("备份缺少账户、存储服务器或任务身份")
        }
        let root = try directory(
            principal: principal, origin: origin, jobID: jobID,
            baseDirectory: baseDirectory
        )
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true
        )
        var items: [Item] = []
        var seen = Set<String>()
        for download in downloads {
            let artifact = download.artifact
            guard seen.insert(artifact.name).inserted else {
                throw backupError("备份包含重复附件名称")
            }
            let digest = hash(download.data)
            let serverHash = artifact.contentHash.lowercased()
            guard serverHash.count == 64, serverHash == digest,
                  artifact.sizeBytes == download.data.count else {
                throw backupError("生成物哈希或大小与服务器清单不一致")
            }
            let ext = URL(fileURLWithPath: artifact.fileName).pathExtension
            let safeExtension = ext.count <= 8 && ext.allSatisfy {
                $0.isASCII && ($0.isLetter || $0.isNumber)
            } ? ext : "bin"
            let file = "\(hash(Data(artifact.name.utf8)))-\(digest).\(safeExtension)"
            try download.data.write(
                to: root.appendingPathComponent(file), options: .atomic
            )
            items.append(Item(
                name: artifact.name, file: file,
                sizeBytes: download.data.count, sha256: digest,
                contentType: artifact.contentType
            ))
        }
        let manifest = Manifest(
            schemaVersion: 1, principal: principal, managerOrigin: origin,
            storageServerID: storageServerID, jobID: jobID,
            verifiedAt: Date(), items: items
        )
        let encoded = try JSONEncoder().encode(manifest)
        try encoded.write(to: root.appendingPathComponent("backup.json"), options: .atomic)
        return root
    }

    static func hasBackup(
        principal: String, managerURL: URL?, jobID: String,
        artifact: TestJobArtifact, baseDirectory: URL? = nil
    ) -> Bool {
        guard let (root, manifest) = load(
            principal: principal, managerURL: managerURL, jobID: jobID,
            baseDirectory: baseDirectory
        ), let item = matchingItem(artifact, in: manifest) else { return false }
        return FileManager.default.fileExists(
            atPath: root.appendingPathComponent(item.file).path
        )
    }

    static func data(
        principal: String, managerURL: URL?, jobID: String,
        artifact: TestJobArtifact, baseDirectory: URL? = nil
    ) throws -> Data {
        guard let (root, manifest) = load(
            principal: principal, managerURL: managerURL, jobID: jobID,
            baseDirectory: baseDirectory
        ), let item = matchingItem(artifact, in: manifest) else {
            throw backupError("没有与当前账户和任务匹配的本地备份")
        }
        let bytes = try Data(contentsOf: root.appendingPathComponent(item.file))
        guard bytes.count == item.sizeBytes, hash(bytes) == item.sha256 else {
            throw backupError("本地备份校验失败")
        }
        return bytes
    }

    private static func matchingItem(
        _ artifact: TestJobArtifact, in manifest: Manifest
    ) -> Item? {
        manifest.items.first {
            $0.name == artifact.name &&
            (artifact.contentHash.isEmpty || $0.sha256 == artifact.contentHash.lowercased())
        }
    }

    private static func load(
        principal: String, managerURL: URL?, jobID: String,
        baseDirectory: URL?
    ) -> (URL, Manifest)? {
        guard !principal.isEmpty, !jobID.isEmpty,
              let origin = origin(managerURL),
              let root = try? directory(
                  principal: principal, origin: origin, jobID: jobID,
                  baseDirectory: baseDirectory
              ),
              let data = try? Data(contentsOf: root.appendingPathComponent("backup.json")),
              let manifest = try? JSONDecoder().decode(Manifest.self, from: data),
              manifest.schemaVersion == 1,
              manifest.principal == principal,
              manifest.managerOrigin == origin,
              manifest.jobID == jobID,
              !manifest.storageServerID.isEmpty else { return nil }
        return (root, manifest)
    }

    private static func directory(
        principal: String, origin: String, jobID: String,
        baseDirectory: URL?
    ) throws -> URL {
        let base = try baseDirectory ?? FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        )
        let scope = hash(Data("\(principal)|\(origin)".utf8))
        return base.appendingPathComponent("FactorTester/job-backups", isDirectory: true)
            .appendingPathComponent(scope, isDirectory: true)
            .appendingPathComponent(hash(Data(jobID.utf8)), isDirectory: true)
    }

    private static func origin(_ url: URL?) -> String? {
        guard let url, let scheme = url.scheme?.lowercased(),
              let host = url.host?.lowercased(),
              ["http", "https"].contains(scheme) else { return nil }
        return "\(scheme)://\(host):\(url.port ?? (scheme == "https" ? 443 : 80))"
    }

    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func backupError(_ message: String) -> TestJobsRequestError {
        TestJobsRequestError(statusCode: nil, responseText: L10n.text(message))
    }
}
