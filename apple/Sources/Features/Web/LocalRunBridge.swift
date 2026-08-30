import Foundation

enum LocalRunBridgeContract {
    static let messageName = "factorTesterLocalRun"

    static func arguments(message: [String: Any]) throws -> [String] {
        guard message["action"] as? String == "upload" else {
            throw LocalRunBridgeError.unsupportedAction
        }
        let jobID = try requiredText(message, key: "local_job_id")
        let name = try requiredText(message, key: "name")
        guard jobID.count <= 128, name.count <= 512,
              !name.contains("/"), !name.contains("\\") else {
            throw LocalRunBridgeError.invalidMessage
        }
        var arguments = [
            "client", "local-run", "upload", jobID, name,
            "--json",
        ]
        let profilePath = UserDefaults.standard.string(
            forKey: "client.release.profilePath"
        )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !profilePath.isEmpty {
            arguments += ["--release-profile", profilePath]
        }
        return arguments
    }

    static func syncArguments() -> [String] {
        var arguments = [
            "client", "local-run", "outbox", "--sync", "--json",
        ]
        let profilePath = UserDefaults.standard.string(
            forKey: "client.release.profilePath"
        )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !profilePath.isEmpty {
            arguments += ["--release-profile", profilePath]
        }
        return arguments
    }

    private static func requiredText(
        _ message: [String: Any],
        key: String
    ) throws -> String {
        guard let value = message[key] as? String else {
            throw LocalRunBridgeError.invalidMessage
        }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw LocalRunBridgeError.invalidMessage }
        return text
    }
}

enum LocalRunBridgeError: LocalizedError {
    case invalidMessage
    case unsupportedAction

    var errorDescription: String? {
        switch self {
        case .invalidMessage:
            return L10n.text("本地生成物上传请求格式无效")
        case .unsupportedAction:
            return L10n.text("不支持该本地运行操作")
        }
    }
}

#if os(macOS)
import WebKit

final class LocalRunBridge: NSObject, WKScriptMessageHandlerWithReply {
    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.name == LocalRunBridgeContract.messageName,
              message.frameInfo.isMainFrame,
              let body = message.body as? [String: Any] else {
            replyHandler(nil, LocalRunBridgeError.invalidMessage.localizedDescription)
            return
        }
        Task {
            do {
                let arguments = try LocalRunBridgeContract.arguments(message: body)
                try await BundledRuntimeActivator.waitUntilReady()
                let executable = ClientCLIResolution.executable()
                let queued = try await ReleaseCommand.runObject(
                    arguments, executable: executable,
                )
                let sync: [String: Any]
                do {
                    sync = try await ReleaseCommand.runObject(
                        LocalRunBridgeContract.syncArguments(),
                        executable: executable,
                    )
                } catch {
                    // Upload intent is durable even while the Manager is
                    // offline.  Keep the UI successful and expose the
                    // pending state so the next sync can retry it.
                    sync = [
                        "success": false,
                        "pending_sync": true,
                        "error": error.localizedDescription,
                    ]
                }
                replyHandler([
                    "success": true,
                    "queued": queued,
                    "sync": sync,
                    "pending_sync": sync["success"] as? Bool != true,
                ], nil)
            } catch {
                replyHandler(nil, error.localizedDescription)
            }
        }
    }
}
#endif
