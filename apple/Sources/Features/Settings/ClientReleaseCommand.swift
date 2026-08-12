import Foundation

#if os(macOS)
import Darwin
#endif

enum ReleaseCommand {
    static func runObject(
        _ arguments: [String],
        executable: String,
        stdinJSON: [String: Any]? = nil,
        timeout: Duration = .seconds(60)
    ) async throws -> [String: Any] {
        guard let value = try await runJSON(
            arguments,
            executable: executable,
            stdinJSON: stdinJSON,
            timeout: timeout
        ) as? [String: Any] else {
            throw ReleaseCommandError.invalidResponse
        }
        return value
    }

    static func runArray(
        _ arguments: [String],
        executable: String,
        timeout: Duration = .seconds(60)
    ) async throws -> [[String: Any]] {
        guard let value = try await runJSON(
            arguments,
            executable: executable,
            timeout: timeout
        ) as? [[String: Any]] else {
            throw ReleaseCommandError.invalidResponse
        }
        return value
    }

    private static func runJSON(
        _ arguments: [String],
        executable: String,
        stdinJSON: [String: Any]? = nil,
        timeout: Duration
    ) async throws -> Any {
        #if os(macOS)
        let inputData = try stdinJSON.map {
            try JSONSerialization.data(withJSONObject: $0)
        }
        let data = try await withThrowingTaskGroup(of: Data.self) { group in
            group.addTask {
                try await execute(
                    arguments,
                    executable: executable,
                    inputData: inputData
                )
            }
            group.addTask {
                try await Task.sleep(for: timeout)
                throw ReleaseCommandError.timedOut
            }
            defer { group.cancelAll() }
            guard let result = try await group.next() else {
                throw CancellationError()
            }
            return result
        }
        return try JSONSerialization.jsonObject(with: data)
        #else
        throw ReleaseCommandError.unsupportedPlatform
        #endif
    }

    #if os(macOS)
    private static func execute(
        _ arguments: [String],
        executable: String,
        inputData: Data?
    ) async throws -> Data {
        let process = Process()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            let output = Pipe()
            let errors = Pipe()
            let launch = resolve(executable: executable, arguments: arguments)
            process.executableURL = launch.url
            process.arguments = launch.arguments
            process.standardOutput = output
            process.standardError = errors
            let input = inputData.map { _ in Pipe() }
            if let input {
                process.standardInput = input
            }
            try process.run()

            // Cancellation can arrive between the preflight check and launch.
            // In that race the cancellation handler saw no running process, so
            // stop the freshly launched child here as well.
            if Task.isCancelled {
                terminate(process)
                throw CancellationError()
            }

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
            let waitTask = Task.detached {
                process.waitUntilExit()
            }
            await waitTask.value
            let data = await outputTask.value
            let detail = await errorTask.value
            try Task.checkCancellation()
            if process.terminationStatus != 0 {
                throw ReleaseCommandError.failed(
                    String(data: detail, encoding: .utf8) ?? "unknown error"
                )
            }
            return data
        } onCancel: {
            terminate(process)
        }
    }

    private static func terminate(_ process: Process) {
        guard process.isRunning else { return }
        let pid = process.processIdentifier
        process.terminate()
        DispatchQueue.global(qos: .utility).asyncAfter(
            deadline: .now() + .milliseconds(250)
        ) {
            guard process.isRunning, process.processIdentifier == pid else {
                return
            }
            _ = Darwin.kill(pid, SIGKILL)
        }
    }

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
    case timedOut
    case unsupportedPlatform

    var errorDescription: String? {
        switch self {
        case .failed(let detail): return detail
        case .invalidResponse:
            return L10n.text("客户端命令没有返回有效 JSON。")
        case .timedOut:
            return L10n.text("客户端命令执行超时，已终止后台进程。")
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
