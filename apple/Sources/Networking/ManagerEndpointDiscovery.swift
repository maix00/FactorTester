import Foundation

/// Chooses the Manager endpoint for automatic mode.
///
/// The released client contains one public bootstrap IP only. The bootstrap
/// response is a server-owned directory of online public and internal nodes;
/// the client measures reachability from the current device and never infers
/// an address from its own network interfaces.
@MainActor
final class ManagerEndpointDiscoveryService {
    static let shared = ManagerEndpointDiscoveryService()

    private struct PublicSelection {
        let target: ManagerPublicTarget
        let info: ManagerNetworkInfo
    }

    private var cachedPublicSelection: PublicSelection?
    private var cachedInternalSelections: [String: InternalSelection] = [:]
    private var knownOrganizationsWithoutInternalManager = Set<String>()
    private var publicSelectionTask: Task<PublicSelection?, Never>?

    private init() {}

    @discardableResult
    func selectBestManager(
        organizationID: String? = nil,
        force: Bool = false
    ) async -> ManagerPublicTarget? {
        let manager = ManagerConfig.shared
        if force {
            publicSelectionTask?.cancel()
            publicSelectionTask = nil
            cachedPublicSelection = nil
            cachedInternalSelections.removeAll()
            knownOrganizationsWithoutInternalManager.removeAll()
        } else if !manager.shouldDiscoverNearestPublicManager {
            return nil
        }

        guard let selection = await publicSelection() else {
            return nil
        }
        let publicTarget = selection.target

        if let organizationID = organizationID?.trimmingCharacters(
            in: .whitespacesAndNewlines
        ), !organizationID.isEmpty,
           let selectedInternal = await internalEndpoint(
               from: selection.info,
               organizationID: organizationID
           ) {
            manager.saveAutoDiscovered(
                endpoint: selectedInternal.endpoint,
                serverID: selectedInternal.serverID
            )
            await authenticateIfEnrolled(at: selectedInternal.endpoint)
            return publicTarget
        }

        manager.saveAutoDiscovered(
            endpoint: publicTarget.endpoint,
            serverID: publicTarget.serverID
        )
        await authenticateIfEnrolled(at: publicTarget.endpoint)
        return publicTarget
    }

    /// Runs the public concurrent probe once per app process. Login/logout or
    /// SwiftUI view reconstruction only reuses this result; the Settings
    /// force action is the explicit exception that clears this cache.
    private func publicSelection() async -> PublicSelection? {
        if let cachedPublicSelection {
            return cachedPublicSelection
        }

        if let publicSelectionTask {
            return await publicSelectionTask.value
        }

        let task = Task { @MainActor [self] in
            await performPublicSelection()
        }
        publicSelectionTask = task
        let result = await task.value
        publicSelectionTask = nil
        return result
    }

    private func performPublicSelection() async -> PublicSelection? {
        if let cachedPublicSelection {
            return cachedPublicSelection
        }

        let manager = ManagerConfig.shared
        let bootstrap = ManagerConfig.bakedPublicBootstrapEndpoint
        let seedEndpoints = Self.uniqueEndpoints([
            bootstrap,
            manager.baseURL,
        ].compactMap { $0 })
        let seedProbes = await ManagerNetworkInfoService.shared.probeAll(
            endpoints: seedEndpoints
        )
        guard !seedProbes.isEmpty else {
            // The baked address remains in ManagerConfig, so the next launch
            // can retry without turning a temporary outage into a permanent
            // manual setting.
            return nil
        }

        let suggestedTargets = seedProbes
            .flatMap { $0.info.publicCandidates }
            .reduce(into: [String: ManagerPublicTarget]()) { result, target in
                guard let endpoint = Self.normalizedEndpoint(target.endpoint)
                else { return }
                result[Self.endpointKey(endpoint)] = target
            }
        let publicEndpoints = Self.uniqueEndpoints(
            seedEndpoints
                + suggestedTargets.values.map { $0.endpoint }
        )
        let seedProbeByEndpoint = Dictionary(
            seedProbes.map { (Self.endpointKey($0.endpoint), $0) },
            uniquingKeysWith: { first, _ in first }
        )
        let additionalEndpoints = publicEndpoints.filter {
            seedProbeByEndpoint[Self.endpointKey($0)] == nil
        }
        let additionalProbes = await ManagerNetworkInfoService.shared
            .probeAll(endpoints: additionalEndpoints)
        let publicProbes = seedProbes + additionalProbes
        guard let selectedPublic = Self.selectPublicProbe(
            publicProbes,
            suggestedTargets: suggestedTargets
        ) else {
            return nil
        }
        let selection = PublicSelection(
            target: Self.publicTarget(
                for: selectedPublic,
                suggestedTargets: suggestedTargets
            ),
            info: selectedPublic.info
        )
        cachedPublicSelection = selection
        return selection
    }

    private func internalEndpoint(
        from info: ManagerNetworkInfo,
        organizationID: String
    ) async -> InternalSelection? {
        if let cached = cachedInternalSelections[organizationID] {
            return cached
        }
        if knownOrganizationsWithoutInternalManager.contains(organizationID) {
            return nil
        }

        var candidates: [URL: InternalSelection] = [:]
        for target in info.internalCandidates
        where target.online && target.managedOrganizations.contains(organizationID) {
            for endpoint in target.endpoints() {
                guard let normalized = Self.normalizedEndpoint(endpoint) else {
                    continue
                }
                candidates[normalized] = InternalSelection(
                    endpoint: normalized,
                    serverID: target.serverID
                )
            }
        }
        guard !candidates.isEmpty else {
            knownOrganizationsWithoutInternalManager.insert(organizationID)
            return nil
        }
        let probes = await ManagerNetworkInfoService.shared.probeAll(
            endpoints: Array(candidates.keys)
        )
        let result = probes
            .sorted { $0.latencyMS < $1.latencyMS }
            .compactMap { probe in
                candidates[probe.endpoint]
            }
            .first
        if let result {
            cachedInternalSelections[organizationID] = result
        } else {
            knownOrganizationsWithoutInternalManager.insert(organizationID)
        }
        return result
    }

    private func authenticateIfEnrolled(at endpoint: URL) async {
        guard ManagerDeviceKeyStore.load() != nil else { return }
        // Device authentication is best effort here. A public device may be
        // enrolled only on the public Manager, while an internal Manager can
        // still be the best data path for the logged-in organization.
        _ = try? await ManagerDeviceAuthenticationService.shared.authenticate(
            endpoint: endpoint
        )
    }

    private struct InternalSelection {
        let endpoint: URL
        let serverID: String
    }

    private static func selectPublicProbe(
        _ probes: [ManagerNetworkProbe],
        suggestedTargets: [String: ManagerPublicTarget]
    ) -> ManagerNetworkProbe? {
        probes
            .filter { $0.endpoint.scheme?.lowercased() == "https" }
            .sorted { left, right in
                if left.latencyMS != right.latencyMS {
                    return left.latencyMS < right.latencyMS
                }
                let leftTarget = suggestedTargets[endpointKey(left.endpoint)]
                let rightTarget = suggestedTargets[endpointKey(right.endpoint)]
                return (leftTarget?.load ?? 0) < (rightTarget?.load ?? 0)
            }
            .first
    }

    private static func publicTarget(
        for probe: ManagerNetworkProbe,
        suggestedTargets: [String: ManagerPublicTarget]
    ) -> ManagerPublicTarget {
        let suggested = suggestedTargets[endpointKey(probe.endpoint)]
        return ManagerPublicTarget(
            serverID: suggested?.serverID ?? probe.info.serverID,
            role: suggested?.role ?? probe.info.role,
            endpoint: probe.endpoint,
            latencyMS: probe.latencyMS,
            load: suggested?.load ?? 0
        )
    }

    private static func normalizedEndpoint(_ endpoint: URL) -> URL? {
        guard let scheme = endpoint.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              endpoint.host != nil else {
            return nil
        }
        var components = URLComponents(
            url: endpoint,
            resolvingAgainstBaseURL: false
        )
        components?.scheme = scheme
        components?.query = nil
        components?.fragment = nil
        return components?.url
    }

    private static func endpointKey(_ endpoint: URL) -> String {
        endpoint.absoluteString.trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        ).lowercased()
    }

    private static func uniqueEndpoints(_ endpoints: [URL]) -> [URL] {
        var seen = Set<String>()
        return endpoints.compactMap { endpoint in
            guard let normalized = normalizedEndpoint(endpoint),
                  seen.insert(endpointKey(normalized)).inserted else {
                return nil
            }
            return normalized
        }
    }
}
