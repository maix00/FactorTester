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
            let inputData = try stdinJSON.map {
                try JSONSerialization.data(withJSONObject: $0)
            }
            process.executableURL = launch.url
            process.arguments = launch.arguments
            process.standardOutput = output
            process.standardError = errors
            let input = inputData.map { _ in Pipe() }
            if let input {
                process.standardInput = input
            }
            try process.run()

            // Drain both pipes while the child is running. Waiting first can
            // deadlock as soon as a valid JSON response exceeds the kernel
            // pipe buffer (the Profile history already does).
            let outputTask = Task.detached {
                output.fileHandleForReading.readDataToEndOfFile()
            }
            let errorTask = Task.detached {
                errors.fileHandleForReading.readDataToEndOfFile()
            }
            if let input, let inputData {
                input.fileHandleForWriting.write(inputData)
                try input.fileHandleForWriting.close()
            }
            process.waitUntilExit()
            let data = await outputTask.value
            let detail = await errorTask.value
            if process.terminationStatus != 0 {
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
