import SwiftUI

struct InitializationSourceView: View {
    let profile: LocalProfileModel
    @StateObject private var controller = InitializationSourceController()
    @State private var selectedOwner = ""

    var body: some View {
        GroupBox("Initialization") {
            VStack(alignment: .leading, spacing: 10) {
                LabeledContent(
                    "Authenticated principal",
                    value: profile.principalRef
                )
                Picker("Authorized factor library", selection: $selectedOwner) {
                    Text("Select a registered grant").tag("")
                    ForEach(controller.grants) { grant in
                        Text("\(grant.name) · \(grant.factorCount)")
                            .tag(grant.id)
                    }
                }
                HStack {
                    Button("Refresh grants") {
                        Task { await controller.refresh(profileID: profile.id) }
                    }
                    Button("Bind source") {
                        Task {
                            await controller.bind(
                                profileID: profile.id,
                                ownerRef: selectedOwner
                            )
                        }
                    }
                    .disabled(selectedOwner.isEmpty)
                }
                Text("Only server-authorized registered libraries appear here. Source code is never materialized.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let error = controller.error {
                    Text(error).foregroundStyle(.red)
                }
            }
            .padding(8)
        }
        .task { await controller.refresh(profileID: profile.id) }
    }
}
