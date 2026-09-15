import Foundation

/// The report page asks the macOS client to export the report.  The manager
/// renders Markdown from the report it holds; the PDF renderer is a client
/// binary and a locally-exportable report also has its tree on this machine,
/// so the client decides whether to export natively or fall back to the
/// manager export.
enum ResearchReportExportMessage {
    static let handlerName = "researchReportExport"

    struct Request {
        let publicationID: String
        let profileRef: String
        let workPackageID: String
        let branchID: String
        let ownerRef: String
        let format: ResearchReportExportFormat
        let title: String

        /// The export path of the channel the report page addressed.  It
        /// mirrors `FTReportSource`: a server-held tree, the client's local
        /// copy, or a published projection.
        var exportPath: String {
            if publicationID.hasPrefix("local:") {
                let ref = String(publicationID.dropFirst("local:".count))
                return "/api/client/research/\(Self.encode(ref))/export"
            }
            if publicationID.hasPrefix("server:") {
                let ref = String(publicationID.dropFirst("server:".count))
                return "/api/server-research/\(Self.encode(ref))/export"
            }
            return "/api/public-research/\(Self.encode(publicationID))/export"
        }

        /// The manager export URL for a report this client cannot export from
        /// its own workspace.
        func serverExportURL(relativeTo base: URL) -> URL? {
            guard !publicationID.isEmpty else { return nil }
            var path = exportPath + "?format=\(format.extensionName)"
            if !ownerRef.isEmpty {
                path += "&target_ref=\(Self.encode(ownerRef))"
            }
            return URL(string: path, relativeTo: base)?.absoluteURL
        }

        static func encode(_ value: String) -> String {
            var allowed = CharacterSet.alphanumerics
            allowed.insert(charactersIn: "-_.")
            return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
        }
    }

    static func decode(_ body: Any) -> Request? {
        guard let payload = body as? [String: Any],
              let rawFormat = payload["format"] as? String else {
            return nil
        }
        let format = ResearchReportExportFormat(rawValue: rawFormat)
            ?? (rawFormat == "md" ? .markdown : nil)
        guard let format else { return nil }
        let publicationID = String(payload["publication_id"] as? String ?? "")
        let profileRef = String(payload["profile_ref"] as? String ?? "")
        guard !publicationID.isEmpty || !profileRef.isEmpty else { return nil }
        return Request(
            publicationID: publicationID,
            profileRef: profileRef,
            workPackageID: String(payload["work_package_id"] as? String ?? ""),
            branchID: String(payload["branch_id"] as? String ?? ""),
            ownerRef: String(payload["owner_ref"] as? String ?? ""),
            format: format,
            title: String(payload["title"] as? String ?? ""),
        )
    }
}
