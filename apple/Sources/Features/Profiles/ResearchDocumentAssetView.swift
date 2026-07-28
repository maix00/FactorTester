import CryptoKit
import Darwin
import SwiftUI
import WebKit
#if os(macOS)
import AppKit
#else
import UIKit
#endif

struct ResearchDocumentAssetView: View {
    let asset: ResearchDocumentAsset
    let reportRef: String

    @State private var data: Data?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Group {
                if let data {
                    image(data)
                } else if let error {
                    Label(error, systemImage: "photo.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ProgressView("正在读取研究图像…")
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

    @ViewBuilder
    private func image(_ data: Data) -> some View {
        if asset.mediaType == "image/svg+xml" {
            DocumentPassiveSVGWebView(data: data)
                .aspectRatio(16 / 9, contentMode: .fit)
                .frame(maxWidth: 760, maxHeight: 430)
        } else {
            documentPlatformImage(data)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 760, maxHeight: 520)
        }
    }

    private func load() async {
        do {
            data = try await ResearchDocumentAssetLoader.load(
                asset: asset, reportRef: reportRef
            )
            error = nil
        } catch {
            data = nil
            self.error = error.localizedDescription
        }
    }
}

enum ResearchDocumentAssetLoader {
    private static let maximumBytes = 8 * 1024 * 1024

    static func load(
        asset: ResearchDocumentAsset, reportRef: String
    ) async throws -> Data {
        guard let reportURL = URL(string: reportRef), reportURL.isFileURL else {
            throw ResearchDocumentAssetError.invalidRoot
        }
        guard asset.filename == URL(fileURLWithPath: asset.filename).lastPathComponent,
              !asset.filename.isEmpty else { throw ResearchDocumentAssetError.invalidFile }
        let fileURL = reportURL.deletingLastPathComponent()
            .appendingPathComponent("assets", isDirectory: true)
            .appendingPathComponent(asset.filename, isDirectory: false)
        return try await Task.detached {
            let value = try PersonalWorkspaceAccessStore.withAccess(to: fileURL) {
                try read(fileURL)
            }
            if let digest = asset.assetRef.split(separator: ":").last,
               asset.assetRef.hasPrefix("report-asset:sha256:") {
                let actual = SHA256.hash(data: value).map { String(format: "%02x", $0) }.joined()
                guard actual == digest else { throw ResearchDocumentAssetError.hashMismatch }
            }
            if asset.mediaType == "image/svg+xml" { try validateSVG(value) }
            return value
        }.value
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

    private static func validateSVG(_ data: Data) throws {
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

private func documentPlatformImage(_ data: Data) -> Image {
#if os(macOS)
    Image(nsImage: NSImage(data: data) ?? NSImage())
#else
    Image(uiImage: UIImage(data: data) ?? UIImage())
#endif
}

#if os(macOS)
private struct DocumentPassiveSVGWebView: NSViewRepresentable {
    let data: Data
    func makeNSView(context: Context) -> WKWebView { makeView() }
    func updateNSView(_ view: WKWebView, context: Context) { view.load(data, mimeType: "image/svg+xml", characterEncodingName: "utf-8", baseURL: URL(fileURLWithPath: "/")) }
    private func makeView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.underPageBackgroundColor = .clear
        view.setValue(false, forKey: "drawsBackground")
        view.load(data, mimeType: "image/svg+xml", characterEncodingName: "utf-8", baseURL: URL(fileURLWithPath: "/"))
        return view
    }
}
#else
private struct DocumentPassiveSVGWebView: UIViewRepresentable {
    let data: Data
    func makeUIView(context: Context) -> WKWebView { makeView() }
    func updateUIView(_ view: WKWebView, context: Context) { view.load(data, mimeType: "image/svg+xml", characterEncodingName: "utf-8", baseURL: URL(fileURLWithPath: "/")) }
    private func makeView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        return WKWebView(frame: .zero, configuration: configuration)
    }
}
#endif
