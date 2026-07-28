import Foundation

/// Presentation labels for graph-owned identifiers. Unknown graph nodes keep
/// their registered name rather than being replaced with a generic status.
enum ResearchDisplayText {
    static func reportTitle(_ title: String) -> String {
        guard title.range(of: "\\p{Han}", options: .regularExpression) != nil
        else { return L10n.text("因子研究报告") }
        return title
    }

    static func branchLabel(_ label: String, currentNode: String) -> String {
        if label.range(of: "\\p{Han}", options: .regularExpression) != nil {
            return label
        }
        return L10n.format("%@研究", node(currentNode))
    }

    static func node(_ value: String) -> String {
        switch value {
        case "candidate_discovery": return L10n.text("候选发现")
        case "hypothesis_preregistration": return L10n.text("假设预注册")
        case "capability_resolution": return L10n.text("研究能力确认")
        case "data_contract": return L10n.text("数据契约")
        case "factor_semantics": return L10n.text("因子语义")
        case "validation_design": return L10n.text("验证设计")
        case "trial_plan": return L10n.text("试验计划")
        case "capability_gap": return L10n.text("能力缺口")
        case "job_evidence_ready": return L10n.text("回测证据就绪")
        case "evidence_assessment": return L10n.text("证据评估")
        case "factor_improvement": return L10n.text("因子改进")
        case "completed": return L10n.text("研究完成")
        default: return value.replacingOccurrences(of: "_", with: " ")
        }
    }

    static func lifecycleStatus(_ status: String) -> String {
        switch status.lowercased() {
        case "running": return L10n.text("进行中")
        case "paused": return L10n.text("已暂停")
        case "completed", "closed": return L10n.text("已完成")
        case "blocked": return L10n.text("等待处理")
        case "failed": return L10n.text("失败")
        default: return status.isEmpty ? L10n.text("状态未知") : status
        }
    }

    static func productGroup(_ productGroup: String) -> String {
        productGroup.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
