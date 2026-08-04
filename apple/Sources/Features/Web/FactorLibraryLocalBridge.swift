import Foundation

enum FactorLibraryLocalBridgeContract {
    static let messageName = "factorTesterLocalFactorSets"

    static func arguments(message: [String: Any]) throws -> [String] {
        switch message["action"] as? String {
        case "catalog":
            var arguments = [
                "client", "profile", "factor-worktree", "factor-set",
                "local-catalog", "--json",
            ]
            let query = (message["query"] as? String ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !query.isEmpty {
                arguments.insert(contentsOf: ["--query", query], at: 5)
            }
            return arguments
        case "members":
            guard let targetRef = message["target_ref"] as? String,
                  targetRef.hasPrefix("factor-set:v1:") else {
                throw FactorLibraryLocalBridgeError.invalidTarget
            }
            let offset = max(0, message["offset"] as? Int ?? 0)
            let limit = min(100, max(1, message["limit"] as? Int ?? 50))
            return [
                "client", "profile", "factor-worktree", "factor-set",
                "members", "--target-ref", targetRef,
                "--offset", String(offset), "--limit", String(limit), "--json",
            ]
        default:
            throw FactorLibraryLocalBridgeError.unsupportedAction
        }
    }
}

enum FactorLibraryLocalBridgeError: LocalizedError {
    case invalidMessage
    case invalidTarget
    case unsupportedAction

    var errorDescription: String? {
        switch self {
        case .invalidMessage:
            return L10n.text("本地因子集合请求格式无效")
        case .invalidTarget:
            return L10n.text("本地因子集合引用无效")
        case .unsupportedAction:
            return L10n.text("不支持该本地因子集合操作")
        }
    }
}

#if os(macOS)
import WebKit

final class FactorLibraryLocalBridge: NSObject, WKScriptMessageHandlerWithReply {
    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.name == FactorLibraryLocalBridgeContract.messageName,
              message.frameInfo.isMainFrame,
              let body = message.body as? [String: Any] else {
            replyHandler(
                nil,
                FactorLibraryLocalBridgeError.invalidMessage.localizedDescription
            )
            return
        }
        Task {
            do {
                let arguments = try FactorLibraryLocalBridgeContract.arguments(
                    message: body
                )
                try await BundledRuntimeActivator.waitUntilReady()
                let value = try await ReleaseCommand.runObject(
                    arguments,
                    executable: ClientCLIResolution.executable()
                )
                replyHandler(value, nil)
            } catch {
                replyHandler(nil, error.localizedDescription)
            }
        }
    }
}
#endif
