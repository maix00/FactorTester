import Foundation

enum ClientTabContent {
    case home
    case module(Module)
    case adapter(ClientAdapterModel)
    case web(path: String)
    case research
    case workPackage(ResearchDirectoryItem)
    case profiles
    case profile(id: String)
    case accountSettings
    case manager
    case jobs
    case testJob(TestJob)
}

struct ClientTab: Identifiable {
    let id: String
    let title: String
    let titleKey: String?
    let systemImage: String
    let content: ClientTabContent

    var localizedTitle: String {
        guard let titleKey else { return title }
        return L10n.text(titleKey)
    }

    static let home = ClientTab(
        id: "home",
        title: "主页",
        titleKey: "主页",
        systemImage: "square.grid.2x2",
        content: .home
    )

    static func module(_ module: Module) -> ClientTab {
        ClientTab(
            id: "module:\(module.id)",
            title: module.title,
            titleKey: module.title,
            systemImage: module.sfSymbol ?? "square.stack.3d.up",
            content: .module(module)
        )
    }

    static func adapter(_ adapter: ClientAdapterModel) -> ClientTab {
        ClientTab(
            id: "adapter:\(adapter.id)",
            title: adapter.displayName,
            titleKey: nil,
            systemImage: "desktopcomputer",
            content: .adapter(adapter)
        )
    }

    static func web(
        id: String,
        title: String,
        titleKey: String? = nil,
        systemImage: String,
        path: String
    ) -> ClientTab {
        ClientTab(
            id: "web:\(id)",
            title: title,
            titleKey: titleKey,
            systemImage: systemImage,
            content: .web(path: path)
        )
    }

    static let research = ClientTab(
        id: "research",
        title: "研究",
        titleKey: "研究",
        systemImage: "chart.xyaxis.line",
        content: .research
    )

    static let jobs = ClientTab(
        id: "jobs",
        title: "测试任务",
        titleKey: "测试任务",
        systemImage: "checklist",
        content: .jobs
    )

    static func testJob(_ job: TestJob) -> ClientTab {
        ClientTab(
            id: "test-job:\(job.port):\(job.id)",
            title: L10n.format("任务 %@", String(job.id.prefix(10))),
            titleKey: nil,
            systemImage: "doc.text.magnifyingglass",
            content: .testJob(job)
        )
    }

    static func workPackage(_ item: ResearchDirectoryItem) -> ClientTab {
        ClientTab(
            id: "work-package:\(item.id)",
            title: item.displayTitle,
            titleKey: nil,
            systemImage: "point.3.connected.trianglepath.dotted",
            content: .workPackage(item)
        )
    }

    static let profiles = ClientTab(
        id: "profiles",
        title: "Profiles",
        titleKey: "Profiles",
        systemImage: "person.2.crop.square.stack",
        content: .profiles
    )

    static func profile(id: String, title: String) -> ClientTab {
        ClientTab(
            id: "profile:\(id)",
            title: title,
            titleKey: nil,
            systemImage: "person.crop.rectangle.stack",
            content: .profile(id: id)
        )
    }

    static let accountSettings = ClientTab(
        id: "account-settings",
        title: "设置",
        titleKey: "设置",
        systemImage: "person.crop.circle",
        content: .accountSettings
    )

    static let manager = ClientTab(
        id: "manager",
        title: "服务器管理",
        titleKey: "服务器管理",
        systemImage: "server.rack",
        content: .manager
    )

    static let factorLibrary = ClientTab.web(
        id: "factor-library",
        title: "因子库",
        titleKey: "因子库",
        systemImage: "function",
        path: "/factors"
    )

    static let products = ClientTab.web(
        id: "products",
        title: "产品",
        titleKey: "产品",
        systemImage: "shippingbox",
        path: "/products"
    )

    var isHome: Bool { id == Self.home.id }

    var isPinnedLauncher: Bool {
        [
            "home", "research", "jobs", "web:factor-library", "web:products",
            "profiles", "account-settings",
        ].contains(id)
    }

    var isClosable: Bool { !isPinnedLauncher }
}
