import AppKit
import Foundation

protocol AppUpdateInstalling {
    @MainActor
    func presentVerifiedInstaller(
        at url: URL,
        inspection: AppInstallerInspection
    ) throws
}

struct HumanDMGInstaller: AppUpdateInstalling {
    func presentVerifiedInstaller(
        at url: URL,
        inspection: AppInstallerInspection
    ) throws {
        guard NSWorkspace.shared.open(url) else {
            throw AppUpdateError.server(L10n.text("无法打开已验证的 DMG。"))
        }
    }
}

// A future notarized helper or Sparkle adapter plugs into this protocol.
// Until then, HumanDMGInstaller never replaces the running application.
