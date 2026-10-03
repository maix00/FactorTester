import Foundation

extension LocalProfileController {
    func saveAgent(
        profileID: String,
        agentID: String,
        role: String,
        workspaceID: String,
        instanceID: String,
        branchID: String
    ) async {
        var arguments = [
            "client", "profile", "agent", "set", profileID,
            "--agent-id", agentID, "--role", role,
        ]
        if role == "planning" {
            arguments += ["--workspace-id", workspaceID]
        } else {
            arguments += [
                "--instance-id", instanceID, "--branch-id", branchID,
            ]
        }
        await run(arguments)
    }

    func saveAdapter(
        profileID: String,
        adapterID: String,
        enabled: Bool,
        credentialRef: String,
        configurationRef: String
    ) async {
        var arguments = [
            "client", "profile", "adapter", "set", profileID,
            "--adapter-id", adapterID,
            enabled ? "--enabled" : "--disabled",
        ]
        if !credentialRef.isEmpty {
            arguments += ["--credential-ref", credentialRef]
        }
        if !configurationRef.isEmpty {
            arguments += ["--configuration-ref", configurationRef]
        }
        await run(arguments)
    }
}
