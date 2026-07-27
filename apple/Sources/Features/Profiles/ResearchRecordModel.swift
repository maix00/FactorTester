import Foundation

struct ResearchDeepLinkModel: Identifiable, Decodable {
    let id: String
    let kind: String
    let targetRef: String
    let sectionRef: String

    init(json: [String: Any]) {
        id = json["link_id"] as? String ?? ""
        kind = json["kind"] as? String ?? ""
        targetRef = json["target_ref"] as? String ?? ""
        sectionRef = json["section_ref"] as? String ?? ""
    }

    enum CodingKeys: String, CodingKey {
        case id = "link_id"
        case kind
        case targetRef = "target_ref"
        case sectionRef = "section_ref"
    }
}

struct ResearchArtifactModel: Identifiable {
    let id: String
    let format: String
    let status: String
    let localRef: String
    let indexRef: String
    let journalRef: String
    let journalHash: String
    let sectionRefs: [ResearchDeepLinkModel]

    init(json: [String: Any]) {
        id = json["artifact_ref"] as? String ?? ""
        format = json["format"] as? String ?? ""
        status = json["status"] as? String ?? ""
        localRef = json["local_ref"] as? String ?? ""
        indexRef = json["index_ref"] as? String ?? ""
        journalRef = json["journal_ref"] as? String ?? ""
        journalHash = json["journal_hash"] as? String ?? ""
        sectionRefs = (json["section_refs"] as? [[String: Any]] ?? [])
            .map(ResearchDeepLinkModel.init)
    }
}

struct ResearchRecordModel: Identifiable {
    let id: String
    let title: String
    let status: String
    let agentID: String
    let scope: String
    let factorFamilies: [String]
    let productGroup: String
    let researchRole: String
    let graphInstanceRef: String
    let graphBranchRef: String
    let checkpointRef: String
    let timeline: [ResearchDeepLinkModel]
    let artifacts: [ResearchArtifactModel]

    init(json: [String: Any]) {
        id = json["record_id"] as? String ?? ""
        title = json["title"] as? String ?? id
        status = json["status"] as? String ?? ""
        agentID = json["agent_id"] as? String ?? ""
        let scopeValues = json["scope"] as? [String: Any] ?? [:]
        scope = String(describing: scopeValues)
        factorFamilies = scopeValues["factor_families"] as? [String] ?? []
        productGroup = scopeValues["product_group"] as? String ?? ""
        researchRole = scopeValues["research_role"] as? String ?? ""
        graphInstanceRef = json["graph_instance_ref"] as? String
            ?? json["work_package_ref"] as? String
            ?? ""
        graphBranchRef = json["graph_branch_ref"] as? String ?? ""
        checkpointRef = json["checkpoint_ref"] as? String ?? ""
        timeline = (json["timeline_refs"] as? [[String: Any]] ?? [])
            .map(ResearchDeepLinkModel.init)
        artifacts = (json["artifacts"] as? [[String: Any]] ?? [])
            .map(ResearchArtifactModel.init)
    }

    var currentJournalArtifact: ResearchArtifactModel? {
        artifacts.last {
            !$0.journalRef.isEmpty && $0.sectionRefs.contains {
                $0.kind == "checkpoint" && $0.targetRef == checkpointRef
            }
        } ?? artifacts.last { !$0.journalRef.isEmpty }
    }

    var currentDocumentArtifact: ResearchArtifactModel? {
        artifacts.last {
            $0.format == "document" && !$0.localRef.isEmpty
        }
    }

    var researchScopeTitle: String {
        let family = factorFamilies.joined(separator: "、")
        let role: String
        switch researchRole {
        case "auxiliary_or_conditional_signal":
            role = L10n.text("辅助与条件信号")
        case "new_main_factor_candidate":
            role = L10n.text("新主因子候选")
        case "main_factor": role = L10n.text("主因子")
        case "auxiliary_factor": role = L10n.text("辅助因子")
        default: role = L10n.text("因子")
        }
        if !family.isEmpty { return L10n.format("%@ · %@研究", family, role) }
        return title
    }

    var preferredResearchTitle: String {
        let normalized = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let generic = normalized.lowercased() == "primary"
            || normalized.lowercased().hasPrefix("continuation-v")
        return normalized.isEmpty || generic ? researchScopeTitle : normalized
    }
}
