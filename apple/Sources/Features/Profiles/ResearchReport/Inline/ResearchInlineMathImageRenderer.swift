#if os(macOS)
import AppKit
import WebKit

struct ResearchInlineMathRendered {
    let image: NSImage
    let baselineFromTop: CGFloat
}

@MainActor
final class ResearchInlineMathImageRenderer: NSObject, WKNavigationDelegate {
    static let shared = ResearchInlineMathImageRenderer()

    private struct Request {
        let key: String
        let latex: String
        let fontSize: CGFloat
    }

    private final class Box: NSObject {
        let value: ResearchInlineMathRendered

        init(_ value: ResearchInlineMathRendered) {
            self.value = value
        }
    }

    private let cache = NSCache<NSString, Box>()
    private var waiters: [String: [(ResearchInlineMathRendered?) -> Void]] = [:]
    private var queue: [Request] = []
    private var active: Request?
    private lazy var webView: WKWebView = makeWebView()

    nonisolated static func key(latex: String, fontSize: CGFloat) -> String {
        "\(fontSize.rounded(.toNearestOrEven))\u{1f}\(latex)"
    }

    func request(
        latex: String,
        fontSize: CGFloat,
        completion: @escaping (ResearchInlineMathRendered?) -> Void
    ) {
        let key = Self.key(latex: latex, fontSize: fontSize)
        if let rendered = cache.object(forKey: key as NSString)?.value {
            completion(rendered)
            return
        }
        waiters[key, default: []].append(completion)
        guard waiters[key]?.count == 1 else { return }
        queue.append(.init(key: key, latex: latex, fontSize: fontSize))
        startNext()
    }

    private func startNext() {
        guard active == nil, !queue.isEmpty else { return }
        let request = queue.removeFirst()
        active = request
        webView.loadHTMLString(
            ResearchInlineMathDocument.html(
                latex: request.latex,
                fontSize: request.fontSize
            ),
            baseURL: BundledKaTeXRuntime.baseURL
        )
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard active != nil else { return }
        Task { [weak self, weak webView] in
            guard let self, let webView else { return }
            do {
                let value = try await webView.callAsyncJavaScript(
                    ResearchInlineMathDocument.metricsScript,
                    arguments: [:],
                    in: nil,
                    contentWorld: .page
                )
                self.snapshot(value as? [String: Any])
            } catch {
                self.finish(nil)
            }
        }
    }

    private func snapshot(_ value: [String: Any]?) {
        guard let value,
              let x = number(value["x"]),
              let y = number(value["y"]),
              let width = number(value["width"]),
              let height = number(value["height"]),
              let baseline = number(value["baseline"]),
              width > 0, height > 0 else {
            finish(nil)
            return
        }
        let configuration = WKSnapshotConfiguration()
        configuration.rect = CGRect(
            x: x, y: y, width: min(width, 2048), height: min(height, 256)
        )
        webView.takeSnapshot(with: configuration) { [weak self] image, _ in
            guard let self else { return }
            guard let image else {
                self.finish(nil)
                return
            }
            image.size = configuration.rect.size
            image.isTemplate = true
            self.finish(.init(
                image: image,
                baselineFromTop: min(max(0, baseline), height)
            ))
        }
    }

    private func finish(_ rendered: ResearchInlineMathRendered?) {
        guard let request = active else { return }
        if let rendered {
            cache.setObject(Box(rendered), forKey: request.key as NSString)
        }
        let completions = waiters.removeValue(forKey: request.key) ?? []
        active = nil
        completions.forEach { $0(rendered) }
        startNext()
    }

    private func makeWebView() -> WKWebView {
        let view = WKWebView(frame: CGRect(x: 0, y: 0, width: 2048, height: 256))
        view.navigationDelegate = self
        view.underPageBackgroundColor = .clear
        view.setValue(false, forKey: "drawsBackground")
        return view
    }

    private func number(_ value: Any?) -> CGFloat? {
        (value as? NSNumber).map(CGFloat.init(truncating:))
    }
}
#endif
