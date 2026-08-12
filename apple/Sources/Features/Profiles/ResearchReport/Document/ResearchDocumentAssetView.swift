import CryptoKit
import Darwin
import SwiftUI
import WebKit

struct ResearchDocumentAssetView: View {
    let asset: ResearchDocumentAsset
    let reportRef: String

    @State private var svgData: Data?
    @State private var rasterImage: CGImage?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Group {
                if let svgData {
                    DocumentPassiveSVGWebView(data: svgData)
                        .aspectRatio(16 / 9, contentMode: .fit)
                        .frame(maxWidth: 760, maxHeight: 430)
                } else if let rasterImage {
                    Image(decorative: rasterImage, scale: 1)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 760, maxHeight: 520)
                } else if let error {
                    Label(error, systemImage: "photo.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ProgressView(L10n.text("正在读取研究图像…"))
                        .frame(maxWidth: .infinity, minHeight: 120)
                }
            }
            .frame(maxWidth: .infinity)
            .background(Color.secondary.opacity(0.045), in: RoundedRectangle(cornerRadius: 8))
            if !asset.caption.isEmpty {
                Text(asset.caption).font(.caption).foregroundStyle(.secondary)
            }
        }
        .task(id: "\(reportRef)|\(asset.assetRef)") { await load() }
        .accessibilityLabel(asset.altText.isEmpty ? asset.caption : asset.altText)
    }

    @MainActor
    private func load() async {
        do {
            let data = try await ResearchDocumentAssetLoader.load(
                asset: asset, reportRef: reportRef
            )
            if asset.mediaType == "image/svg+xml" {
                svgData = data
                rasterImage = nil
            } else {
                rasterImage = try await ResearchDocumentRasterImageDecoder.decode(data)
                svgData = nil
            }
            error = nil
        } catch {
            svgData = nil
            rasterImage = nil
            self.error = error.localizedDescription
        }
    }
}

enum ResearchDocumentAssetLoader {
    private static let maximumBytes = 8 * 1024 * 1024

    static func load(
        asset: ResearchDocumentAsset,
        reportRef: String,
        jobCacheRoot: URL? = nil
    ) async throws -> Data {
        guard let reportURL = URL(string: reportRef), reportURL.isFileURL else {
            throw ResearchDocumentAssetError.invalidRoot
        }
        guard asset.filename == URL(fileURLWithPath: asset.filename).lastPathComponent,
              !asset.filename.isEmpty else { throw ResearchDocumentAssetError.invalidFile }
        let file = try resolvedFile(
            asset,
            reportURL: reportURL,
            jobCacheRoot: jobCacheRoot ?? defaultJobCacheRoot
        )
        return try await Task.detached {
            let value: Data
            switch file.access {
            case .personalWorkspace:
                value = try PersonalWorkspaceAccessStore.withAccess(to: file.url) {
                    try read(file.url)
                }
            case .appManagedJobCache:
                value = try read(file.url)
            }
            if !asset.contentHash.isEmpty {
                let actual = SHA256.hash(data: value).map { String(format: "%02x", $0) }.joined()
                guard actual == asset.contentHash else {
                    throw ResearchDocumentAssetError.hashMismatch
                }
            }
            if asset.mediaType == "image/svg+xml" { try validateSVG(value) }
            return value
        }.value
    }

    static func resolvedFile(
        _ asset: ResearchDocumentAsset,
        reportURL: URL,
        jobCacheRoot: URL
    ) throws -> ResearchDocumentAssetFile {
        let packageRoot = reportURL.deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
        if !asset.localRef.isEmpty {
            guard !asset.localRef.hasPrefix("/"),
                  !asset.localRef.split(separator: "/").contains("..") else {
                throw ResearchDocumentAssetError.invalidFile
            }
            let url = asset.localRef.split(separator: "/").reduce(packageRoot) {
                $0.appendingPathComponent(String($1))
            }
            return .init(url: url, access: .personalWorkspace)
        }
        if let jobID = jobID(from: asset.externalRef) {
            let url = jobCacheRoot
                .appendingPathComponent(jobID, isDirectory: true)
                .appendingPathComponent(asset.filename, isDirectory: false)
            return .init(url: url, access: .appManagedJobCache)
        }
        let url = packageRoot.appendingPathComponent("assets", isDirectory: true)
            .appendingPathComponent(asset.filename, isDirectory: false)
        return .init(url: url, access: .personalWorkspace)
    }

    private static var defaultJobCacheRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/jobs", isDirectory: true)
    }

    private static func jobID(from reference: String) -> String? {
        guard let value = URL(string: reference),
              value.scheme == "factortester-artifact", value.host == "jobs" else {
            return nil
        }
        let parts = value.pathComponents.filter { $0 != "/" }
        guard parts.count == 2,
              parts[0].range(of: #"^[A-Za-z0-9._-]{1,128}$"#,
                             options: .regularExpression) != nil else {
            return nil
        }
        return parts[0]
    }

    private static func read(_ url: URL) throws -> Data {
        let descriptor: Int32 = url.withUnsafeFileSystemRepresentation { path in
            guard let path else { return -1 }
            return Darwin.open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW)
        }
        guard descriptor >= 0 else { throw ResearchDocumentAssetError.missingFile }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var metadata = Darwin.stat()
        guard Darwin.fstat(descriptor, &metadata) == 0,
              metadata.st_size >= 0, metadata.st_size <= maximumBytes,
              metadata.st_mode & S_IFMT == S_IFREG else {
            throw ResearchDocumentAssetError.invalidFile
        }
        return try handle.readToEnd() ?? Data()
    }

    static func validateSVG(_ data: Data) throws {
        guard let value = String(data: data, encoding: .utf8) else {
            throw ResearchDocumentAssetError.unsafeSVG
        }
        let lower = value.lowercased()
        let forbidden = ["<script", "<foreignobject", "<!doctype", "<!entity", "javascript:"]
        let external = #"(?:href|src)\s*=\s*["']\s*(?:https?:|file:|javascript:)"#
        guard lower.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("<svg"),
              !forbidden.contains(where: lower.contains),
              lower.range(of: external, options: .regularExpression) == nil,
              lower.range(of: #"\son[a-z]+\s*="#, options: .regularExpression) == nil else {
            throw ResearchDocumentAssetError.unsafeSVG
        }
    }
}

struct ResearchDocumentAssetFile {
    enum Access: Equatable {
        case personalWorkspace
        case appManagedJobCache
    }

    let url: URL
    let access: Access
}

enum ResearchDocumentAssetError: LocalizedError {
    case invalidRoot, missingFile, invalidFile, hashMismatch, unsafeSVG

    var errorDescription: String? {
        switch self {
        case .invalidRoot: return L10n.text("研究报告没有可信的本地图片目录")
        case .missingFile: return L10n.text("报告图片尚未保存到个人工作区")
        case .invalidFile: return L10n.text("报告图片不是受支持的有界普通文件")
        case .hashMismatch: return L10n.text("报告图片完整性校验失败")
        case .unsafeSVG: return L10n.text("报告 SVG 含有脚本、外链或主动内容")
        }
    }
}

#if os(macOS)
struct DocumentPassiveSVGWebView: NSViewRepresentable {
    let data: Data
    func makeCoordinator() -> SVGLoadCoordinator { .init() }
    func makeNSView(context: Context) -> WKWebView { makeView() }
    func updateNSView(_ view: WKWebView, context: Context) {
        guard !context.coordinator.loaded else { return }
        context.coordinator.loaded = true
        view.load(data, mimeType: "image/svg+xml", characterEncodingName: "utf-8",
                  baseURL: URL(fileURLWithPath: "/"))
    }
    private func makeView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.underPageBackgroundColor = .clear
        view.setValue(false, forKey: "drawsBackground")
        return view
    }
}
#else
struct DocumentPassiveSVGWebView: UIViewRepresentable {
    let data: Data
    func makeCoordinator() -> SVGLoadCoordinator { .init() }
    func makeUIView(context: Context) -> WKWebView { makeView() }
    func updateUIView(_ view: WKWebView, context: Context) {
        guard !context.coordinator.loaded else { return }
        context.coordinator.loaded = true
        view.load(data, mimeType: "image/svg+xml", characterEncodingName: "utf-8",
                  baseURL: URL(fileURLWithPath: "/"))
    }
    private func makeView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        return WKWebView(frame: .zero, configuration: configuration)
    }
}
#endif

final class SVGLoadCoordinator {
    var loaded = false
}
