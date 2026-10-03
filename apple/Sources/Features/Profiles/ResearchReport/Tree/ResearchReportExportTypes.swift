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

struct ResearchReportExportRequest {
    let profileID: String
    let reportWorkspaceID: String
    let branchID: String
    let format: ResearchReportExportFormat

    func arguments(output: URL) -> [String] {
        [
            "report", "export",
            "--profile", profileID,
            "--report-workspace-id", reportWorkspaceID,
            "--branch-id", branchID,
            "--format", format.rawValue,
            "--output", output.path,
            "--force",
            "--json",
        ]
    }
}

enum ResearchReportExportError: LocalizedError {
    case missingReportIdentity

    var errorDescription: String? {
        switch self {
        case .missingReportIdentity:
            return L10n.text("研究报告缺少可导出的 Profile、研究或分支标识")
        }
    }
}
