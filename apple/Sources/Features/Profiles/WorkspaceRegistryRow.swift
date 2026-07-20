import SwiftUI

struct WorkspaceRegistryRow: View {
    let workspace: LocalWorkspaceModel

    var body: some View {
        HStack(alignment: .top) {
            Image(systemName: accessIcon)
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(workspace.id)
                Text(workspace.path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Owner: \(workspace.ownerRef)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(accessLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var accessIcon: String {
        workspace.accessMode == "owner" ? "person.fill" : "person.2"
    }

    private var accessLabel: String {
        switch workspace.accessMode {
        case "owner": return "本人"
        case "granted": return "已授权"
        default: return "只读"
        }
    }
}
