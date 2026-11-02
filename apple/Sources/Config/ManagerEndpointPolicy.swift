import Foundation
import Network

enum ManagerEndpointPolicy {
    static func isLoopback(_ host: String) -> Bool {
        let value = normalized(host)
        if value == "localhost" { return true }
        if let ip = IPv4Address(value) { return ip.rawValue.first == 127 }
        if let ip = IPv6Address(value) { return ip.rawValue == IPv6Address("::1")?.rawValue }
        return false
    }

    /// Permit plain HTTP only for actual private IP literals and localhost.
    /// Hostname prefixes such as `fc.example` are not IPv6 addresses.
    static func isPrivateNetwork(_ host: String) -> Bool {
        let value = normalized(host)
        if isLoopback(value) { return true }
        if let ip = IPv6Address(value) {
            let bytes = Array(ip.rawValue)
            return (bytes[0] & 0xfe) == 0xfc || (bytes[0] == 0xfe && (bytes[1] & 0xc0) == 0x80)
        }
        if let ip = IPv4Address(value) {
            let bytes = Array(ip.rawValue)
            return bytes[0] == 10 || (bytes[0] == 172 && (16...31).contains(Int(bytes[1])))
                || (bytes[0] == 192 && bytes[1] == 168)
        }
        return false
    }

    private static func normalized(_ host: String) -> String {
        host.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}
