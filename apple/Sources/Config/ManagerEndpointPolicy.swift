import Foundation

enum ManagerEndpointPolicy {
    static func isLoopback(_ host: String) -> Bool {
        ["127.0.0.1", "localhost", "::1"].contains(normalized(host))
    }

    static func isPrivateNetwork(_ host: String) -> Bool {
        let value = normalized(host)
        if isLoopback(value) { return true }
        if value.hasPrefix("fc") || value.hasPrefix("fd") { return true }
        if value.hasPrefix("fe8") || value.hasPrefix("fe9")
            || value.hasPrefix("fea") || value.hasPrefix("feb") {
            return true
        }
        let octets = value.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else {
            return false
        }
        return octets[0] == 10
            || (octets[0] == 172 && (16...31).contains(octets[1]))
            || (octets[0] == 192 && octets[1] == 168)
            || octets[0] == 127
    }

    private static func normalized(_ host: String) -> String {
        host.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}
