import Foundation

enum ResearchReportExportFormat: String, CaseIterable {
    case markdown
    case pdf

    var extensionName: String {
        switch self {
        case .markdown: return "md"
        case .pdf: return "pdf"
        }
    }

    var localizedTitle: String {
        switch self {
        case .markdown: return L10n.text("导出为 Markdown")
        case .pdf: return L10n.text("导出为 PDF")
        }
    }
}

struct ResearchReportExportSource {
    let headURL: URL
    let markdownURL: URL

    init(reportRef: String) throws {
        guard let headURL = URL(string: reportRef), headURL.isFileURL else {
            throw ResearchReportExportError.invalidReportReference
        }
        self.headURL = headURL
        let reportRoot = headURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        markdownURL = reportRoot.appendingPathComponent("REPORT.md")
    }

    func markdownData() throws -> Data {
        try PersonalWorkspaceAccessStore.withAccess(to: markdownURL) {
            guard FileManager.default.fileExists(atPath: markdownURL.path) else {
                throw ResearchReportExportError.materializedMarkdownMissing
            }
            return try Data(contentsOf: markdownURL)
        }
    }
}

protocol ResearchReportRenderer {
    func render(_ source: ResearchReportExportSource) throws -> Data
}

struct ResearchReportMarkdownRenderer: ResearchReportRenderer {
    func render(_ source: ResearchReportExportSource) throws -> Data {
        try source.markdownData()
    }
}

enum ResearchReportExportError: LocalizedError {
    case invalidReportReference
    case materializedMarkdownMissing
    case pdfContextUnavailable

    var errorDescription: String? {
        switch self {
        case .invalidReportReference:
            return L10n.text("研究报告本地引用无效")
        case .materializedMarkdownMissing:
            return L10n.text("研究报告尚未生成 Markdown")
        case .pdfContextUnavailable:
            return L10n.text("无法创建 PDF 文档")
        }
    }
}
