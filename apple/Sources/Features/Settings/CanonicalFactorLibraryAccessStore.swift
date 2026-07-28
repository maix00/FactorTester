import Foundation

enum CanonicalFactorLibraryAccessStore {
    private static let bookmarkKey = "canonicalFactorLibrary.securityBookmark"
    private static let pathKey = "canonicalFactorLibrary.root"

    static var rootPath: String? {
        UserDefaults.standard.string(forKey: pathKey)
    }

    static func defaultRootPath(for principal: String) -> String {
        defaultRootURL(for: principal).path
    }

    @discardableResult
    static func ensureDefault(for principal: String) throws -> String {
        guard isValidPrincipal(principal) else {
            throw WorkspaceAccessError.required
        }
        let root = defaultRootURL(for: principal)
        let fileManager = FileManager.default
        try fileManager.createDirectory(
            at: root.appendingPathComponent("custom_factors", isDirectory: true),
            withIntermediateDirectories: true
        )
        try fileManager.createDirectory(
            at: root.appendingPathComponent("public_factors", isDirectory: true),
            withIntermediateDirectories: true
        )
        try fileManager.createDirectory(
            at: root.appendingPathComponent(".factor_workspace", isDirectory: true),
            withIntermediateDirectories: true
        )
        UserDefaults.standard.set(root.path, forKey: pathKey)
        return root.path
    }

    static func authorize(_ url: URL) throws {
        let normalized = url.standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: normalized.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            throw WorkspaceAccessError.required
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

    private static func defaultRootURL(for principal: String) -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users", isDirectory: true)
            .appendingPathComponent(principal, isDirectory: true)
            .appendingPathComponent("personal-workspace/factor-library", isDirectory: true)
            .standardizedFileURL
    }

    private static func isValidPrincipal(_ principal: String) -> Bool {
        !principal.isEmpty && principal.allSatisfy {
            $0.isNumber || $0.isLetter || $0 == "_" || $0 == "-" || $0 == "."
        }
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
            throw WorkspaceAccessError.required
        }
        let started = root.startAccessingSecurityScopedResource()
        guard started else { throw WorkspaceAccessError.required }
        defer { root.stopAccessingSecurityScopedResource() }
        return try await operation()
    }
}
