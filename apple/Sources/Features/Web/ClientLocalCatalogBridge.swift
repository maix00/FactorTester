import Foundation

enum ClientLocalCatalogBridgeContract {
    static let messageName = "factorTesterLocalCatalog"

    /// Only Manager pages that present factor/product selection receive the
    /// device-local catalog handler. Normalize the route first so a legitimate
    /// query such as `/products?source=local` does not accidentally disable the
    /// bridge, while similarly prefixed unrelated pages remain excluded.
    static func allowsEmbeddedPage(path: String) -> Bool {
        guard let components = URLComponents(string: path),
              components.scheme == nil,
              components.host == nil else { return false }
        let pathname = components.path
        let roots = [
            "/factors", "/products", "/tests", "/ic-test", "/backtest",
            "/factor-series",
        ]
        return roots.contains { root in
            pathname == root || pathname.hasPrefix(root + "/")
        }
    }

    static func arguments(message: [String: Any]) throws -> [String] {
        guard message["action"] as? String == "request" else {
            throw ClientLocalCatalogBridgeError.unsupportedAction
        }
        let path = try requiredText(message, key: "path")
        guard let components = URLComponents(string: path),
              components.scheme == nil,
              components.host == nil,
              (
                  components.path.hasPrefix("/api/client/product")
                    || components.path == "/api/client/contract_tree"
              ) else {
            throw ClientLocalCatalogBridgeError.invalidPath
        }
        let method = String(message["method"] as? String ?? "GET").uppercased()
        guard method == "GET" || method == "POST" else {
            throw ClientLocalCatalogBridgeError.invalidMessage
        }
        var arguments = [
            "client", "source", "request",
            "--path", path, "--method", method,
        ]
        if let body = message["body"] as? String, !body.isEmpty {
            guard let data = body.data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: data),
                  value is [String: Any] else {
                throw ClientLocalCatalogBridgeError.invalidMessage
            }
            arguments.append(contentsOf: ["--body-json", body])
        }
        arguments.append("--json")
        return arguments
    }

    private static func requiredText(
        _ message: [String: Any],
        key: String
    ) throws -> String {
        guard let value = message[key] as? String else {
            throw ClientLocalCatalogBridgeError.invalidMessage
        }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            throw ClientLocalCatalogBridgeError.invalidMessage
        }
        return text
    }
}

enum ClientLocalCatalogBridgeError: LocalizedError {
    case invalidMessage
    case invalidPath
    case unsupportedAction

    var errorDescription: String? {
        switch self {
        case .invalidMessage:
            return L10n.text("本地目录请求格式无效")
        case .invalidPath:
            return L10n.text("本地目录请求路径无效")
        case .unsupportedAction:
            return L10n.text("不支持该本地目录操作")
        }
    }
}

#if os(macOS)
import WebKit

final class ClientLocalCatalogBridge: NSObject, WKScriptMessageHandlerWithReply {
    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.name == ClientLocalCatalogBridgeContract.messageName,
              message.frameInfo.isMainFrame,
              let body = message.body as? [String: Any] else {
            replyHandler(
                nil,
                ClientLocalCatalogBridgeError.invalidMessage.localizedDescription
            )
            return
        }
        Task {
            do {
                let arguments = try ClientLocalCatalogBridgeContract.arguments(
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
