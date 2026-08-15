import Combine
import Foundation

struct LocalResearchGraphFile: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let filename: String
    let createdAt: Date
    var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, filename
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// Local-only Research Graph YAML storage for the Swift client.
///
/// Files in this store are never sent to a Manager implicitly.  The selected
/// default URL is the input boundary a future local Research Agent runner can
/// use; the server-side user library has a separate, explicit upload action.
@MainActor
final class LocalResearchGraphStore: ObservableObject {
    static let maxFileBytes = 2 * 1024 * 1024

    @Published private(set) var files: [LocalResearchGraphFile] = []
    @Published private(set) var defaultFileID: String?
    @Published private(set) var errorMessage: String?

    private let fileManager: FileManager
    private let root: URL
    private let indexURL: URL

    init(
        root: URL? = nil,
        fileManager: FileManager = .default
    ) {
        self.fileManager = fileManager
        let base = root ?? fileManager.urls(
            for: .documentDirectory,
            in: .userDomainMask
        )[0].appendingPathComponent(
            "FactorTester/research-graphs",
            isDirectory: true
        )
        self.root = base.standardizedFileURL
        self.indexURL = self.root.appendingPathComponent("index.json")
        load()
    }

    var defaultFile: LocalResearchGraphFile? {
        guard let defaultFileID else { return nil }
        return files.first { $0.id == defaultFileID }
    }

    var defaultGraphURL: URL? {
        guard let file = defaultFile else { return nil }
        return url(for: file)
    }

    func importFile(from source: URL) {
        errorMessage = nil
        do {
            let access = source.startAccessingSecurityScopedResource()
            defer {
                if access { source.stopAccessingSecurityScopedResource() }
            }
            let data = try Data(contentsOf: source)
            guard !data.isEmpty else { throw LocalResearchGraphStoreError.empty }
            guard data.count <= Self.maxFileBytes else {
                throw LocalResearchGraphStoreError.tooLarge
            }
            try ensureRoot()
            let file = LocalResearchGraphFile(
                id: UUID().uuidString.lowercased(),
                name: source.deletingPathExtension().lastPathComponent,
                filename: safeFilename(source.lastPathComponent),
                createdAt: Date(),
                updatedAt: Date()
            )
            try data.write(to: url(for: file), options: .atomic)
            files.append(file)
            files.sort { $0.updatedAt > $1.updatedAt }
            try persist()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setDefault(_ file: LocalResearchGraphFile?) {
        errorMessage = nil
        defaultFileID = file?.id
        do {
            try persist()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func delete(_ file: LocalResearchGraphFile) {
        errorMessage = nil
        do {
            try? fileManager.removeItem(at: url(for: file))
            files.removeAll { $0.id == file.id }
            if defaultFileID == file.id { defaultFileID = nil }
            try persist()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: indexURL) else { return }
        do {
            let value = try JSONDecoder().decode(Index.self, from: data)
            files = value.files.filter { fileManager.fileExists(atPath: url(for: $0).path) }
            defaultFileID = value.defaultFileID
            if let defaultFileID, !files.contains(where: { $0.id == defaultFileID }) {
                self.defaultFileID = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func persist() throws {
        try ensureRoot()
        let data = try JSONEncoder().encode(Index(
            files: files,
            defaultFileID: defaultFileID
        ))
        try data.write(to: indexURL, options: .atomic)
    }

    private func ensureRoot() throws {
        try fileManager.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
    }

    private func url(for file: LocalResearchGraphFile) -> URL {
        root.appendingPathComponent("\(file.id)-\(file.filename)")
    }

    private func safeFilename(_ value: String) -> String {
        let raw = value.isEmpty ? "research-graph.yaml" : value
        let allowed = CharacterSet.alphanumerics
            .union(CharacterSet(charactersIn: "._-"))
        let scalars = raw.unicodeScalars.map {
            allowed.contains($0) ? Character(String($0)) : "-"
        }
        let cleaned = String(scalars).trimmingCharacters(in: CharacterSet(charactersIn: ".-"))
        let result = cleaned.isEmpty ? "research-graph.yaml" : cleaned
        return result.lowercased().hasSuffix(".yaml") || result.lowercased().hasSuffix(".yml")
            ? result
            : "\(result).yaml"
    }

    private struct Index: Codable {
        let files: [LocalResearchGraphFile]
        let defaultFileID: String?

        enum CodingKeys: String, CodingKey {
            case files
            case defaultFileID = "default_file_id"
        }
    }
}

enum LocalResearchGraphStoreError: LocalizedError {
    case empty
    case tooLarge

    var errorDescription: String? {
        switch self {
        case .empty:
            return L10n.text("研究图 YAML 为空")
        case .tooLarge:
            return L10n.text("研究图 YAML 不能超过 2 MiB")
        }
    }
}
