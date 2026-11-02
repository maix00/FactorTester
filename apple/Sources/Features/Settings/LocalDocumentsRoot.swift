import Foundation

/// Shared CLI and native-client Documents authority during the name migration.
enum LocalDocumentsRoot {
    /// Foundation leaves all symlinks unresolved when the leaf does not yet
    /// exist. Resolve the nearest existing ancestor before appending the leaf.
    static func resolvedLocation(_ input: URL) -> URL {
        var ancestor = input.standardizedFileURL
        var suffix: [String] = []
        let manager = FileManager.default
        while !manager.fileExists(atPath: ancestor.path) && ancestor.path != "/" {
            suffix.append(ancestor.lastPathComponent)
            ancestor.deleteLastPathComponent()
        }
        return suffix.reversed().reduce(ancestor.resolvingSymlinksInPath()) {
            $0.appendingPathComponent($1)
        }.standardizedFileURL
    }

    static func resolve(home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)) throws -> URL {
        let documents = home.appendingPathComponent("Documents", isDirectory: true)
        let current = documents.appendingPathComponent("TradeResearch", isDirectory: true)
        let legacy = documents.appendingPathComponent("FactorTester", isDirectory: true)
        let currentExists = try validDirectory(current)
        let legacyExists = try validDirectory(legacy)
        if currentExists && legacyExists &&
            resolvedLocation(current).path != resolvedLocation(legacy).path {
            throw LocalDocumentsError.conflict
        }
        return currentExists || !legacyExists ? current : legacy
    }

    private static func validDirectory(_ url: URL) throws -> Bool {
        let manager = FileManager.default
        do {
            _ = try manager.attributesOfItem(atPath: url.path)
        } catch let error as NSError where error.domain == NSCocoaErrorDomain &&
            (error.code == NSFileNoSuchFileError || error.code == NSFileReadNoSuchFileError) {
            return false
        }
        var directory: ObjCBool = false
        guard manager.fileExists(atPath: url.path, isDirectory: &directory), directory.boolValue else {
            throw LocalDocumentsError.invalid
        }
        return true
    }
}

enum LocalDocumentsError: LocalizedError {
    case conflict, invalid
    var errorDescription: String? {
        switch self {
        case .conflict: return L10n.text("TradeResearch 文档目录存在冲突，请先核对本地目录迁移。")
        case .invalid: return L10n.text("TradeResearch 文档目录无效或链接已损坏。")
        }
    }
}
