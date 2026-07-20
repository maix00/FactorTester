import Foundation

struct AppInstallerInspection {
    let bundleID: String
    let version: String
    let build: String
    let developerIDSigned: Bool
    let notarized: Bool
}

enum AppInstallerInspector {
    static func inspect(_ dmg: URL) async throws -> AppInstallerInspection {
        try await Task.detached {
            let attached = try run(
                "/usr/bin/hdiutil",
                ["attach", "-nobrowse", "-readonly", "-plist", dmg.path]
            )
            let plist = try PropertyListSerialization.propertyList(
                from: attached, format: nil
            ) as? [String: Any]
            let entities = plist?["system-entities"] as? [[String: Any]] ?? []
            guard let rawMount = entities.compactMap({
                $0["mount-point"] as? String
            }).first else { throw AppUpdateError.bundleIdentityMismatch }
            let mount = URL(fileURLWithPath: rawMount)
            defer {
                _ = try? run("/usr/bin/hdiutil", ["detach", mount.path])
            }
            let app = mount.appendingPathComponent("FTClient.app")
            guard let bundle = Bundle(url: app),
                  let bundleID = bundle.bundleIdentifier,
                  let version = bundle.infoDictionary?[
                    "CFBundleShortVersionString"
                  ] as? String,
                  let build = bundle.infoDictionary?[
                    "CFBundleVersion"
                  ] as? String
            else { throw AppUpdateError.bundleIdentityMismatch }
            let signature = try run(
                "/usr/bin/codesign",
                ["--verify", "--deep", "--strict", app.path]
            )
            let detail = try run(
                "/usr/bin/codesign", ["-dv", "--verbose=4", app.path],
                allowStderr: true
            )
            let developerID = signature.isEmpty
                && String(data: detail, encoding: .utf8)?.contains(
                    "Authority=Developer ID Application"
                ) == true
            let gatekeeper = try? run(
                "/usr/sbin/spctl",
                ["--assess", "--verbose=2", "--type", "execute", app.path],
                allowStderr: true
            )
            return AppInstallerInspection(
                bundleID: bundleID, version: version, build: build,
                developerIDSigned: developerID,
                notarized: gatekeeper.flatMap {
                    String(data: $0, encoding: .utf8)
                }?.contains("source=Notarized Developer ID") == true
            )
        }.value
    }

    private static func run(
        _ executable: String,
        _ arguments: [String],
        allowStderr: Bool = false
    ) throws -> Data {
        let process = Process()
        let output = Pipe()
        let errors = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        process.waitUntilExit()
        let stdout = output.fileHandleForReading.readDataToEndOfFile()
        let stderr = errors.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0 else {
            throw AppUpdateError.server(
                String(data: stderr, encoding: .utf8) ?? "installer inspection failed"
            )
        }
        return allowStderr ? stderr : stdout
    }
}
