import Foundation

struct ResearchHTTPResponse {
    let data: Data
    let statusCode: Int
    let etag: String?
}

protocol ProfileResearchTransport {
    func data(for request: URLRequest) async throws -> ResearchHTTPResponse
    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error>
}

protocol ResearchRefreshClock {
    func sleep(seconds: Double) async throws
}

struct SystemResearchRefreshClock: ResearchRefreshClock {
    func sleep(seconds: Double) async throws {
        try await Task.sleep(
            nanoseconds: UInt64(max(seconds, 0) * 1_000_000_000)
        )
    }
}

final class URLSessionProfileResearchTransport: ProfileResearchTransport {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("Invalid server response")
        }
        return ResearchHTTPResponse(
            data: data,
            statusCode: http.statusCode,
            etag: http.value(forHTTPHeaderField: "ETag")
        )
    }

    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse,
                          (200..<300).contains(http.statusCode) else {
                        throw APIError.transport("SSE connection failed")
                    }
                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        if line.hasPrefix("data:") {
                            continuation.yield(())
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

enum ConditionalProjection<Value> {
    case notModified
    case value(Value, responseETag: String?)
}

struct ProfileResearchService {
    let baseURL: URL
    let transport: ProfileResearchTransport
    private let decoder = JSONDecoder()

    init(
        baseURL: URL,
        transport: ProfileResearchTransport =
            URLSessionProfileResearchTransport()
    ) {
        self.baseURL = baseURL
        self.transport = transport
    }

    func list(
        workspaceRef: String,
        after: String? = nil
    ) async throws -> ProfileResearchListResponse {
        let path = path(
            "/api/profile-research",
            query: [
                URLQueryItem(name: "workspace_ref", value: workspaceRef),
                URLQueryItem(name: "limit", value: "20"),
                URLQueryItem(name: "after", value: after),
            ]
        )
        return try await value(path: path, as: ProfileResearchListResponse.self)
    }

    func workPackageDetail(
        href: String,
        etag: String? = nil
    ) async throws -> ConditionalProjection<ProfileResearchWorkPackageDetail> {
        try await conditional(path: href, etag: etag)
    }

    func branchDetail(
        href: String,
        etag: String? = nil
    ) async throws -> ConditionalProjection<ProfileResearchDetail> {
        try await conditional(path: href, etag: etag)
    }

    // Temporary source compatibility for callers that already hold a branch
    // detail href. New navigation first opens a Work Package.
    func detail(
        href: String,
        etag: String? = nil
    ) async throws -> ConditionalProjection<ProfileResearchDetail> {
        try await branchDetail(href: href, etag: etag)
    }

    func timeline(
        href: String,
        after: String? = nil,
        etag: String? = nil
    ) async throws -> ConditionalProjection<ProfileResearchTimelinePage> {
        let page = path(
            href,
            query: [
                URLQueryItem(name: "limit", value: "50"),
                URLQueryItem(name: "after", value: after),
            ]
        )
        return try await conditional(path: page, etag: etag)
    }

    func events(href: String) -> AsyncThrowingStream<Void, Error> {
        transport.events(for: request(path: href, etag: nil))
    }

    private func value<T: Decodable>(
        path: String,
        as type: T.Type
    ) async throws -> T {
        switch try await conditional(path: path, etag: nil, as: type) {
        case .notModified:
            throw APIError.transport("Unexpected not-modified response")
        case .value(let value, _):
            return value
        }
    }

    private func conditional<T: Decodable>(
        path: String,
        etag: String?,
        as type: T.Type = T.self
    ) async throws -> ConditionalProjection<T> {
        let response = try await transport.data(
            for: request(path: path, etag: etag)
        )
        if response.statusCode == 304 { return .notModified }
        guard (200..<300).contains(response.statusCode) else {
            if response.statusCode == 401 || response.statusCode == 403 {
                throw APIError.transport("没有权限读取该研究工作区")
            }
            throw APIError.transport(
                "Research projection HTTP \(response.statusCode)"
            )
        }
        return .value(
            try decoder.decode(type, from: response.data),
            responseETag: response.etag
        )
    }

    private func request(path: String, etag: String?) -> URLRequest {
        let url = URL(string: path, relativeTo: baseURL)!.absoluteURL
        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let etag {
            request.setValue(etag, forHTTPHeaderField: "If-None-Match")
        }
        return request
    }

    private func path(
        _ value: String,
        query: [URLQueryItem]
    ) -> String {
        var components = URLComponents()
        components.path = value
        components.queryItems = query.filter { $0.value != nil }
        return components.string ?? value
    }
}
