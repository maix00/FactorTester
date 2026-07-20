import SwiftUI

struct ClientTabView: View {
    let tab: ClientTab
    let goHome: () -> Void
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            tabBar
            Divider()
            content
        }
    }

    private var tabBar: some View {
        HStack(spacing: 10) {
            Button(action: goHome) {
                Label("返回主页", systemImage: "chevron.left")
            }
            .keyboardShortcut("[", modifiers: .command)
            Text(tab.title)
                .font(.headline)
            Spacer()
            Button(action: close) {
                Label("关闭 Tab", systemImage: "xmark")
            }
            .keyboardShortcut("w", modifiers: .command)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(.bar)
    }

    @ViewBuilder
    private var content: some View {
        switch tab.content {
        case .home:
            EmptyView()
        case .module(let module):
            ModuleDestinationView(module: module)
        case .adapter(let adapter):
            if let url = adapter.uiURL {
                LocalAdapterWebView(title: adapter.displayName, url: url)
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "network.slash")
                        .font(.largeTitle)
                    Text("无法打开").font(.headline)
                    Text("该组件没有声明可嵌入的本地 Web UI。")
                        .foregroundStyle(.secondary)
                }
            }
        case .web(let path):
            WebPageView(path: path)
        }
    }
}
