import Foundation

enum ReleaseCommand {
    static func runObject(
        _ arguments: [String],
        executable: String,
        stdinJSON: [String: Any]? = nil
    ) async throws -> [String: Any] {
        guard let value = try await runJSON(
            arguments,
            executable: executable,
            stdinJSON: stdinJSON
        ) as? [String: Any] else {
            throw ReleaseCommandError.invalidResponse
        }
        return value
    }

    static func runArray(
        _ arguments: [String],
        executable: String
    ) async throws -> [[String: Any]] {
        guard let value = try await runJSON(
            arguments,
            executable: executable
        ) as? [[String: Any]] else {
            throw ReleaseCommandError.invalidResponse
        }
        return value
    }

    private static func runJSON(
        _ arguments: [String],
        executable: String,
        stdinJSON: [String: Any]? = nil
    ) async throws -> Any {
        #if os(macOS)
        return try await Task.detached {
            let process = Process()
            let output = Pipe()
            let errors = Pipe()
            let launch = resolve(executable: executable, arguments: arguments)
            process.executableURL = launch.url
            process.arguments = launch.arguments
            process.standardOutput = output
            process.standardError = errors
            if let stdinJSON {
                let input = Pipe()
                process.standardInput = input
                try process.run()
                let data = try JSONSerialization.data(
                    withJSONObject: stdinJSON
                )
                input.fileHandleForWriting.write(data)
                try input.fileHandleForWriting.close()
            } else {
                try process.run()
            }
            process.waitUntilExit()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            if process.terminationStatus != 0 {
                let detail = errors.fileHandleForReading.readDataToEndOfFile()
                throw ReleaseCommandError.failed(
                    String(data: detail, encoding: .utf8) ?? "unknown error"
                )
            }
            return try JSONSerialization.jsonObject(with: data)
        }.value
        #else
        throw ReleaseCommandError.unsupportedPlatform
        #endif
    }

    #if os(macOS)
    private static func resolve(
        executable: String,
        arguments: [String]
    ) -> (url: URL, arguments: [String]) {
        if executable.contains("/") {
            return (URL(fileURLWithPath: executable), arguments)
        }
        if let bundled = Bundle.main.resourceURL?
            .appendingPathComponent("FactorTester/bin")
            .appendingPathComponent(executable),
           FileManager.default.isExecutableFile(atPath: bundled.path) {
            return (bundled, arguments)
        }
        let installed = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(
                "Library/Application Support/FactorTester/bin"
            )
            .appendingPathComponent(executable)
        if FileManager.default.isExecutableFile(atPath: installed.path) {
            return (installed, arguments)
        }
        return (
            URL(fileURLWithPath: "/usr/bin/env"),
            [executable] + arguments
        )
    }
    #endif
}

enum ReleaseCommandError: LocalizedError {
    case failed(String)
    case invalidResponse
    case unsupportedPlatform

    var errorDescription: String? {
        switch self {
        case .failed(let detail): return detail
        case .invalidResponse:
            return L10n.text("客户端命令没有返回有效 JSON。")
        case .unsupportedPlatform:
            return L10n.text("客户端版本管理仅支持 macOS。")
        }
    }
}

extension Dictionary where Key == String, Value == Any {
    func string(_ key: String) -> String {
        self[key] as? String ?? ""
    }

    func bool(_ key: String) -> Bool? {
        self[key] as? Bool
    }
}
