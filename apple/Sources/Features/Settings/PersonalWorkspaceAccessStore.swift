import Foundation

enum PersonalWorkspaceAccessStore {
    private static let bookmarkKey = "personalWorkspace.securityBookmark"
    private static let pathKey = "personalWorkspace.authorizedRoot"

    static var authorizedRootPath: String? {
        UserDefaults.standard.string(forKey: pathKey)
    }

    static func authorize(_ url: URL) throws {
        let normalized = url.standardizedFileURL
        guard isCanonicalUserRoot(normalized) else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        try storeBookmark(for: normalized)
        UserDefaults.standard.set(normalized.path, forKey: pathKey)
    }

    private static func storeBookmark(for normalized: URL) throws {
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
    }

    static func withAccess<T>(
        to target: URL,
        _ operation: () throws -> T
    ) throws -> T {
        guard requiresExplicitAccess(target) else {
            return try operation()
        }
        guard let storedRoot = storedAuthorizedRoot(for: target) else {
            throw ResearchJournalError.workspaceAccessRequired
        }
        if let bookmark = UserDefaults.standard.data(forKey: bookmarkKey),
           let resolved = resolve(bookmark),
           sameLocation(resolved.root, storedRoot),
           contains(target, in: resolved.root) {
            if resolved.stale {
                try? storeBookmark(for: storedRoot)
            }
            let started = resolved.root.startAccessingSecurityScopedResource()
            defer {
                if started { resolved.root.stopAccessingSecurityScopedResource() }
            }
            return try operation()
        }

        // This app intentionally runs outside App Sandbox so its local CLI and
        // adapters can execute. In that mode the directory choice is a durable
        // consent marker, while a security-scoped bookmark may become
        // unresolvable after an ad-hoc Beta update. Keep the exact canonical
        // user root, refresh the bookmark without widening the path, and let
        // the filesystem enforce the actual read permission.
        try? storeBookmark(for: storedRoot)
        return try operation()
    }

    private static func resolve(
        _ bookmark: Data
    ) -> (root: URL, stale: Bool)? {
        let optionSets: [URL.BookmarkResolutionOptions] = [
            [.withSecurityScope, .withoutUI],
            [.withoutUI],
        ]
        for options in optionSets {
            var stale = false
            if let root = try? URL(
                resolvingBookmarkData: bookmark,
                options: options,
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            ) {
                return (root.standardizedFileURL, stale)
            }
        }
        return nil
    }

    private static func requiresExplicitAccess(_ target: URL) -> Bool {
        contains(target, in: factorTesterRoot)
    }

    static func storedAuthorizedRoot(
        path: String?,
        for target: URL
    ) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        let root = URL(fileURLWithPath: path, isDirectory: true)
            .standardizedFileURL
        guard isCanonicalUserRoot(root), contains(target, in: root) else {
            return nil
        }
        return root
    }

    private static func storedAuthorizedRoot(for target: URL) -> URL? {
        storedAuthorizedRoot(path: authorizedRootPath, for: target)
    }

    private static var factorTesterRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester", isDirectory: true)
            .standardizedFileURL
    }

    private static var usersRoot: URL {
        factorTesterRoot.appendingPathComponent("users", isDirectory: true)
    }

    private static func isCanonicalUserRoot(_ root: URL) -> Bool {
        let rootPath = root.standardizedFileURL.path
        let prefix = usersRoot.path + "/"
        guard rootPath.hasPrefix(prefix) else { return false }
        let suffix = String(rootPath.dropFirst(prefix.count))
        return !suffix.isEmpty && !suffix.contains("/")
    }

    private static func sameLocation(_ lhs: URL, _ rhs: URL) -> Bool {
        lhs.standardizedFileURL.path == rhs.standardizedFileURL.path
    }

    private static func contains(_ target: URL, in root: URL) -> Bool {
        let targetPath = target.standardizedFileURL.path
        let rootPath = root.standardizedFileURL.path
        return targetPath == rootPath
            || targetPath.hasPrefix(rootPath.hasSuffix("/") ? rootPath : rootPath + "/")
    }
}
