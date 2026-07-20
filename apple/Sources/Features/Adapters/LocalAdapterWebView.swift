import SwiftUI

struct LocalAdapterWebView: View {
    @Environment(\.dismiss) private var dismiss

    let title: String
    let url: URL

    var body: some View {
        NavigationStack {
            WebViewRepresentable(
                url: url,
                syncServerCookies: false
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
