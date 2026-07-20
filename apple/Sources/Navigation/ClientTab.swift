import Foundation

enum ClientTabContent {
    case home
    case module(Module)
    case adapter(ClientAdapterModel)
    case web(path: String)
}

struct ClientTab: Identifiable {
    let id: String
    let title: String
    let systemImage: String
    let content: ClientTabContent

    static let home = ClientTab(
        id: "home",
        title: "主页",
        systemImage: "square.grid.2x2",
        content: .home
    )

    static func module(_ module: Module) -> ClientTab {
        ClientTab(
            id: "module:\(module.id)",
            title: module.title,
            systemImage: module.sfSymbol ?? "square.stack.3d.up",
            content: .module(module)
        )
    }

    static func adapter(_ adapter: ClientAdapterModel) -> ClientTab {
        ClientTab(
            id: "adapter:\(adapter.id)",
            title: adapter.displayName,
            systemImage: "desktopcomputer",
            content: .adapter(adapter)
        )
    }

    static func web(
        id: String,
        title: String,
        systemImage: String,
        path: String
    ) -> ClientTab {
        ClientTab(
            id: "web:\(id)",
            title: title,
            systemImage: systemImage,
            content: .web(path: path)
        )
    }

    var isHome: Bool { id == Self.home.id }
}
