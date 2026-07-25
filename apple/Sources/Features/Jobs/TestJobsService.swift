import Foundation

struct TestJob: Identifiable, Hashable {
    let id: String
    let kind: String
    let status: String
    let workspaceID: String
    let port: Int
    let profile: String
    let updatedAt: Date?
    let artifactCount: Int
}

struct TestJobArtifact: Identifiable, Hashable {
    let id: String
    let name: String
    let description: String
    let sizeBytes: Int
    let state: String
}

struct TestJobOutputDeclaration: Identifiable, Hashable {
    let id: String
    let name: String
    let label: String
    let presentation: String
    let viewer: String
    let formats: [String]
}

struct TestJobDetail {
    let job: TestJob
    let runSpecHash: String
    let outputRequests: [String]
    let outputDeclarations: [TestJobOutputDeclaration]
    let configurationText: String
    let researchBindingText: String
    let submissionContextText: String
    let resultText: String
    let previewRows: [[String: String]]
    let chartPoints: [TestJobChartPoint]
    let priceResultData: Data?
    let artifacts: [TestJobArtifact]
}

struct TestJobChartPoint: Identifiable {
    let id: Int
    let label: String
    let value: Double
}

final class TestJobsService {
    private let session = URLSession(
        configuration: .default,
        delegate: SelfSignedTrustDelegate(),
        delegateQueue: nil
    )

    func list(port: Int? = nil) async throws -> [TestJob] {
        let suffix = port.map { "&port=\($0)" } ?? "&port=all"
        let json = try await request(path: "/api/jobs?limit=200\(suffix)", port: port)
        return (json["jobs"] as? [[String: Any]] ?? []).map(makeJob)
    }

    func visiblePorts() async throws -> [Int] {
        let json = try await request(path: "/api/jobs/ports")
        return (json["ports"] as? [Any] ?? []).compactMap {
            if let value = $0 as? Int { return value }
            return Int(String(describing: $0))
        }.filter { 1...65535 ~= $0 }
    }

    func detail(jobID: String, port: Int = 0) async throws -> TestJobDetail {
        let encoded = jobID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? jobID
        async let detailJSON = request(path: "/api/jobs/\(encoded)", port: port)
        async let artifactsJSON = request(path: "/api/jobs/\(encoded)/artifacts", port: port)
        async let resultJSON = request(path: "/api/jobs/\(encoded)/result", port: port)
        let detail = try await detailJSON
        let artifacts = try await artifactsJSON
        let result = (try? await resultJSON)?["result"] ?? detail["result_summary"]
        let rows = previewRows(result)
        let job = makeJob(detail)
        return TestJobDetail(
            job: job,
            runSpecHash: detail["run_spec_hash"] as? String ?? "",
            outputRequests: detail["output_requests"] as? [String] ?? [],
            outputDeclarations: (detail["output_declarations"] as? [[String: Any]] ?? []).map(makeOutputDeclaration),
            configurationText: prettyJSON(detail["configuration"]),
            researchBindingText: prettyJSON(detail["research_binding"]),
            submissionContextText: prettyJSON(detail["submission_context"]),
            resultText: prettyJSON(result),
            previewRows: rows,
            chartPoints: chartPoints(rows),
            priceResultData: result.flatMap { try? JSONSerialization.data(withJSONObject: $0) },
            artifacts: (artifacts["artifacts"] as? [[String: Any]] ?? []).map(makeArtifact)
        )
    }

    func clearArtifacts(jobID: String, port: Int) async throws {
        _ = try await request(path: "/api/jobs/\(jobID)/artifacts", method: "DELETE", port: port)
    }

    func download(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> URL {
        let encodedJob = jobID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? jobID
        let encodedName = artifact.name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? artifact.name
        let data = try await requestData(path: "/api/jobs/\(encodedJob)/artifacts/\(encodedName)", port: port)
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("FactorTester/jobs/\(jobID)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let safeName = URL(fileURLWithPath: artifact.name).lastPathComponent
        let destination = root.appendingPathComponent(safeName)
        try data.write(to: destination, options: .atomic)
        return destination
    }

    private func request(path: String, method: String = "GET", port: Int? = nil) async throws -> [String: Any] {
        let data = try await requestData(path: path, method: method, port: port)
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "TestJobs", code: 1, userInfo: [NSLocalizedDescriptionKey: "服务器返回格式无效"])
        }
        if let success = value["success"] as? Bool, !success {
            throw NSError(domain: "TestJobs", code: 2, userInfo: [NSLocalizedDescriptionKey: value["error"] as? String ?? "任务请求失败"])
        }
        return value
    }

    private func requestData(path: String, method: String = "GET", port: Int? = nil) async throws -> Data {
        guard var url = ServerConfig.shared.url(forPath: path) else {
            throw NSError(domain: "TestJobs", code: 3, userInfo: [NSLocalizedDescriptionKey: "尚未配置服务器"])
        }
        if let port, port > 0, port != Int(ServerConfig.shared.port) {
            var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            components?.port = port
            if let alternate = components?.url { url = alternate }
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        request.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "TestJobs", code: 4, userInfo: [NSLocalizedDescriptionKey: "任务服务器返回错误"])
        }
        return data
    }

    private func makeJob(_ value: [String: Any]) -> TestJob {
        let context = value["server_context"] as? [String: Any]
        return TestJob(
            id: value["job_id"] as? String ?? "",
            kind: value["kind"] as? String ?? "test",
            status: value["status"] as? String ?? "unknown",
            workspaceID: value["workspace_id"] as? String ?? "",
            port: (value["port"] as? Int) ?? (context?["port"] as? Int) ?? 0,
            profile: (context?["profile"] as? String) ?? "default",
            updatedAt: (value["updated_at"] as? Double).map(Date.init(timeIntervalSince1970:)),
            artifactCount: value["artifact_count"] as? Int ?? 0
        )
    }

    private func makeArtifact(_ value: [String: Any]) -> TestJobArtifact {
        let name = value["name"] as? String ?? "artifact"
        return TestJobArtifact(
            id: name,
            name: name,
            description: value["description"] as? String ?? name,
            sizeBytes: value["size_bytes"] as? Int ?? 0,
            state: value["state"] as? String ?? "active"
        )
    }

    private func makeOutputDeclaration(_ value: [String: Any]) -> TestJobOutputDeclaration {
        let name = value["name"] as? String ?? "output"
        return TestJobOutputDeclaration(
            id: name,
            name: name,
            label: value["label"] as? String ?? name,
            presentation: value["presentation"] as? String ?? "data",
            viewer: value["viewer"] as? String ?? "json",
            formats: value["formats"] as? [String] ?? []
        )
    }

    private func prettyJSON(_ value: Any?) -> String {
        guard let value else { return "—" }
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return String(describing: value) }
        return text
    }

    private func previewRows(_ value: Any?) -> [[String: String]] {
        let candidates = (value as? [String: Any])?.values.compactMap { $0 as? [[String: Any]] } ?? []
        return (candidates.first ?? []).prefix(100).map { row in
            row.reduce(into: [String: String]()) { result, pair in
                result[pair.key] = String(describing: pair.value)
            }
        }
    }

    private func chartPoints(_ rows: [[String: String]]) -> [TestJobChartPoint] {
        let key = rows.first?.keys.first(where: { $0.lowercased().contains("equity") || $0.lowercased().contains("return") })
        guard let key else { return [] }
        return rows.enumerated().compactMap { index, row in
            guard let value = Double(row[key] ?? "") else { return nil }
            return TestJobChartPoint(id: index, label: row["timestamp"] ?? "(index + 1)", value: value)
        }
    }
}
