import Foundation

struct TestJobsRequestError: LocalizedError {
    let statusCode: Int?
    let responseText: String

    var errorDescription: String? {
        if let statusCode {
            return L10n.format(
                "任务服务器返回错误（HTTP %ld）：%@",
                statusCode,
                responseText
            )
        }
        return responseText
    }
}

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
    let contentType: String
    let serverFileName: String?

    var fileName: String {
        if let serverFileName, !serverFileName.isEmpty {
            return serverFileName
        }
        let rawName = URL(fileURLWithPath: name).lastPathComponent
        guard URL(fileURLWithPath: rawName).pathExtension.isEmpty else {
            return rawName
        }
        let extensionName: String
        switch contentType.split(separator: ";", maxSplits: 1).first.map(String.init) {
        case "text/csv": extensionName = "csv"
        case "application/json": extensionName = "json"
        case "image/svg+xml": extensionName = "svg"
        case "application/zip": extensionName = "zip"
        case "text/plain": extensionName = "txt"
        case "application/pdf": extensionName = "pdf"
        default: extensionName = "bin"
        }
        return "\(rawName).\(extensionName)"
    }
}

struct TestJobOutputDeclaration: Identifiable, Hashable {
    let id: String
    let name: String
    let label: String
    let presentation: String
    let viewer: String
    let formats: [String]
    let artifacts: [String]
}

struct TestJobField: Identifiable, Hashable {
    let id: String
    let name: String
    let value: String
    let nameKey: String?
    let nameArgument: String?

    init(
        id: String,
        name: String,
        value: String,
        nameKey: String? = nil,
        nameArgument: String? = nil
    ) {
        self.id = id
        self.name = name
        self.value = value
        self.nameKey = nameKey
        self.nameArgument = nameArgument
    }
}

struct TestJobResultSection: Identifiable {
    enum Kind {
        case chart
        case table
        case json
    }

    let id: String
    let title: String
    let kind: Kind
    let chartPoints: [TestJobChartPoint]
    let rows: [[String: String]]
    let jsonText: String
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
    let fieldRows: [TestJobField]
    let configurationFields: [TestJobField]
    let configurationJSON: String
    let researchBindingFields: [TestJobField]
    let researchBindingJSON: String
    let submissionContextFields: [TestJobField]
    let submissionContextJSON: String
    let resultSections: [TestJobResultSection]
}

struct TestJobChartPoint: Identifiable {
    let id: Int
    let label: String
    let value: Double
}

final class TestJobsService {
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.default
        // Keep the same Flask session cookie used by APIClient.  A separate
        // URLSession must not turn a logged-in job page into an anonymous one.
        configuration.httpCookieStorage = HTTPCookieStorage.shared
        configuration.httpCookieAcceptPolicy = .always
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(
            configuration: configuration,
            delegate: SelfSignedTrustDelegate(),
            delegateQueue: nil
        )
    }()

    func list(port: Int? = nil) async throws -> [TestJob] {
        let suffix = port.map { "&port=\($0)" } ?? "&port=all"
        let json = try await request(path: "/api/jobs?limit=200\(suffix)", port: port)
        return (json["jobs"] as? [[String: Any]] ?? []).map { makeJob($0) }
    }

    func visiblePorts() async throws -> [Int] {
        let json = try await request(path: "/api/jobs/ports")
        return (json["ports"] as? [Any] ?? []).compactMap {
            if let value = $0 as? Int { return value }
            return Int(String(describing: $0))
        }.filter { 1...65535 ~= $0 }
    }

    func detail(
        jobID: String,
        port: Int = 0,
        fallbackJob: TestJob? = nil
    ) async throws -> TestJobDetail {
        let encoded = jobID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? jobID
        let response: [String: Any]
        do {
            response = try await request(path: "/api/jobs/\(encoded)", port: port)
        } catch {
            guard fallbackJob != nil else { throw error }
            response = [:]
        }
        let unified = response["task_detail"] as? [String: Any]
        let detail = unified ?? response
        let jobPayload = (unified?["job"] as? [String: Any]) ?? response
        let artifacts: [String: Any]
        let result: Any?
        if let unified {
            artifacts = ["artifacts": unified["artifacts"] as? [[String: Any]] ?? []]
            let results = unified["results"] as? [String: Any]
            if let summary = results?["summary"] {
                result = summary
            } else if let results {
                result = [
                    "status": results["status"] ?? "",
                    "error": results["error"] ?? NSNull(),
                ]
            } else {
                result = nil
            }
        } else {
            do {
                artifacts = try await request(path: "/api/jobs/\(encoded)/artifacts", port: port)
            } catch {
                // Older jobs may not have retained artifact metadata.  The job
                // itself is still useful and must remain openable.
                artifacts = ["artifacts": []]
            }
            do {
                let resultJSON = try await request(path: "/api/jobs/\(encoded)/result", port: port)
                result = resultJSON["result"] ?? response["result_summary"]
            } catch {
                result = response["result_summary"]
            }
        }
        let rows = previewRows(result)
        let chart = chartPoints(rows)
        let job = makeJob(jobPayload, fallback: fallbackJob ?? TestJob(
            id: jobID,
            kind: "test",
            status: "unknown",
            workspaceID: "",
            port: port,
            profile: "default",
            updatedAt: nil,
            artifactCount: 0
        ))
        return TestJobDetail(
            job: job,
            runSpecHash: jobPayload["run_spec_hash"] as? String ?? "",
            outputRequests: (unified?["output_requests"] as? [String]) ?? response["output_requests"] as? [String] ?? [],
            outputDeclarations: ((unified?["output_declarations"] as? [[String: Any]]) ?? (response["output_declarations"] as? [[String: Any]]) ?? []).map(makeOutputDeclaration),
            configurationText: prettyJSON(detail["configuration"]),
            researchBindingText: prettyJSON(detail["research_binding"] ?? response["research_binding"]),
            submissionContextText: prettyJSON(detail["caller"] ?? response["submission_context"]),
            resultText: prettyJSON(result),
            previewRows: rows,
            chartPoints: chartPoints(rows),
            priceResultData: Self.safeJSONData(result),
            artifacts: (artifacts["artifacts"] as? [[String: Any]] ?? []).map(makeArtifact),
            fieldRows: detailFieldRows(jobPayload.merging(response) { current, _ in current }, job: job),
            configurationFields: scalarFieldRows(detail["configuration"], prefix: "配置"),
            configurationJSON: residualJSON(detail["configuration"]),
            researchBindingFields: scalarFieldRows(detail["research_binding"] ?? response["research_binding"], prefix: "研究绑定"),
            researchBindingJSON: residualJSON(detail["research_binding"] ?? response["research_binding"]),
            submissionContextFields: scalarFieldRows(detail["caller"] ?? response["submission_context"], prefix: "调用方"),
            submissionContextJSON: residualJSON(detail["caller"] ?? response["submission_context"]),
            resultSections: resultSections(rows: rows, chart: chart, resultText: prettyJSON(result))
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
        let destination = root.appendingPathComponent(artifact.fileName)
        try data.write(to: destination, options: .atomic)
        return destination
    }

    func artifactTable(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> TestJobArtifactTable {
        let encodedJob = jobID.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? jobID
        let encodedName = artifact.name.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? artifact.name
        let data = try await requestData(
            path: "/api/jobs/\(encodedJob)/artifacts/\(encodedName)",
            port: port
        )
        return try Self.decodeArtifactTable(data)
    }

    func artifactData(
        jobID: String,
        port: Int,
        artifact: TestJobArtifact
    ) async throws -> Data {
        let encodedJob = jobID.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? jobID
        let encodedName = artifact.name.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? artifact.name
        return try await requestData(
            path: "/api/jobs/\(encodedJob)/artifacts/\(encodedName)",
            port: port
        )
    }

    func downloadAll(jobID: String, port: Int) async throws -> URL {
        let encodedJob = jobID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? jobID
        let data = try await requestData(
            path: "/api/jobs/\(encodedJob)/artifacts/archive",
            port: port
        )
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("FactorTester/jobs/\(jobID)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let archive = root.appendingPathComponent(".job-\(jobID)-artifacts.zip")
        try? FileManager.default.removeItem(at: archive)
        // Remove the ZIP left by the previous client once a new extraction
        // succeeds; the task directory should contain the usable files only.
        let legacyArchive = root.appendingPathComponent("job-\(jobID)-artifacts.zip")
        try data.write(to: archive, options: .atomic)
#if os(macOS)
        do {
            try extractArchive(archive, into: root)
            try FileManager.default.removeItem(at: archive)
            try? FileManager.default.removeItem(at: legacyArchive)
        } catch {
            // Keep the temporary archive when extraction fails so the user can
            // recover it instead of silently losing the downloaded bytes.
            throw error
        }
#endif
        return root
    }

#if os(macOS)
    private func extractArchive(_ archive: URL, into directory: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = ["-x", "-k", archive.path, directory.path]
        let errorPipe = Pipe()
        process.standardError = errorPipe
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let message = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .flatMap { $0.isEmpty ? nil : $0 }
                ?? L10n.text("无法解压任务生成物")
            throw TestJobsRequestError(statusCode: nil, responseText: message)
        }
    }
#endif

    private func request(path: String, method: String = "GET", port: Int? = nil) async throws -> [String: Any] {
        let data = try await requestData(path: path, method: method, port: port)
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("服务器返回格式无效")
            )
        }
        if let success = value["success"] as? Bool, !success {
            let message = value["error"] as? String
                ?? value["message"] as? String
                ?? value["detail"] as? String
                ?? L10n.text("任务请求失败")
            let detail = value["detail"] as? String
            let responseText = detail.map { message == $0 ? message : "\(message)：\($0)" } ?? message
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: responseText
            )
        }
        return value
    }

    private func requestData(path: String, method: String = "GET", port: Int? = nil) async throws -> Data {
        guard var url = ServerConfig.shared.url(forPath: path) else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("尚未配置服务器")
            )
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
        guard let http = response as? HTTPURLResponse else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("服务器没有返回有效的 HTTP 响应")
            )
        }
        guard (200..<300).contains(http.statusCode) else {
            throw TestJobsRequestError(
                statusCode: http.statusCode,
                responseText: Self.responseText(data) ?? "HTTP \(http.statusCode)"
            )
        }
        return data
    }

    private static func responseText(_ data: Data) -> String? {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            for key in ["error", "message", "detail"] {
                if let value = object[key] as? String, !value.isEmpty { return value }
            }
        }
        guard let text = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return String(text.prefix(2_000))
    }

    private func makeJob(_ value: [String: Any], fallback: TestJob? = nil) -> TestJob {
        let context = value["server_context"] as? [String: Any]
        return TestJob(
            id: value["job_id"] as? String ?? fallback?.id ?? "",
            kind: value["kind"] as? String ?? fallback?.kind ?? "test",
            status: value["status"] as? String ?? fallback?.status ?? "unknown",
            workspaceID: value["workspace_id"] as? String ?? fallback?.workspaceID ?? "",
            port: (value["port"] as? Int) ?? (context?["port"] as? Int) ?? fallback?.port ?? 0,
            profile: (context?["profile"] as? String) ?? fallback?.profile ?? "default",
            updatedAt: (value["updated_at"] as? Double).map(Date.init(timeIntervalSince1970:)),
            artifactCount: value["artifact_count"] as? Int ?? fallback?.artifactCount ?? 0
        )
    }

    private func makeArtifact(_ value: [String: Any]) -> TestJobArtifact {
        let name = value["name"] as? String ?? "artifact"
        return TestJobArtifact(
            id: name,
            name: name,
            description: value["description"] as? String ?? name,
            sizeBytes: value["size_bytes"] as? Int ?? 0,
            state: value["state"] as? String ?? "active",
            contentType: value["content_type"] as? String ?? "application/octet-stream",
            serverFileName: value["file_name"] as? String
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
            formats: value["formats"] as? [String] ?? [],
            artifacts: value["artifacts"] as? [String] ?? []
        )
    }

    private func detailFieldRows(_ value: [String: Any], job: TestJob) -> [TestJobField] {
        let context = value["server_context"] as? [String: Any] ?? [:]
        let rawStatus = value["status"] as? String ?? job.status
        let known: [(String, String, String)] = [
            ("job_id", "job_id（任务 ID）", value["job_id"] as? String ?? job.id),
            ("kind", "kind（任务类型）", value["kind"] as? String ?? job.kind),
            ("status", "status（任务状态）", "\(rawStatus)（\(statusLabel(rawStatus))）"),
            ("workspace_id", "workspace_id（工作区）", value["workspace_id"] as? String ?? job.workspaceID),
            ("port", "port（端口）", stringValue(value["port"] ?? context["port"] ?? job.port)),
            ("profile", "profile（研究 Profile）", stringValue(context["profile"] ?? job.profile)),
            ("owner", "owner（提交用户）", stringValue(value["owner"])),
            ("created_at", "created_at（提交时间）", timestampValue(value["created_at"])),
            ("submitted_at", "submitted_at（提交时间，兼容字段）", timestampValue(value["submitted_at"])),
            ("started_at", "started_at（开始时间）", timestampValue(value["started_at"])),
            ("finished_at", "finished_at（完成时间）", timestampValue(value["finished_at"])),
            ("completed_at", "completed_at（完成时间，兼容字段）", timestampValue(value["completed_at"])),
            ("updated_at", "updated_at（更新时间）", timestampValue(value["updated_at"])),
            ("run_spec_hash", "run_spec_hash（RunSpec 哈希）", value["run_spec_hash"] as? String ?? ""),
            ("job_spec_hash", "job_spec_hash（JobSpec 哈希）", value["job_spec_hash"] as? String ?? ""),
            ("execution_mode", "execution_mode（执行模式）", stringValue(value["execution_mode"])),
            ("step_mode", "step_mode（Step 模式）", stringValue(value["step_mode"])),
            ("error", "error（错误）", errorValue(value["error"]))
        ]
        var rows = known.map {
            TestJobField(
                id: $0.0,
                name: $0.1,
                value: $0.2,
                nameKey: $0.1
            )
        }
        rows.append(contentsOf: scalarFieldRows(value["research_binding"], prefix: "研究绑定"))
        rows.append(contentsOf: scalarFieldRows(value["submission_context"], prefix: "调用方"))
        return rows
    }

    private func scalarFieldRows(_ value: Any?, prefix: String) -> [TestJobField] {
        guard let dictionary = value as? [String: Any] else { return [] }
        return dictionary.keys.sorted().compactMap { key in
            guard let value = dictionary[key], isScalar(value) else { return nil }
            let nameKey = "\(prefix) · %@"
            return TestJobField(
                id: "\(prefix).\(key)",
                name: "\(prefix) · \(key)",
                value: stringValue(value),
                nameKey: nameKey,
                nameArgument: key
            )
        }
    }

    private func residualJSON(_ value: Any?) -> String {
        guard let dictionary = value as? [String: Any] else { return "" }
        let residual = dictionary.filter { !isScalar($0.value) }
        return residual.isEmpty ? "" : prettyJSON(residual)
    }

    private func resultSections(
        rows: [[String: String]],
        chart: [TestJobChartPoint],
        resultText: String
    ) -> [TestJobResultSection] {
        var sections: [TestJobResultSection] = []
        if !chart.isEmpty {
            sections.append(TestJobResultSection(id: "chart", title: "收益/指标图表", kind: .chart, chartPoints: chart, rows: [], jsonText: ""))
        }
        if !rows.isEmpty {
            sections.append(TestJobResultSection(id: "table", title: "结果表格", kind: .table, chartPoints: [], rows: rows, jsonText: ""))
        }
        if !resultText.isEmpty {
            sections.append(TestJobResultSection(id: "json", title: "原始结果 JSON", kind: .json, chartPoints: [], rows: [], jsonText: resultText))
        }
        return sections
    }

    private func isScalar(_ value: Any) -> Bool {
        value is String || value is NSNumber || value is NSNull
    }

    private func stringValue(_ value: Any?) -> String {
        guard let value else { return "" }
        if value is NSNull { return "" }
        if let bool = value as? Bool { return L10n.text(bool ? "是" : "否") }
        if let number = value as? NSNumber { return number.stringValue }
        return String(describing: value)
    }

    private func timestampValue(_ value: Any?) -> String {
        let seconds: Double
        if let number = value as? NSNumber {
            seconds = number.doubleValue
        } else if let value = value as? Double {
            seconds = value
        } else {
            return ""
        }
        guard seconds > 0 else { return "" }
        let formatter = DateFormatter()
        formatter.locale = L10n.locale
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.string(from: Date(timeIntervalSince1970: seconds))
    }

    private func errorValue(_ value: Any?) -> String {
        guard let value else { return "" }
        if let text = value as? String { return text }
        return prettyJSON(value)
    }

    private func statusLabel(_ value: String) -> String {
        let key = [
            "succeeded": "成功", "failed": "失败", "running": "运行中",
            "queued": "排队中", "planning": "规划中", "paused": "已暂停",
            "cancelled": "已取消",
        ][value] ?? value
        return L10n.text(key)
    }

    private func prettyJSON(_ value: Any?) -> String {
        guard let value else { return "" }
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return String(describing: value) }
        if text.count > 20_000 {
            return String(text.prefix(20_000)) + "\n…（" + L10n.text("内容过长，已截断；请下载生成物查看完整内容") + ")"
        }
        return text
    }

    static func safeJSONData(_ value: Any?) -> Data? {
        guard let value else { return nil }
        guard JSONSerialization.isValidJSONObject(value)
                || value is String
                || value is NSNumber
                || value is NSNull else { return nil }
        return try? JSONSerialization.data(
            withJSONObject: value,
            options: [.fragmentsAllowed]
        )
    }

    private func previewRows(_ value: Any?) -> [[String: String]] {
        let candidates = (value as? [String: Any])?.values.compactMap { $0 as? [[String: Any]] } ?? []
        return (candidates.first ?? []).prefix(100).map { row in
            row.reduce(into: [String: String]()) { result, pair in
                let value = String(describing: pair.value)
                result[pair.key] = value.count > 500 ? String(value.prefix(500)) + "…" : value
            }
        }
    }

    private func chartPoints(_ rows: [[String: String]]) -> [TestJobChartPoint] {
        let key = rows.first?.keys.first(where: { $0.lowercased().contains("equity") || $0.lowercased().contains("return") })
        guard let key else { return [] }
        return rows.enumerated().compactMap { index, row in
            guard let value = Double(row[key] ?? ""), value.isFinite else { return nil }
            return TestJobChartPoint(id: index, label: row["timestamp"] ?? String(index + 1), value: value)
        }
    }
}
