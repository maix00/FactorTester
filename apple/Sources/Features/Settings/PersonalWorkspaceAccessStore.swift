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
            throw WorkspaceAccessError.required
        }
        try storeBookmark(for: normalized)
        UserDefaults.standard.set(normalized.path, forKey: pathKey)
    }

    static func expectedRoot(for principal: String) -> URL? {
        guard principal.range(
            of: #"^[A-Za-z0-9._-]{1,128}$"#,
            options: .regularExpression
        ) != nil else { return nil }
        if let path = authorizedRootPath {
            let root = URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
            if root.lastPathComponent == principal && isCanonicalUserRoot(root) {
                return root
            }
        }
        guard let usersRoot = try? LocalDocumentsRoot.resolve().appendingPathComponent("users", isDirectory: true) else {
            return nil
        }
        return usersRoot.appendingPathComponent(principal, isDirectory: true)
            .standardizedFileURL
    }

    static func hasAuthorization(for root: URL) -> Bool {
        (try? withAccess(to: root) { true }) == true
    }

    private static func storeBookmark(for normalized: URL) throws {
        let started = normalized.startAccessingSecurityScopedResource()
        defer {
            if started { normalized.stopAccessingSecurityScopedResource() }
        }
        try persistBookmark(for: normalized, securityScoped: started)
    }

    static func withAccess<T>(
        to target: URL,
        _ operation: () throws -> T
    ) throws -> T {
        let access = try prepareAccess(to: target)
        defer { finishAccess(access) }
        return try operation()
    }

    static func withAccess<T>(
        to target: URL,
        _ operation: () async throws -> T
    ) async throws -> T {
        let access = try prepareAccess(to: target)
        defer { finishAccess(access) }
        return try await operation()
    }

    private struct PreparedAccess {
        let root: URL?
        let started: Bool
    }

    private static func prepareAccess(to target: URL) throws -> PreparedAccess {
        guard requiresExplicitAccess(target) else {
            return PreparedAccess(root: nil, started: false)
        }
        guard let storedRoot = storedAuthorizedRoot(for: target),
              let bookmark = UserDefaults.standard.data(forKey: bookmarkKey),
              let resolved = resolve(bookmark),
              sameLogicalLocation(resolved.root, storedRoot) else {
            // Never fall through to an unscoped Documents read. Besides
            // bypassing the explicit directory choice, doing so makes macOS
            // show its TCC prompt whenever an ad-hoc build changes identity.
            throw WorkspaceAccessError.required
        }
        let started = resolved.root.startAccessingSecurityScopedResource()
        guard started else {
            throw WorkspaceAccessError.required
        }
        do {
            // Inspect Documents and resolve symlinks only after activating the
            // original security scope; otherwise macOS may trigger a naked
            // Documents access prompt before the user's bookmark is applied.
            _ = try LocalDocumentsRoot.resolve()
            guard sameLocation(resolved.root, storedRoot),
                  physicallyContains(target, in: resolved.root) else {
                throw WorkspaceAccessError.required
            }
        } catch {
            resolved.root.stopAccessingSecurityScopedResource()
            throw error
        }
        if resolved.stale {
            // Refresh only after the original security extension is active.
            // Refreshing first performs a naked Documents access and can ask
            // for permission again after an otherwise compatible update.
            try? persistBookmark(for: resolved.root, securityScoped: true)
        }
        return PreparedAccess(root: resolved.root, started: true)
    }

    private static func finishAccess(_ access: PreparedAccess) {
        if access.started {
            access.root?.stopAccessingSecurityScopedResource()
        }
    }

    private static func persistBookmark(
        for root: URL,
        securityScoped: Bool
    ) throws {
        let options: URL.BookmarkCreationOptions = securityScoped
            ? .withSecurityScope
            : []
        let bookmark = try root.bookmarkData(
            options: options,
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        UserDefaults.standard.set(bookmark, forKey: bookmarkKey)
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
        let documents = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents", isDirectory: true)
        return ["TradeResearch", "FactorTester"].contains {
            let root = documents.appendingPathComponent($0, isDirectory: true)
            let lexicalTarget = target.standardizedFileURL.path
            let lexicalRoot = root.standardizedFileURL.path
            return lexicalTarget == lexicalRoot || lexicalTarget.hasPrefix(lexicalRoot + "/")
        }
    }

    static func storedAuthorizedRoot(
        path: String?,
        for target: URL,
        home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        let root = URL(fileURLWithPath: path, isDirectory: true)
            .standardizedFileURL
        guard isCanonicalUserRoot(root, home: home), logicallyContains(target, in: root, home: home) else {
            return nil
        }
        return root
    }

    private static func storedAuthorizedRoot(for target: URL) -> URL? {
        storedAuthorizedRoot(path: authorizedRootPath, for: target)
    }

    private static func isCanonicalUserRoot(
        _ root: URL, home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> Bool {
        let usersRoot = home.appendingPathComponent("Documents/TradeResearch/users", isDirectory: true)
        let rootPath = logicalPath(root, home: home)
        let prefix = usersRoot.standardizedFileURL.path + "/"
        guard rootPath.hasPrefix(prefix) else { return false }
        let suffix = String(rootPath.dropFirst(prefix.count))
        return !suffix.isEmpty && !suffix.contains("/")
    }

    private static func sameLocation(_ lhs: URL, _ rhs: URL) -> Bool {
        LocalDocumentsRoot.resolvedLocation(lhs).path == LocalDocumentsRoot.resolvedLocation(rhs).path
    }

    private static func sameLogicalLocation(_ lhs: URL, _ rhs: URL) -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return logicalPath(lhs, home: home) == logicalPath(rhs, home: home)
    }

    private static func logicalPath(_ url: URL, home: URL) -> String {
        let path = url.standardizedFileURL.path
        let old = home.appendingPathComponent("Documents/FactorTester", isDirectory: true).standardizedFileURL.path
        let current = home.appendingPathComponent("Documents/TradeResearch", isDirectory: true).standardizedFileURL.path
        if path == old { return current }
        if path.hasPrefix(old + "/") { return current + path.dropFirst(old.count) }
        return path
    }

    private static func logicallyContains(_ target: URL, in root: URL, home: URL) -> Bool {
        let targetPath = logicalPath(target, home: home)
        let rootPath = logicalPath(root, home: home)
        return targetPath == rootPath || targetPath.hasPrefix(rootPath + "/")
    }

    static func physicallyContains(_ target: URL, in root: URL) -> Bool {
        let targetPath = LocalDocumentsRoot.resolvedLocation(target).path
        let rootPath = LocalDocumentsRoot.resolvedLocation(root).path
        return targetPath == rootPath
            || targetPath.hasPrefix(rootPath.hasSuffix("/") ? rootPath : rootPath + "/")
    }
}

enum WorkspaceAccessError: LocalizedError {
    case required

    var errorDescription: String? {
        L10n.text("请先在设置中授权个人工作区")
    }
}
