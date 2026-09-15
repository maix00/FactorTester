import Foundation

/// The report page asks the macOS client to export the report.  The manager
/// renders Markdown from the tree it holds; the PDF renderer is a client
/// binary and a locally-exportable report also has its tree on this machine,
/// so the client decides whether to export natively or fall back to the
/// server export.
enum ResearchReportExportMessage {
    static let handlerName = "researchReportExport"

    struct Request {
        let publicationID: String
        let serverRef: String
        /// The branch owner when the report belongs to another profile.
        let targetRef: String
        let format: ResearchReportExportFormat
        let title: String

        /// ``server_ref`` is ``profile:package:branch``.
        var profileID: String {
            serverRef.split(separator: ":", omittingEmptySubsequences: false)
                .first.map(String.init) ?? ""
        }

        var workPackageID: String {
            let parts = serverRef.split(
                separator: ":", omittingEmptySubsequences: false,
            )
            return parts.count == 3 ? String(parts[1]) : ""
        }

        var branchID: String {
            let parts = serverRef.split(
                separator: ":", omittingEmptySubsequences: false,
            )
            return parts.count == 3 ? String(parts[2]) : ""
        }
    }

    static func decode(_ body: Any) -> Request? {
        guard let payload = body as? [String: Any],
              let rawFormat = payload["format"] as? String,
              let format = ResearchReportExportFormat(rawValue: rawFormat) else {
            return nil
        }
        let serverRef = String(payload["server_ref"] as? String ?? "")
        guard !serverRef.isEmpty else { return nil }
        return Request(
            publicationID: String(payload["publication_id"] as? String ?? ""),
            serverRef: serverRef,
            targetRef: String(payload["target_ref"] as? String ?? ""),
            format: format,
            title: String(payload["title"] as? String ?? ""),
        )
    }
}
