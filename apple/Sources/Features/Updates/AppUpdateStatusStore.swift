import Foundation

enum AppUpdateStatusStore {
    static let filename = "app-update-status.json"
    static let clientRootEnvironmentKey = "FACTORTESTER_CLIENT_ROOT"

    static func write(
        state: String,
        installedVersion: String,
        latestVersion: String,
        error: String? = nil
    ) {
        let root = rootURL()
        do {
            try FileManager.default.createDirectory(
                at: root,
                withIntermediateDirectories: true
            )
            var payload: [String: Any] = [
                "schema_version": 1,
                "state": state,
                "installed_version": installedVersion,
                "latest_version": latestVersion,
                "updated_at": ISO8601DateFormatter().string(from: Date()),
            ]
            if let error, !error.isEmpty {
                payload["error"] = error
            }
            let data = try JSONSerialization.data(
                withJSONObject: payload,
                options: [.sortedKeys]
            )
            try data.write(
                to: root.appendingPathComponent(filename),
                options: .atomic
            )
        } catch {
            // Update telemetry must never block or fail the client itself.
        }
    }

    static func rootURL(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        applicationSupportURL: URL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
    ) -> URL {
        if let configured = environment[clientRootEnvironmentKey]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !configured.isEmpty {
            return URL(fileURLWithPath: configured, isDirectory: true)
                .standardizedFileURL
        }
        #if DEBUG
        return applicationSupportURL.appendingPathComponent(
            "FactorTester-Debug",
            isDirectory: true
        )
        #else
        return applicationSupportURL.appendingPathComponent(
            "FactorTester",
            isDirectory: true
        )
        #endif
    }
}
