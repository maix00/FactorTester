import SwiftUI

struct LocalAdapterWebView: View {
    @Environment(\.dismiss) private var dismiss

    let title: String
    let url: URL
    var webPageSession: WebPageSession? = nil

    var body: some View {
        NavigationStack {
            WebViewRepresentable(
                url: url,
                syncServerCookies: false,
                webSession: webPageSession
            )
            .navigationTitle(title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
            }
        }
        .frame(minWidth: 960, minHeight: 680)
    }
}
