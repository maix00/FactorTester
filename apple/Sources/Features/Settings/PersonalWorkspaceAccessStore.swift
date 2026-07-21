import Foundation

enum PersonalWorkspaceAccessStore {
    private static let bookmarkKey = "personalWorkspace.securityBookmark"
    private static let pathKey = "personalWorkspace.authorizedRoot"

    static var authorizedRootPath: String? {
        UserDefaults.standard.string(forKey: pathKey)
    }

    static func authorize(_ url: URL) throws {
        let normalized = url.standardizedFileURL
        let started = normalized.startAccessingSecurityScopedResource()
        defer {
            if started { normalized.stopAccessingSecurityScopedResource() }
        }
        let options: URL.BookmarkCreationOptions = started
            ? .withSecurityScope
            : []
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
        _ operation: () throws -> T
    ) throws -> T {
        guard requiresExplicitAccess(target) else {
            return try operation()
        }
        guard let bookmark = UserDefaults.standard.data(forKey: bookmarkKey)
        else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        var stale = false
        let root: URL
        do {
            root = try URL(
                resolvingBookmarkData: bookmark,
                options: [.withSecurityScope, .withoutUI],
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            )
        } catch {
            throw ResearchJournalError.workspaceAccessRequired
        }
        guard !stale, contains(target, in: root) else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        let started = root.startAccessingSecurityScopedResource()
        defer {
            if started { root.stopAccessingSecurityScopedResource() }
        }
        return try operation()
    }

    private static func requiresExplicitAccess(_ target: URL) -> Bool {
        let protectedRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester", isDirectory: true)
        return contains(target, in: protectedRoot)
    }

    private static func contains(_ target: URL, in root: URL) -> Bool {
        let targetPath = target.standardizedFileURL.path
        let rootPath = root.standardizedFileURL.path
        return targetPath == rootPath
            || targetPath.hasPrefix(rootPath.hasSuffix("/") ? rootPath : rootPath + "/")
    }
}
