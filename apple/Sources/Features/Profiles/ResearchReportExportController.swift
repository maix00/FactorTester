#if os(macOS)
import AppKit
import UniformTypeIdentifiers

@MainActor
enum ResearchReportExportController {
    static func export(
        format: ResearchReportExportFormat,
        reportRef: String,
        title: String
    ) throws {
        let source = try ResearchReportExportSource(reportRef: reportRef)
        let renderer: any ResearchReportRenderer
        switch format {
        case .markdown:
            renderer = ResearchReportMarkdownRenderer()
        case .pdf:
            renderer = ResearchReportPDFRenderer()
        }
        let data = try renderer.render(source)
        let panel = NSSavePanel()
        panel.title = L10n.text("导出研究报告")
        panel.nameFieldStringValue =
            "\(safeFilename(title)).\(format.extensionName)"
        panel.allowedContentTypes = [
            UTType(filenameExtension: format.extensionName) ?? .data
        ]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        try data.write(to: url, options: .atomic)
    }

    private static func safeFilename(_ value: String) -> String {
        let illegal = CharacterSet(charactersIn: "/:\\")
        let parts = value.components(separatedBy: illegal)
        let filename = parts.filter { !$0.isEmpty }.joined(separator: "-")
        return filename.isEmpty ? L10n.text("研究报告") : filename
    }
}
#endif
