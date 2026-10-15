import Foundation
import CryptoKit

extension TestJobsService {
    struct ArtifactTransferAccess: Equatable {
        let url: URL
        let bearer: String
        let expectedSize: Int
    }

    static func decodeArtifactTransferAccess(
        _ data: Data
    ) throws -> ArtifactTransferAccess {
        guard let payload = try JSONSerialization.jsonObject(with: data)
                as? [String: Any],
              let access = payload["access"] as? [String: Any],
              let rawURL = access["url"] as? String,
              let url = URL(string: rawURL),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              let bearer = access["bearer"] as? String,
              !bearer.isEmpty else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("生成物传输授权无效")
            )
        }
        return ArtifactTransferAccess(
            url: url,
            bearer: bearer,
            expectedSize: access["expected_size"] as? Int ?? 0
        )
    }

    func artifactTransferData(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact,
        evidenceRef: String? = nil
    ) async throws -> Data {
        let encodedJob = jobID.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? jobID
        let encodedName = artifact.name.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? artifact.name
        var accessPath = "/api/jobs/\(encodedJob)/artifacts/\(encodedName)/access"
        if let evidenceRef, !evidenceRef.isEmpty {
            var components = URLComponents()
            components.queryItems = [
                URLQueryItem(name: "evidence_ref", value: evidenceRef),
            ]
            accessPath += components.percentEncodedQuery.map { "?\($0)" } ?? ""
        }
        let issued = try await requestData(
            path: accessPath,
            method: "POST",
            port: port
        )
        let access = try Self.decodeArtifactTransferAccess(issued)
        var request = URLRequest(url: access.url)
        request.httpMethod = "GET"
        request.setValue(
            "Bearer \(access.bearer)", forHTTPHeaderField: "Authorization"
        )
        request.setValue(
            "application/octet-stream", forHTTPHeaderField: "Accept"
        )
        request.setValue(
            "FactorTester-Swift/1", forHTTPHeaderField: "User-Agent"
        )
        request.setValue(
            "swift", forHTTPHeaderField: "X-FactorTester-Client"
        )
        let (data, response) = try await transferSession.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("服务器没有返回有效的 HTTP 响应")
            )
        }
        guard (200..<300).contains(http.statusCode) else {
            throw TestJobsRequestError(
                statusCode: http.statusCode,
                responseText: Self.responseText(data)
                    ?? "HTTP \(http.statusCode)"
            )
        }
        let expected = access.expectedSize > 0
            ? access.expectedSize : artifact.sizeBytes
        guard expected == 0 || data.count == expected else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("生成物大小与传输授权不一致")
            )
        }
        if !artifact.contentHash.isEmpty {
            let digest = SHA256.hash(data: data)
                .map { String(format: "%02x", $0) }.joined()
            guard digest == artifact.contentHash.lowercased() else {
                throw TestJobsRequestError(
                    statusCode: nil,
                    responseText: L10n.text("生成物哈希与服务器清单不一致")
                )
            }
        }
        return data
    }

    func download(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> URL {
        let data = try await artifactData(
            jobID: jobID, port: port, artifact: artifact
        )
        let root = try artifactDownloadRoot(jobID: jobID)
        let destination = root.appendingPathComponent(
            URL(fileURLWithPath: artifact.fileName).lastPathComponent
        )
        try data.write(to: destination, options: .atomic)
        return destination
    }

    func artifactTable(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> TestJobArtifactTable {
        let data = try await artifactData(jobID: jobID, port: port, artifact: artifact)
        return try Self.decodeArtifactTable(data)
    }

    func artifactData(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> Data {
        if artifact.state == "local" || artifact.state == "deleted" {
            return try TestJobBackupStore.data(
                principal: backupPrincipal, managerURL: ManagerConfig.shared.baseURL,
                jobID: jobID, artifact: artifact
            )
        }
        do {
            return try await artifactTransferData(
                jobID: jobID, port: port, artifact: artifact
            )
        } catch {
            return try TestJobBackupStore.data(
                principal: backupPrincipal, managerURL: ManagerConfig.shared.baseURL,
                jobID: jobID, artifact: artifact
            )
        }
    }

    func downloadAll(
        jobID: String, port: Int, artifacts: [TestJobArtifact]
    ) async throws -> URL {
        guard !backupPrincipal.isEmpty else {
            throw TestJobsRequestError(statusCode: nil,
                responseText: L10n.text("登录后才能建立个人任务备份"))
        }
        let encoded = jobID.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? jobID
        let response = try await request(
            path: "/api/jobs/\(encoded)/artifacts", port: port
        )
        let storageServerID = response["storage_server_id"] as? String ?? ""
        let active = (response["artifacts"] as? [[String: Any]] ?? [])
            .map(makeArtifact).filter { $0.state == "active" }
        guard !active.isEmpty else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("该任务没有可下载的生成物")
            )
        }
        var downloads: [TestJobBackupStore.Download] = []
        for artifact in active {
            let data = try await artifactTransferData(
                jobID: jobID, port: port, artifact: artifact
            )
            downloads.append(.init(artifact: artifact, data: data))
        }
        return try TestJobBackupStore.save(
            principal: backupPrincipal, managerURL: ManagerConfig.shared.baseURL,
            storageServerID: storageServerID, jobID: jobID,
            downloads: downloads
        )
    }

    private func artifactDownloadRoot(jobID: String) throws -> URL {
        let root = FileManager.default.urls(
            for: .documentDirectory, in: .userDomainMask
        )[0].appendingPathComponent(
            "FactorTester/jobs/\(jobID)", isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true
        )
        return root
    }
}
