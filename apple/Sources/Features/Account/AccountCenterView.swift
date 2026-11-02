import SwiftUI

/// Retained native navigation uses the shared React account surface.
struct AccountSettingsView: View {
    var body: some View { WebPageView(path: "/app?settings=account", presentation: .standalone) }
}
