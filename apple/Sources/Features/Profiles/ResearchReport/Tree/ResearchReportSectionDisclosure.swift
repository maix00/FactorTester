import SwiftUI

/// Special report sections are still ordinary report content. The marker only
/// changes presentation; it never changes graph navigation or evidence data.
enum ResearchReportSectionSpecialKind: Equatable {
    case obligationChange
    case graphContinuation
    case capabilityDetour
    case grillResolution
    case externalReview
    case entryRequirements
    case obligationRequirement
    case obligationCoverage
    case pathSelection
    case testResult
    case evidenceFragment
    case researchGap

    static func resolve(
        component: ResearchDocumentComponent,
        bindings: [ResearchDocumentBinding]
    ) -> Self? {
        resolve(
            displayKind: component.displayKind,
            sectionRole: nil,
            hasObligationChanges: component.kind == "special"
                && bindings.contains(where: { $0.kind == "obligation" })
        )
    }

    static func resolve(
        displayKind: String,
        sectionRole: String?,
        hasObligationChanges: Bool
    ) -> Self? {
        if displayKind == "graph_continuation"
            || sectionRole == "graph_continuation"
            || sectionRole == "upgrade_reentry" {
            return .graphContinuation
        }
        if displayKind == "capability_detour"
            || sectionRole == "capability_detour" {
            return .capabilityDetour
        }
        if displayKind == "grill_resolution"
            || sectionRole == "grill_resolution" {
            return .grillResolution
        }
        if displayKind == "external_review"
            || sectionRole == "external_review" {
            return .externalReview
        }
        if displayKind == "entry_requirements"
            || sectionRole == "entry_requirements" {
            return .entryRequirements
        }
        if displayKind == "obligation_requirement"
            || sectionRole == "obligation_requirement" {
            return .obligationRequirement
        }
        if displayKind == "obligation_coverage"
            || sectionRole == "obligation_coverage" {
            return .obligationCoverage
        }
        if displayKind == "path_selection"
            || sectionRole == "path_selection" {
            return .pathSelection
        }
        if displayKind == "test_result"
            || sectionRole == "test_result" {
            return .testResult
        }
        if displayKind == "evidence_fragment"
            || sectionRole == "evidence_fragment" {
            return .evidenceFragment
        }
        if displayKind == "research_gap"
            || sectionRole == "research_gap" {
            return .researchGap
        }
        if displayKind == "obligation_changes"
            || sectionRole == "obligation_changes"
            || hasObligationChanges {
            return .obligationChange
        }
        return nil
    }

    var title: String {
        switch self {
        case .obligationChange: return L10n.text("义务变化")
        case .graphContinuation: return L10n.text("图版本承接")
        case .capabilityDetour: return L10n.text("能力修复旁路")
        case .grillResolution: return L10n.text("Grill 决议")
        case .externalReview: return L10n.text("外部审计")
        case .entryRequirements: return L10n.text("节点进入要求")
        case .obligationRequirement: return L10n.text("义务小类处理")
        case .obligationCoverage: return L10n.text("义务覆盖")
        case .pathSelection: return L10n.text("研究路径选择")
        case .testResult: return L10n.text("测试结果")
        case .evidenceFragment: return L10n.text("证据片段")
        case .researchGap: return L10n.text("研究缺口")
        }
    }

    var icon: String {
        switch self {
        case .obligationChange: return "exclamationmark.bubble"
        case .graphContinuation: return "arrow.triangle.branch"
        case .capabilityDetour: return "wrench.and.screwdriver"
        case .grillResolution: return "checkmark.bubble"
        case .externalReview: return "text.magnifyingglass"
        case .entryRequirements: return "checklist"
        case .obligationRequirement: return "checkmark.circle"
        case .obligationCoverage: return "checkmark.shield"
        case .pathSelection: return "arrow.triangle.branch"
        case .testResult: return "chart.bar.doc.horizontal"
        case .evidenceFragment: return "doc.text.magnifyingglass"
        case .researchGap: return "exclamationmark.triangle"
        }
    }

    var tint: Color {
        switch self {
        case .obligationChange: return .orange
        case .graphContinuation: return .indigo
        case .capabilityDetour: return .purple
        case .grillResolution: return .red
        case .externalReview: return .teal
        case .entryRequirements: return .blue
        case .obligationRequirement: return .cyan
        case .obligationCoverage: return .green
        case .pathSelection: return .indigo
        case .testResult: return .blue
        case .evidenceFragment: return .indigo
        case .researchGap: return .orange
        }
    }
}
