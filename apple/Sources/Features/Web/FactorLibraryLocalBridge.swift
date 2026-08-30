import Foundation

enum FactorLibraryLocalBridgeContract {
    static let messageName = "factorTesterLocalFactorSets"

    static func returnsArray(message: [String: Any]) -> Bool {
        switch message["action"] as? String {
        case "owners", "revisions", "families":
            return true
        default:
            return false
        }
    }

    static func arguments(message: [String: Any]) throws -> [String] {
        switch message["action"] as? String {
        case "catalog":
            var arguments = [
                "factor-library", "workspace", "factor-set",
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
                  isV2FactorSetReference(targetRef) else {
                throw FactorLibraryLocalBridgeError.invalidTarget
            }
            let offset = max(0, message["offset"] as? Int ?? 0)
            let limit = min(100, max(1, message["limit"] as? Int ?? 50))
            return [
                "factor-library", "workspace", "factor-set",
                "members", "--target-ref", targetRef,
                "--offset", String(offset), "--limit", String(limit), "--json",
            ]
        case "descriptor":
            guard let targetRef = message["target_ref"] as? String,
                  isV2FactorSetReference(targetRef) else {
                throw FactorLibraryLocalBridgeError.invalidTarget
            }
            return [
                "factor-library", "workspace", "factor-set",
                "descriptor", "--target-ref", targetRef, "--json",
            ]
        case "run-input":
            guard let targetRef = message["target_ref"] as? String,
                  isV2FactorSetReference(targetRef) else {
                throw FactorLibraryLocalBridgeError.invalidTarget
            }
            return [
                "factor-library", "workspace", "factor-set",
                "run-input", "--target-ref", targetRef, "--json",
            ]
        case "owners":
            return [
                "factor-library", "workspace", "owners", "list",
                "--json",
            ]
        case "revisions":
            let ownerRef = try requiredText(message, key: "owner_ref")
            let limit = min(200, max(1, message["limit"] as? Int ?? 50))
            return [
                "factor-library", "workspace", "revisions", "list",
                "--owner-ref", ownerRef, "--limit", String(limit), "--json",
            ]
        case "families":
            let ownerRef = try requiredText(message, key: "owner_ref")
            let revision = try requiredText(message, key: "git_commit")
            return [
                "factor-library", "workspace", "families", "list",
                "--owner-ref", ownerRef, "--git-commit", revision, "--json",
            ]
        case "family":
            let ownerRef = try requiredText(message, key: "owner_ref")
            let revision = try requiredText(message, key: "git_commit")
            let family = try requiredText(message, key: "family")
            return [
                "factor-library", "workspace", "families", "describe",
                "--owner-ref", ownerRef, "--git-commit", revision,
                "--family", family, "--json",
            ]
        case "instantiate":
            let ownerRef = try requiredText(message, key: "owner_ref")
            let revision = try requiredText(message, key: "git_commit")
            let family = try requiredText(message, key: "family")
            let parameters = message["params"] as? [String: Any] ?? [:]
            guard JSONSerialization.isValidJSONObject(parameters) else {
                throw FactorLibraryLocalBridgeError.invalidMessage
            }
            let data = try JSONSerialization.data(
                withJSONObject: parameters,
                options: [.sortedKeys]
            )
            guard let json = String(data: data, encoding: .utf8) else {
                throw FactorLibraryLocalBridgeError.invalidMessage
            }
            return [
                "factor-library", "workspace", "factors", "instantiate",
                "--owner-ref", ownerRef, "--git-commit", revision,
                "--family", family, "--params-json", json, "--json",
            ]
        default:
            throw FactorLibraryLocalBridgeError.unsupportedAction
        }
    }

    private static func requiredText(
        _ message: [String: Any],
        key: String
    ) throws -> String {
        guard let value = message[key] as? String else {
            throw FactorLibraryLocalBridgeError.invalidMessage
        }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            throw FactorLibraryLocalBridgeError.invalidMessage
        }
        return text
    }

    private static func isV2FactorSetReference(_ value: String) -> Bool {
        let prefix = "factor-set:v2:"
        guard value.hasPrefix(prefix) else { return false }
        let digest = value.dropFirst(prefix.count)
        return digest.count == 43 && digest.allSatisfy {
            $0.isLetter || $0.isNumber || $0 == "_" || $0 == "-"
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
                let executable = ClientCLIResolution.executable()
                let value: Any
                if FactorLibraryLocalBridgeContract.returnsArray(message: body) {
                    value = try await ReleaseCommand.runArray(
                        arguments,
                        executable: executable
                    )
                } else {
                    value = try await ReleaseCommand.runObject(
                        arguments,
                        executable: executable
                    )
                }
                replyHandler(value, nil)
            } catch {
                replyHandler(nil, error.localizedDescription)
            }
        }
    }
}
#endif
