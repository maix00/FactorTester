import Foundation

struct AppSignatureStatus {
    let signed: Bool
    let acceptedByGatekeeper: Bool
    let detail: String

    static func inspect() async -> AppSignatureStatus {
        await Task.detached {
            let path = Bundle.main.bundleURL.path
            let signed = run(
                "/usr/bin/codesign",
                ["--verify", "--deep", "--strict", path]
            ).status == 0
            let gatekeeper = run(
                "/usr/sbin/spctl",
                ["--assess", "--type", "execute", path]
            )
            return AppSignatureStatus(
                signed: signed,
                acceptedByGatekeeper: gatekeeper.status == 0,
                detail: gatekeeper.output
            )
        }.value
    }

    private static func run(
        _ executable: String,
        _ arguments: [String]
    ) -> (status: Int32, output: String) {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return (-1, error.localizedDescription)
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return (
            process.terminationStatus,
            String(data: data, encoding: .utf8) ?? ""
        )
    }
}
