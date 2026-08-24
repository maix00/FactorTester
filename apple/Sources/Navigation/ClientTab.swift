import Foundation

enum ClientTabContent {
    case module(Module)
    case adapter(ClientAdapterModel)
    case web(path: String)
    case externalWeb(URL)
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

    /// The selected execution service is part of a backend object's identity.
    /// Recover it from an existing Web route so a child reference opened from a
    /// Job tab can keep the same scope even when its href omits `port`.
    var servicePort: Int? {
        switch content {
        case .web(let path):
            return Self.servicePort(from: path)
        case .testJob(let job):
            return Self.validServicePort(job.port)
        default:
            return nil
        }
    }

    static func module(_ module: Module) -> ClientTab {
        // Keep this mapping for native capability sheets and compatibility
        // links.  The main client shell no longer maps the backend module
        // catalog into a Swift sidebar; Web owns that navigation.
        switch module.id {
        case "research": return .research
        case "jobs": return .jobs
        case "ic-test": return .icTest()
        case "backtest": return .backtest()
        case "manager": return .manager
        default: break
        }
        let opensAsFreshTab = module.tabBehavior == "new"
            || ["docs", "sqlite_web"].contains(module.id)
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
        title: "测试",
        titleKey: "测试",
        systemImage: "checklist",
        content: .jobs
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

    static func factorDetail(_ target: String, kind: String, title: String? = nil) -> ClientTab {
        let routeKind: String
        let symbol: String
        switch kind {
        case "family":
            routeKind = "family"
            symbol = "function"
        case "set":
            routeKind = "set"
            symbol = "square.stack.3d.up"
        default:
            routeKind = "factor"
            symbol = "function"
        }
        let encoded = target.addingPercentEncoding(
            withAllowedCharacters: .factortesterPathComponent
        ) ?? target
        return .web(
            id: "factor-\(routeKind):\(target)",
            title: title ?? target,
            titleKey: nil,
            systemImage: symbol,
            path: "/factors/\(routeKind)/\(encoded)"
        )
    }

    /// Resolve an embedded Manager navigation into a Swift-owned destination.
    /// Keeping this pure makes the Web-to-Swift tab contract independently
    /// testable instead of burying route identity inside a SwiftUI callback.
    static func embeddedNavigationDestination(
        for path: String,
        sourceServicePort: Int? = nil
    ) -> ClientTab? {
        guard path.hasPrefix("/"), !path.hasPrefix("//"),
              let components = URLComponents(string: path),
              components.scheme == nil,
              components.host == nil else { return nil }
        let pathname = components.path
        let inheritedPort = validServicePort(sourceServicePort)
        let routePort = servicePort(from: path) ?? inheritedPort

        if path.hasPrefix("/research/") {
            return .researchReport(path: path)
        }
        if pathname.hasPrefix("/jobs/") {
            return .web(
                id: scopedIdentity(
                    "job-detail:\(path)",
                    servicePort: routePort
                ),
                title: "测试任务详情",
                titleKey: "测试任务详情",
                systemImage: "doc.text.magnifyingglass",
                path: path
            )
        }
        if pathname == "/ic-test" {
            return .icTest()
        }
        if pathname == "/backtest" {
            return .backtest()
        }
        if pathname == "/reference" {
            let kind = ResearchDocumentReferenceCatalog.canonicalKind(
                queryValue("kind", in: components) ?? "reference"
            )
            let target = queryValue("target", in: components) ?? path
            let label = referenceLabel(
                kind: kind,
                label: queryValue("label", in: components) ?? "引用详情"
            )
            return .web(
                id: referenceIdentity(
                    kind: kind,
                    target: target,
                    servicePort: routePort
                ),
                title: label,
                titleKey: nil,
                systemImage: ResearchDocumentReferenceCatalog
                    .descriptor(for: kind).symbol,
                path: path
            )
        }
        if pathname == "/factor-series" {
            return .web(
                id: "factor-series:\(path)",
                title: "因子序列",
                titleKey: "因子序列",
                systemImage: "waveform.path.ecg",
                path: path
            )
        }

        let source = queryValue("source", in: components) == "local"
            ? "local" : nil
        if pathname.hasPrefix("/products/group/") {
            return .productGroup(
                decodedRouteTarget(pathname, prefix: "/products/group/"),
                source: source
            )
        }
        if pathname.hasPrefix("/products/product/") {
            let target = decodedRouteTarget(
                pathname, prefix: "/products/product/"
            )
            return .product(target, title: target, source: source)
        }
        if pathname.hasPrefix("/products/contract/")
            || pathname.hasPrefix("/products/continuous-contract/") {
            let continuous = pathname.hasPrefix(
                "/products/continuous-contract/"
            )
            let prefix = continuous
                ? "/products/continuous-contract/" : "/products/contract/"
            return .productContract(
                decodedRouteTarget(pathname, prefix: prefix),
                continuous: continuous,
                source: source
            )
        }
        for (prefix, kind) in [
            ("/factors/family/", "family"),
            ("/factors/factor/", "factor"),
            ("/factors/set/", "set"),
        ] where pathname.hasPrefix(prefix) {
            return .factorDetail(
                decodedRouteTarget(pathname, prefix: prefix),
                kind: kind
            )
        }
        return nil
    }

    static func reference(_ reference: ResearchDocumentTypedLink) -> ClientTab? {
        let kind = ResearchDocumentReferenceCatalog.canonicalKind(reference.kind)
        let referencePort = servicePort(in: reference.detailFields)
        let referenceServerID = serviceServerID(in: reference.detailFields)
        let route: (page: String, symbol: String, target: String)?
        switch kind.replacingOccurrences(of: "_", with: "-") {
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
        case "profile":
            let value = reference.targetRef.split(separator: ":").last.map(String.init) ?? ""
            guard !value.isEmpty else { return nil }
            route = ("/profiles/", "person.crop.rectangle.stack", value)
        case "job", "task":
            let value = reference.targetRef.split(separator: ":", maxSplits: 1).last.map(String.init) ?? ""
            guard !value.isEmpty else { return nil }
            guard let encodedJob = value.addingPercentEncoding(
                withAllowedCharacters: .factortesterPathComponent
            ) else { return nil }
            if let referencePort {
                return referenceWeb(
                    kind: kind,
                    target: reference.targetRef,
                    label: reference.label,
                    systemImage: "doc.text.magnifyingglass",
                    path: jobReferencePath(
                        port: referencePort, job: encodedJob,
                        serverID: referenceServerID
                    ),
                    servicePort: referencePort,
                    serviceServerID: referenceServerID
                )
            }
            if !referenceServerID.isEmpty {
                return referenceWeb(
                    kind: kind,
                    target: reference.targetRef,
                    label: reference.label,
                    systemImage: "doc.text.magnifyingglass",
                    path: jobReferencePath(
                        port: nil, job: encodedJob,
                        serverID: referenceServerID
                    ),
                    serviceServerID: referenceServerID
                )
            }
            route = ("/jobs/", "doc.text.magnifyingglass", value)
        case "url":
            guard let url = ResearchDocumentReferenceRouter.webURL(for: reference) else {
                return nil
            }
            return referenceExternalWeb(
                kind: kind,
                target: reference.targetRef,
                label: reference.label,
                url: url,
            )
        default:
            route = nil
        }
        if let route,
           let encoded = route.target.addingPercentEncoding(
               withAllowedCharacters: .factortesterPathComponent
           ) {
            return referenceWeb(
                kind: kind,
                target: reference.targetRef,
                label: reference.label,
                systemImage: route.symbol,
                path: route.page + encoded,
            )
        }
        // Report links must use the same Web renderer as the report itself.
        // This gives evidence, obligations, requirements, frozen plans, files
        // and future catalog kinds a single Swift-owned tab seam.
        let displayLabel = referenceLabel(
            kind: kind,
            label: reference.label
        )
        var components = URLComponents()
        components.path = "/reference"
        components.queryItems = [
            URLQueryItem(name: "kind", value: kind),
            URLQueryItem(name: "target", value: reference.targetRef),
            URLQueryItem(name: "label", value: displayLabel),
        ]
        if let componentID = reference.componentID, !componentID.isEmpty {
            components.queryItems?.append(
                URLQueryItem(name: "component_id", value: String(componentID.prefix(256)))
            )
        }
        if let detailPayload = referenceDetailPayload(reference.detailFields) {
            components.queryItems?.append(
                URLQueryItem(name: "details", value: detailPayload)
            )
        }
        if !referenceServerID.isEmpty {
            components.queryItems?.append(
                URLQueryItem(name: "server_id", value: referenceServerID)
            )
        }
        let path = components.string ?? "/reference"
        return referenceWeb(
            kind: kind,
            target: reference.targetRef,
            label: displayLabel,
            systemImage: ResearchDocumentReferenceCatalog.descriptor(for: kind).symbol,
            path: path,
            servicePort: referencePort,
            serviceServerID: referenceServerID
        )
    }

    /// Every report hyperlink gets one Swift-owned tab seam. Web remains the
    /// renderer; Swift owns identity, lifecycle, and routing.
    private static func referenceWeb(
        kind: String,
        target: String,
        label: String,
        systemImage: String,
        path: String,
        servicePort: Int? = nil,
        serviceServerID: String = "",
    ) -> ClientTab {
        .web(
            id: referenceIdentity(
                kind: kind,
                target: target,
                servicePort: servicePort,
                serviceServerID: serviceServerID
            ),
            title: label,
            titleKey: nil,
            systemImage: systemImage,
            path: path,
        )
    }

    private static func referenceExternalWeb(
        kind: String,
        target: String,
        label: String,
        url: URL,
    ) -> ClientTab {
        ClientTab(
            id: "reference:\(kind):\(target)",
            title: label,
            titleKey: nil,
            systemImage: "safari",
            content: .externalWeb(url),
        )
    }

    /// Keep the generic Web reference page useful when its detail endpoint is
    /// unavailable, without putting an unbounded report binding into a URL.
    /// The object identity still comes from `kind` and `target`; these fields
    /// are only a bounded presentation fallback.
    private static func referenceDetailPayload(
        _ fields: [ResearchDocumentReferenceField]
    ) -> String? {
        let bounded = fields.prefix(16).map { field in
            [
                "name": String(field.name.prefix(128)),
                "value": String(field.value.prefix(512)),
            ]
        }
        guard !bounded.isEmpty,
              let data = try? JSONSerialization.data(
                  withJSONObject: bounded, options: []
              ),
              data.count <= 8_192 else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func referenceIdentity(
        kind: String,
        target: String,
        servicePort: Int?,
        serviceServerID: String = ""
    ) -> String {
        let canonicalKind = ResearchDocumentReferenceCatalog.canonicalKind(kind)
        let canonicalTarget = canonicalReferenceTarget(
            kind: canonicalKind,
            target: target
        )
        let identity = scopedIdentity(
            "reference:\(canonicalKind):\(canonicalTarget)",
            servicePort: canonicalKind == "run_spec" ? nil : servicePort
        )
        guard canonicalKind != "run_spec", !serviceServerID.isEmpty else {
            return identity
        }
        return "\(identity):server:\(serviceServerID)"
    }

    private static func canonicalReferenceTarget(
        kind: String,
        target: String
    ) -> String {
        guard kind == "run_spec" else { return target }
        let lowered = target.lowercased()
        for prefix in [
            "runspec:sha256:", "run-spec:sha256:", "run_spec:sha256:",
        ] where lowered.hasPrefix(prefix) {
            return "sha256:" + String(lowered.dropFirst(prefix.count))
        }
        return target
    }

    private static func referenceLabel(kind: String, label: String) -> String {
        ResearchDocumentReferenceCatalog.canonicalKind(kind) == "run_spec"
            ? L10n.text("运行配置") : label
    }

    private static func scopedIdentity(
        _ identity: String,
        servicePort: Int?
    ) -> String {
        guard let port = validServicePort(servicePort) else { return identity }
        return "\(identity):port:\(port)"
    }

    private static func servicePort(
        in fields: [ResearchDocumentReferenceField]
    ) -> Int? {
        guard let raw = fields.first(where: { $0.name == "port" })?.value
        else { return nil }
        return validServicePort(Int(raw))
    }

    private static func serviceServerID(
        in fields: [ResearchDocumentReferenceField]
    ) -> String {
        fields.first(where: { $0.name == "server_id" })?.value
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private static func jobReferencePath(
        port: Int?, job: String, serverID: String
    ) -> String {
        let path = port.map { "/jobs/\($0)/\(job)" }
            ?? "/jobs/\(job)"
        guard !serverID.isEmpty else { return path }
        var components = URLComponents(string: path) ?? URLComponents()
        components.queryItems = [URLQueryItem(name: "server_id", value: serverID)]
        return components.string ?? path
    }

    private static func servicePort(from path: String) -> Int? {
        guard let components = URLComponents(string: path) else { return nil }
        if let explicit = queryValue("port", in: components),
           let port = validServicePort(Int(explicit)) {
            return port
        }
        if let details = queryValue("details", in: components),
           let data = details.data(using: .utf8),
           let values = try? JSONSerialization.jsonObject(with: data)
                as? [[String: Any]],
           let raw = values.first(where: { $0["name"] as? String == "port" })?["value"] {
            return validServicePort(Int(String(describing: raw)))
        }
        let segments = components.path.split(separator: "/")
        guard segments.count >= 3, segments[0] == "jobs" else { return nil }
        return validServicePort(Int(segments[1]))
    }

    private static func validServicePort(_ value: Int?) -> Int? {
        guard let value, (1...65_535).contains(value) else { return nil }
        return value
    }

    private static func queryValue(
        _ name: String,
        in components: URLComponents
    ) -> String? {
        components.queryItems?.first(where: { $0.name == name })?.value
    }

    private static func decodedRouteTarget(
        _ path: String,
        prefix: String
    ) -> String {
        let encoded = String(path.dropFirst(prefix.count))
        return encoded.removingPercentEncoding ?? encoded
    }

    var isPinnedLauncher: Bool {
        [
            "research", "jobs", "web:factor-library", "web:products",
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
