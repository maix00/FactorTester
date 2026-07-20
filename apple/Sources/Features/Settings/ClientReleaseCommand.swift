import Foundation

enum ReleaseCommand {
    static func runObject(
        _ arguments: [String],
        executable: String
    ) async throws -> [String: Any] {
        guard let value = try await runJSON(
            arguments,
            executable: executable
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
        executable: String
    ) async throws -> Any {
        #if os(macOS)
        return try await Task.detached {
            let process = Process()
            let output = Pipe()
            let errors = Pipe()
            if executable.contains("/") {
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
            } else {
                process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                process.arguments = [executable] + arguments
            }
            process.standardOutput = output
            process.standardError = errors
            try process.run()
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
}

enum ReleaseCommandError: LocalizedError {
    case failed(String)
    case invalidResponse
    case unsupportedPlatform

    var errorDescription: String? {
        switch self {
        case .failed(let detail): return detail
        case .invalidResponse: return "客户端命令没有返回有效 JSON。"
        case .unsupportedPlatform: return "客户端版本管理仅支持 macOS。"
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
