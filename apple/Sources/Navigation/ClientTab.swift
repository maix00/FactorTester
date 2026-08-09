import Foundation

enum ClientTabContent {
    case home
    case module(Module)
    case adapter(ClientAdapterModel)
    case web(path: String)
    case externalWeb(URL)
    case reference(ResearchDocumentTypedLink)
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
        let opensAsFreshTab = ["docs", "sqlite_web"].contains(module.id)
        let tabID = opensAsFreshTab
            ? "module:\(module.id):\(UUID().uuidString)"
            : "module:\(module.id)"
        return ClientTab(
            id: tabID,
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

    static func externalWeb(_ url: URL) -> ClientTab {
        let title = url.host ?? "网页"
        return ClientTab(
            id: "external-url:\(url.absoluteString)",
            title: title,
            titleKey: nil,
            systemImage: "safari",
            content: .externalWeb(url)
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

    static let icTestLauncher = ClientTab(
        id: "ic-test-launcher",
        title: "IC 测试",
        titleKey: "IC 测试",
        systemImage: "chart.xyaxis.line",
        content: .web(path: "/ic-test")
    )

    static let backtestLauncher = ClientTab(
        id: "backtest-launcher",
        title: "回测",
        titleKey: "回测",
        systemImage: "chart.line.uptrend.xyaxis",
        content: .web(path: "/backtest")
    )

    static func icTest() -> ClientTab {
        testPage(
            id: "ic-test", title: "IC 测试",
            systemImage: "chart.xyaxis.line", path: "/ic-test"
        )
    }

    static func backtest() -> ClientTab {
        testPage(
            id: "backtest", title: "回测",
            systemImage: "chart.line.uptrend.xyaxis", path: "/backtest"
        )
    }

    private static func testPage(
        id: String, title: String, systemImage: String, path: String
    ) -> ClientTab {
        ClientTab(
            id: "\(id):\(UUID().uuidString)",
            title: title,
            titleKey: title,
            systemImage: systemImage,
            content: .web(path: path)
        )
    }

    static func testJob(_ job: TestJob) -> ClientTab {
        let title = L10n.format("%@ · %@", ProfilePresentationText.jobKind(job.kind), job.id)
        return .web(
            id: "test-job:\(job.port):\(job.id)",
            title: title,
            titleKey: nil,
            systemImage: "doc.text.magnifyingglass",
            path: jobPath(job)
        )
    }

    static func jobPath(_ job: TestJob) -> String {
        let encoded = job.id.addingPercentEncoding(
            withAllowedCharacters: .factortesterPathComponent
        ) ?? job.id
        if job.port > 0 { return "/jobs/\(job.port)/\(encoded)" }
        return "/jobs/\(encoded)"
    }

    static func researchReport(path: String) -> ClientTab {
        .web(
            id: "research-report:\(path)",
            title: "研究报告",
            titleKey: "研究报告",
            systemImage: "doc.text",
            path: path
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
        path: "/products?source=local"
    )

    static func product(_ target: String, title: String = "产品", source: String? = nil) -> ClientTab {
        let encoded = target.addingPercentEncoding(withAllowedCharacters: .factortesterPathComponent) ?? target
        let suffix = source == "local" ? "?source=local" : ""
        return .web(id: "product:\(target)", title: title, titleKey: nil, systemImage: "shippingbox", path: "/products/product/\(encoded)\(suffix)")
    }

    static func productGroup(_ target: String, title: String = "产品组", source: String? = nil) -> ClientTab {
        let encoded = target.addingPercentEncoding(withAllowedCharacters: .factortesterPathComponent) ?? target
        let suffix = source == "local" ? "?source=local" : ""
        return .web(id: "product-group:\(target)", title: title, titleKey: nil, systemImage: "shippingbox.and.arrow.backward", path: "/products/group/\(encoded)\(suffix)")
    }

    static func productContract(_ target: String, title: String? = nil, continuous: Bool = false, source: String? = nil) -> ClientTab {
        let encoded = target.addingPercentEncoding(withAllowedCharacters: .factortesterPathComponent) ?? target
        let kind = continuous ? "continuous-contract" : "contract"
        let symbol = continuous ? "link" : "doc.text"
        let suffix = source == "local" ? "?source=local" : ""
        return .web(id: "product-\(kind):\(target)", title: title ?? target, titleKey: nil, systemImage: symbol, path: "/products/\(kind)/\(encoded)\(suffix)")
    }

    static func reference(_ reference: ResearchDocumentTypedLink) -> ClientTab? {
        let route: (page: String, symbol: String, target: String)?
        switch reference.kind.replacingOccurrences(of: "_", with: "-") {
        case "factor-family":
            route = ("/factors/family/", "function", reference.targetRef)
        case "factor":
            if reference.targetRef.hasPrefix("factor-family:") {
                route = ("/factors/family/", "function", reference.targetRef)
            } else if reference.targetRef.hasPrefix("factor-set:") {
                route = ("/factors/set/", "square.stack.3d.up", reference.targetRef)
            } else {
                route = ("/factors/factor/", "function", reference.targetRef)
            }
        case "factor-set":
            route = ("/factors/set/", "square.stack.3d.up", reference.targetRef)
        case "product-group":
            return .productGroup(reference.targetRef, title: reference.label)
        case "product":
            return .product(reference.targetRef, title: reference.label)
        case "contract":
            return .productContract(reference.targetRef, title: reference.label)
        case "continuous-contract":
            return .productContract(reference.targetRef, title: reference.label, continuous: true)
        case "profile", "profile-revision":
            let value = reference.targetRef.split(separator: ":").last.map(String.init) ?? ""
            guard !value.isEmpty else { return nil }
            route = ("/profiles/", "person.crop.rectangle.stack", value)
        case "job", "task":
            let value = reference.targetRef.split(separator: ":", maxSplits: 1).last.map(String.init) ?? ""
            guard !value.isEmpty else { return nil }
            route = ("/jobs/", "doc.text.magnifyingglass", value)
        case "url":
            guard let url = ResearchDocumentReferenceRouter.webURL(for: reference) else {
                return nil
            }
            return ClientTab(
                id: "external-url:" + reference.id,
                title: reference.label,
                titleKey: nil,
                systemImage: "safari",
                content: .externalWeb(url)
            )
        default:
            route = nil
        }
        if let route,
           let encoded = route.target.addingPercentEncoding(
               withAllowedCharacters: .factortesterPathComponent
           ) {
            return .web(
                id: "reference:\(reference.kind):\(reference.targetRef)",
                title: reference.label,
                systemImage: route.symbol,
                path: route.page + encoded
            )
        }
        // Report links must use the same Web renderer as the report itself.
        // This gives evidence, obligations, requirements, frozen plans, files
        // and future catalog kinds a single Swift-owned tab seam.
        var components = URLComponents()
        components.path = "/reference"
        components.queryItems = [
            URLQueryItem(name: "kind", value: reference.kind),
            URLQueryItem(name: "target", value: reference.targetRef),
            URLQueryItem(name: "label", value: reference.label),
        ]
        let path = components.string ?? "/reference"
        return .web(
            id: "reference:\(reference.id)",
            title: reference.label,
            systemImage: ResearchDocumentReferenceCatalog.descriptor(
                for: reference.kind
            ).symbol,
            path: path
        )
    }

    var isHome: Bool { id == Self.home.id }

    var isPinnedLauncher: Bool {
        [
            "home", "research", "jobs", "web:factor-library", "web:products",
            "profiles", "account-settings",
        ].contains(id)
    }

    var isClosable: Bool { !isPinnedLauncher }
}

private extension CharacterSet {
    static let factortesterPathComponent = CharacterSet(
        charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    )
}
