import SwiftUI
#if os(macOS)
import AppKit
#endif

private struct ResearchDocumentReferenceActionKey: EnvironmentKey {
    static let defaultValue: (ResearchDocumentTypedLink) -> Void = { _ in }
}

private struct ResearchDocumentReferenceComponentIDKey: EnvironmentKey {
    static let defaultValue = ""
}

private struct ResearchDocumentReferenceBindingsKey: EnvironmentKey {
    static let defaultValue: [ResearchDocumentBinding] = []
}

extension EnvironmentValues {
    var researchDocumentReferenceAction: (ResearchDocumentTypedLink) -> Void {
        get { self[ResearchDocumentReferenceActionKey.self] }
        set { self[ResearchDocumentReferenceActionKey.self] = newValue }
    }

    var researchDocumentReferenceComponentID: String {
        get { self[ResearchDocumentReferenceComponentIDKey.self] }
        set { self[ResearchDocumentReferenceComponentIDKey.self] = newValue }
    }

    var researchDocumentReferenceBindings: [ResearchDocumentBinding] {
        get { self[ResearchDocumentReferenceBindingsKey.self] }
        set { self[ResearchDocumentReferenceBindingsKey.self] = newValue }
    }
}

enum ResearchDocumentReferenceRouter {
    static func profileID(from reference: ResearchDocumentTypedLink) -> String? {
        guard ResearchDocumentReferenceCatalog.canonicalKind(reference.kind) == "profile",
              reference.targetRef.hasPrefix("profile:") else { return nil }
        let value = String(reference.targetRef.dropFirst("profile:".count))
        return isSafeIdentifier(value) ? value : nil
    }

    static func jobID(from reference: ResearchDocumentTypedLink) -> String? {
        guard ResearchDocumentReferenceCatalog.canonicalKind(reference.kind) == "job" else { return nil }
        for prefix in ["research-job:", "job:"] where reference.targetRef.hasPrefix(prefix) {
            let value = String(reference.targetRef.dropFirst(prefix.count))
            if isSafeIdentifier(value) { return value }
        }
        return nil
    }

    static func localFileURL(
        for reference: ResearchDocumentTypedLink,
        reportRef: String,
        fileManager: FileManager = .default
    ) -> URL? {
        guard ResearchDocumentReferenceCatalog.canonicalKind(reference.kind) == "file",
              ResearchDocumentTypedLinkParser.isSafeRelativeFilePath(
                reference.targetRef
              ),
              let reportURL = URL(string: reportRef), reportURL.isFileURL else {
            return nil
        }
        let packageRoot = reportURL.deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().resolvingSymlinksInPath()
        let candidate = reference.targetRef.split(separator: "/").reduce(packageRoot) {
            $0.appendingPathComponent(String($1), isDirectory: false)
        }.resolvingSymlinksInPath()
        guard candidate.path.hasPrefix(packageRoot.path + "/"),
              fileManager.fileExists(atPath: candidate.path) else { return nil }
        return candidate
    }

    static func webURL(for reference: ResearchDocumentTypedLink) -> URL? {
        guard ResearchDocumentReferenceCatalog.canonicalKind(reference.kind) == "url",
              ResearchDocumentTypedLinkParser.isSafeWebURL(reference.targetRef) else {
            return nil
        }
        return URL(string: reference.targetRef)
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 128 else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || "._-".unicodeScalars.contains($0)
        }
    }
}

#if os(macOS)
enum ResearchDocumentExternalURLLauncher {
    static func open(
        _ url: URL,
        workspace: NSWorkspace = .shared
    ) {
        _ = open(url, workspace.open)
    }

    @discardableResult
    static func open(
        _ url: URL,
        _ opener: (URL) -> Bool
    ) -> Bool {
        opener(url)
    }
}
#endif
