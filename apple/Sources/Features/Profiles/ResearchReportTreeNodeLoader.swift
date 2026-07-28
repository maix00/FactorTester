import Foundation

enum ResearchReportTreeNodeLoader {
    private static let cache: NSCache<NSURL, NSDictionary> = {
        let cache = NSCache<NSURL, NSDictionary>()
        cache.countLimit = 512
        cache.totalCostLimit = 32 * 1024 * 1024
        return cache
    }()

    static func readHead(at url: URL) throws -> [String: Any] {
        try readObject(at: url, cacheable: false)
    }

    static func readNode(reference: String, root: URL) throws -> [String: Any] {
        guard let url = nodeURL(reference, root: root) else {
            throw ResearchReportTreeSourceError.invalidNode
        }
        return try readObject(at: url, cacheable: true)
    }

    static func outline(
        from root: [String: Any], root authoringRoot: URL
    ) throws -> [OutlineItem] {
        guard root["schema_version"] as? Int == 1,
              root["kind"] as? String == "root",
              let children = root["children"] as? [[String: Any]] else {
            throw ResearchReportTreeSourceError.invalidNode
        }
        return try children.map { child in
            guard let id = child["node_id"] as? String,
                  let reference = child["ref"] as? String else {
                throw ResearchReportTreeSourceError.invalidNode
            }
            let node = try readNode(reference: reference, root: authoringRoot)
            guard node["node_id"] as? String == id,
                  node["kind"] as? String == "chapter" else {
                throw ResearchReportTreeSourceError.invalidNode
            }
            return OutlineItem(id: id, reference: reference)
        }
    }

    static func loadSubtree(
        reference: String, parentID: String?, root: URL
    ) throws -> TreeState {
        var state = TreeState()
        try loadNode(reference: reference, parentID: parentID, root: root,
                     depth: 0, state: &state)
        return state
    }

    private static func loadNode(
        reference: String, parentID: String?, root: URL, depth: Int,
        state: inout TreeState
    ) throws {
        guard depth < 32, state.components.count < 4_096 else {
            throw ResearchReportTreeSourceError.invalidNode
        }
        let node = try readNode(reference: reference, root: root)
        guard node["schema_version"] as? Int == 1,
              let nodeID = node["node_id"] as? String,
              let kind = node["kind"] as? String,
              let children = node["children"] as? [[String: Any]],
              let bindings = node["bindings"] as? [[String: Any]] else {
            throw ResearchReportTreeSourceError.invalidNode
        }
        if kind != "root" {
            guard state.nodeIDs.insert(nodeID).inserted else {
                throw ResearchReportTreeSourceError.invalidNode
            }
            var component = node
            component["component_id"] = nodeID
            component["parent_id"] = parentID
            guard let parsed = ResearchDocumentParser.parseComponent(component) else {
                throw ResearchReportTreeSourceError.invalidNode
            }
            state.components.append(parsed)
            for var binding in bindings {
                binding["component_id"] = nodeID
                guard let parsed = ResearchDocumentParser.parseBinding(binding) else {
                    throw ResearchReportTreeSourceError.invalidNode
                }
                state.bindings.append(parsed)
            }
        }
        var childIDs = Set<String>()
        for child in children {
            guard let childID = child["node_id"] as? String,
                  let childRef = child["ref"] as? String,
                  childIDs.insert(childID).inserted else {
                throw ResearchReportTreeSourceError.invalidNode
            }
            try loadNode(reference: childRef,
                         parentID: kind == "root" ? nil : nodeID,
                         root: root, depth: depth + 1, state: &state)
        }
    }

    private static func readObject(
        at url: URL, cacheable: Bool
    ) throws -> [String: Any] {
        let key = url as NSURL
        if cacheable, let cached = cache.object(forKey: key) as? [String: Any] {
            return cached
        }
        let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
            try Data(contentsOf: url, options: .mappedIfSafe)
        }
        guard let value = try JSONSerialization.jsonObject(with: data)
            as? [String: Any] else {
            throw ResearchReportTreeSourceError.invalidNode
        }
        if cacheable {
            cache.setObject(value as NSDictionary, forKey: key, cost: data.count)
        }
        return value
    }

    private static func nodeURL(_ reference: String, root: URL) -> URL? {
        let parts = reference.split(separator: "/").map(String.init)
        guard parts.count == 3, parts[0] == "nodes",
              parts[1].range(of: #"^[A-Za-z0-9._-]{1,128}$"#,
                             options: .regularExpression) != nil,
              parts[2].range(of: #"^[0-9a-f]{64}\.json$"#,
                             options: .regularExpression) != nil else {
            return nil
        }
        return parts.reduce(root) { $0.appendingPathComponent($1) }
    }

    struct OutlineItem {
        let id: String
        let reference: String
    }

    struct TreeState {
        var components: [ResearchDocumentComponent] = []
        var bindings: [ResearchDocumentBinding] = []
        var nodeIDs = Set<String>()

        mutating func merge(_ other: TreeState) {
            components.append(contentsOf: other.components)
            bindings.append(contentsOf: other.bindings)
            nodeIDs.formUnion(other.nodeIDs)
        }
    }
}
