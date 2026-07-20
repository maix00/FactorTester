import SwiftUI

struct ProfileResearchOverview: View {
    let profiles: [LocalProfileModel]
    let openProfile: (LocalProfileModel) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("研究进度").font(.largeTitle.weight(.semibold))
                Text("按 Profile 查看当前研究步骤与已生成报告。")
                    .foregroundStyle(.secondary)
                ForEach(profiles) { profile in
                    Button { openProfile(profile) } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "person.crop.rectangle")
                                .font(.title2)
                                .foregroundStyle(.tint)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(profile.displayName).font(.headline)
                                Text(summary(profile))
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .foregroundStyle(.secondary)
                        }
                        .padding(16)
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                }
                if profiles.isEmpty {
                    Label(
                        "尚未注册 Profile，因此没有可展示的研究进度。",
                        systemImage: "chart.xyaxis.line"
                    )
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 40)
                }
            }
            .padding(24)
        }
    }

    private func summary(_ profile: LocalProfileModel) -> String {
        guard !profile.researchRecords.isEmpty else {
            return "等待研究记录"
        }
        let ready = profile.researchRecords.filter { $0.status == "ready" }.count
        return "\(profile.researchRecords.count) 项研究 · \(ready) 份报告可用"
    }
}
