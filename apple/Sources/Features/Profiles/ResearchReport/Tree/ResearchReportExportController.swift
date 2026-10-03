#if os(macOS)
import AppKit
import UniformTypeIdentifiers

@MainActor
enum ResearchReportExportController {
    static func export(
        format: ResearchReportExportFormat,
        profileID: String,
        reportWorkspaceID: String,
        branchID: String,
        title: String
    ) async throws {
        guard !profileID.isEmpty,
              !reportWorkspaceID.isEmpty,
              !branchID.isEmpty else {
            throw ResearchReportExportError.missingReportIdentity
        }
        let panel = NSSavePanel()
        panel.title = L10n.text("导出研究报告")
        panel.nameFieldStringValue =
            "\(safeFilename(title)).\(format.extensionName)"
        panel.allowedContentTypes = [
            UTType(filenameExtension: format.extensionName) ?? .data
        ]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        try await BundledRuntimeActivator.waitUntilReady()
        let request = ResearchReportExportRequest(
            profileID: profileID,
            reportWorkspaceID: reportWorkspaceID,
            branchID: branchID,
            format: format
        )
        _ = try await ReleaseCommand.runObject(
            request.arguments(output: url),
            executable: ClientCLIResolution.executable(),
            timeout: .seconds(120)
        )
    }

    private static func safeFilename(_ value: String) -> String {
        let illegal = CharacterSet(charactersIn: "/:\\")
        let parts = value.components(separatedBy: illegal)
        let filename = parts.filter { !$0.isEmpty }.joined(separator: "-")
        return filename.isEmpty ? L10n.text("研究报告") : filename
    }
}
#endif
