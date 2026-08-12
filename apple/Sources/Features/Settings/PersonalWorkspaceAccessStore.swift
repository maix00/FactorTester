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
              sameLocation(resolved.root, storedRoot),
              contains(target, in: resolved.root) else {
            // Never fall through to an unscoped Documents read. Besides
            // bypassing the explicit directory choice, doing so makes macOS
            // show its TCC prompt whenever an ad-hoc build changes identity.
            throw WorkspaceAccessError.required
        }
        let started = resolved.root.startAccessingSecurityScopedResource()
        guard started else {
            throw WorkspaceAccessError.required
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

enum WorkspaceAccessError: LocalizedError {
    case required

    var errorDescription: String? {
        L10n.text("请先在设置中授权个人工作区")
    }
}
