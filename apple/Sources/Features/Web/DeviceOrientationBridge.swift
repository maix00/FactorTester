#if os(iOS)
import UIKit
import WebKit

/// The setting is device-local; its labels and controls belong to the web UI.
enum DeviceOrientation: String {
    case portrait, landscape, system
    static let defaultsKey = "traderesearch.device.orientation"

    static func current(defaults: UserDefaults = .standard) -> DeviceOrientation {
        DeviceOrientation(rawValue: defaults.string(forKey: defaultsKey) ?? "") ?? .portrait
    }

    var mask: UIInterfaceOrientationMask {
        switch self {
        case .portrait: return .portrait
        case .landscape: return .landscape
        case .system: return .allButUpsideDown
        }
    }
}

final class DeviceOrientationAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        DeviceOrientation.current().mask
    }
}

@MainActor
final class DeviceOrientationBridge: NSObject, WKScriptMessageHandlerWithReply {
    nonisolated static let name = "tradeResearchOrientation"
    private let endpoint: URL
    init(endpoint: URL) { self.endpoint = endpoint }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let origin = message.frameInfo.securityOrigin
        guard message.name == Self.name, message.frameInfo.isMainFrame,
              ManagerConfig.shared.baseURL == endpoint,
              LocalResearchBridgeContract.sameOrigin(scheme: origin.protocol, host: origin.host, port: origin.port, endpoint: endpoint),
              let body = message.body as? [String: String], let action = body["action"] else {
            replyHandler(["success": false], nil); return
        }
        if action == "current", body.count == 1 {
            replyHandler(["success": true, "orientation": DeviceOrientation.current().rawValue], nil); return
        }
        guard action == "set", body.count == 2, let raw = body["orientation"],
              let selected = DeviceOrientation(rawValue: raw) else {
            replyHandler(["success": false], nil); return
        }
        UserDefaults.standard.set(selected.rawValue, forKey: DeviceOrientation.defaultsKey)
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
            for window in scene.windows { window.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations() }
            if #available(iOS 16.0, *) {
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: selected.mask))
            }
        }
        replyHandler(["success": true, "orientation": selected.rawValue], nil)
    }
}
#endif
