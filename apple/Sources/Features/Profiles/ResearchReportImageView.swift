import CryptoKit
import Darwin
import SwiftUI
import WebKit
#if os(macOS)
import AppKit
#else
import UIKit
#endif

struct ResearchReportImageView: View {
    let asset: ResearchJournalAsset
    let reportRef: String

    @State private var data: Data?
    @State private var loadError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Group {
                if let data {
                    reportImage(data)
                } else if let loadError {
                    Label(loadError, systemImage: "photo.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ProgressView("正在校验并读取回测图…")
                        .frame(maxWidth: .infinity, minHeight: 120)
                }
            }
            .frame(maxWidth: .infinity)
            .background(
                Color.secondary.opacity(0.045),
                in: RoundedRectangle(cornerRadius: 9)
            )

            Text(asset.caption)
                .font(.caption)
                .foregroundStyle(.secondary)

            DisclosureGroup("图像回执") {
                Grid(alignment: .leading, horizontalSpacing: 12) {
                    receiptRow("内容哈希", shortHash(asset.contentHash))
                    receiptRow("媒体类型", asset.mediaType)
                    receiptRow(
                        "来源引用",
                        asset.provenanceRefs.joined(separator: "、")
                    )
                    receiptRow("序列留存", "报告默认仅保存图像，不保存完整净值点")
                }
                .font(.caption)
                .textSelection(.enabled)
                .padding(.top, 7)
            }
            .font(.caption.weight(.medium))
        }
        .task(id: "\(reportRef)|\(asset.contentHash)") {
            await load()
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(asset.altText.isEmpty ? asset.caption : asset.altText)
    }

    @ViewBuilder
    private func reportImage(_ data: Data) -> some View {
        if asset.mediaType == "image/svg+xml" {
            PassiveSVGWebView(data: data)
                .aspectRatio(16 / 9, contentMode: .fit)
                .frame(maxWidth: 760, maxHeight: 430)
        } else {
            platformImage(data)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 760, maxHeight: 520)
        }
    }

    private func receiptRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(LocalizedStringKey(label)).foregroundStyle(.secondary)
            if value.isEmpty {
                Text("无")
            } else {
                Text(verbatim: value)
            }
        }
    }

    private func load() async {
        do {
            data = try await ResearchReportAssetLoader.load(
                asset: asset,
                reportRef: reportRef
            )
            loadError = nil
        } catch {
            data = nil
            loadError = error.localizedDescription
        }
    }

    private func shortHash(_ value: String) -> String {
        "\(value.prefix(12))…\(value.suffix(8))"
    }
}

enum ResearchReportAssetLoader {
    static let maximumBytes = 8 * 1024 * 1024

    static func load(
        asset: ResearchJournalAsset,
        reportRef: String
    ) async throws -> Data {
        guard let reportURL = URL(string: reportRef),
              reportURL.isFileURL else {
            throw ResearchReportAssetError.missingReportRoot
        }
        let packageRoot = reportURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let assetURL = packageRoot
            .appendingPathComponent("assets", isDirectory: true)
            .appendingPathComponent(asset.filename, isDirectory: false)
        return try await Task.detached {
            let value = try PersonalWorkspaceAccessStore.withAccess(
                to: assetURL
            ) {
                try readBoundedRegularFile(assetURL)
            }
            let digest = SHA256.hash(data: value)
                .map { String(format: "%02x", $0) }
                .joined()
            guard digest == asset.contentHash else {
                throw ResearchReportAssetError.hashMismatch
            }
            if asset.mediaType == "image/svg+xml" {
                try validatePassiveSVG(value)
            }
            return value
        }.value
    }

    private static func readBoundedRegularFile(_ url: URL) throws -> Data {
        let descriptor: Int32 = url.withUnsafeFileSystemRepresentation {
            path -> Int32 in
            guard let path else { return -1 }
            return Darwin.open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW)
        }
        guard descriptor >= 0 else {
            throw ResearchReportAssetError.missingFile
        }
        let handle = FileHandle(
            fileDescriptor: descriptor,
            closeOnDealloc: true
        )
        defer { try? handle.close() }
        var metadata = Darwin.stat()
        guard Darwin.fstat(descriptor, &metadata) == 0,
              metadata.st_size >= 0,
              metadata.st_size <= maximumBytes,
              metadata.st_mode & S_IFMT == S_IFREG else {
            throw ResearchReportAssetError.invalidFile
        }
        let data = try handle.readToEnd() ?? Data()
        guard data.count <= maximumBytes else {
            throw ResearchReportAssetError.invalidFile
        }
        return data
    }

    private static func validatePassiveSVG(_ data: Data) throws {
        guard let value = String(data: data, encoding: .utf8) else {
            throw ResearchReportAssetError.unsafeSVG
        }
        let lower = value.lowercased()
        let forbidden = [
            "<script", "<foreignobject", "<!doctype", "<!entity",
            "javascript:",
        ]
        let externalReference =
            #"(?:href|src)\s*=\s*[\"']\s*(?:https?:|file:|javascript:)"#
        guard lower.trimmingCharacters(in: .whitespacesAndNewlines)
                .hasPrefix("<svg"),
              !forbidden.contains(where: lower.contains),
              lower.range(
                of: externalReference,
                options: .regularExpression
              ) == nil,
              lower.range(
                of: #"\son[a-z]+\s*="#,
                options: .regularExpression
              ) == nil else {
            throw ResearchReportAssetError.unsafeSVG
        }
    }
}

enum ResearchReportAssetError: LocalizedError {
    case missingReportRoot
    case missingFile
    case invalidFile
    case hashMismatch
    case unsafeSVG

    var errorDescription: String? {
        switch self {
        case .missingReportRoot:
            return L10n.text("研究报告没有可信的本地图片目录。")
        case .missingFile:
            return L10n.text("报告图片尚未保存到个人工作区。")
        case .invalidFile:
            return L10n.text("报告图片不是受支持的有界普通文件。")
        case .hashMismatch:
            return L10n.text("报告图片完整性校验失败。")
        case .unsafeSVG:
            return L10n.text("报告 SVG 含有脚本、外链或其他主动内容。")
        }
    }
}

private func platformImage(_ data: Data) -> Image {
#if os(macOS)
    if let image = NSImage(data: data) {
        Image(nsImage: image)
    } else {
        Image(systemName: "photo.badge.exclamationmark")
    }
#else
    if let image = UIImage(data: data) {
        Image(uiImage: image)
    } else {
        Image(systemName: "photo.badge.exclamationmark")
    }
#endif
}

#if os(macOS)
private struct PassiveSVGWebView: NSViewRepresentable {
    let data: Data

    func makeNSView(context: Context) -> WKWebView {
        configuredWebView()
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        load(webView)
    }

    private func configuredWebView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.underPageBackgroundColor = .clear
        view.setValue(false, forKey: "drawsBackground")
        load(view)
        return view
    }

    private func load(_ webView: WKWebView) {
        webView.load(
            data,
            mimeType: "image/svg+xml",
            characterEncodingName: "utf-8",
            baseURL: URL(fileURLWithPath: "/")
        )
    }
}
#else
private struct PassiveSVGWebView: UIViewRepresentable {
    let data: Data

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = .clear
        load(view)
        return view
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        load(webView)
    }

    private func load(_ webView: WKWebView) {
        webView.load(
            data,
            mimeType: "image/svg+xml",
            characterEncodingName: "utf-8",
            baseURL: URL(fileURLWithPath: "/")
        )
    }
}
#endif
