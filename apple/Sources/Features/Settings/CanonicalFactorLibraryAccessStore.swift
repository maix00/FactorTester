import Foundation

enum CanonicalFactorLibraryAccessStore {
    private static let bookmarkKey = "canonicalFactorLibrary.securityBookmark"
    private static let pathKey = "canonicalFactorLibrary.root"

    static var rootPath: String? {
        UserDefaults.standard.string(forKey: pathKey)
    }

    static func authorize(_ url: URL) throws {
        let normalized = url.standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: normalized.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        let started = normalized.startAccessingSecurityScopedResource()
        defer { if started { normalized.stopAccessingSecurityScopedResource() } }
        let options: URL.BookmarkCreationOptions = started ? .withSecurityScope : []
        let bookmark = try normalized.bookmarkData(
            options: options,
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        UserDefaults.standard.set(bookmark, forKey: bookmarkKey)
        UserDefaults.standard.set(normalized.path, forKey: pathKey)
    }

    static func withAccess<T>(
        to target: URL,
        _ operation: () async throws -> T
    ) async throws -> T {
        guard let bookmark = UserDefaults.standard.data(forKey: bookmarkKey) else {
            return try await operation()
        }
        var stale = false
        let root = try URL(
            resolvingBookmarkData: bookmark,
            options: [.withSecurityScope, .withoutUI],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        ).standardizedFileURL
        guard target.standardizedFileURL.path == root.path
            || target.standardizedFileURL.path.hasPrefix(root.path + "/") else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        let started = root.startAccessingSecurityScopedResource()
        guard started else { throw ResearchJournalError.workspaceAccessRequired }
        defer { root.stopAccessingSecurityScopedResource() }
        return try await operation()
    }
}
