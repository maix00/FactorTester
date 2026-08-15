import Foundation
import XCTest
@testable import FTClient

final class ManagerObjectTransferServiceTests: XCTestCase {
    func testUploadIssuesMetadataOn7998ThenStreamsBytesTo7997() async throws {
        let content = Data("attachment bytes".utf8)
        let transport = ManagerTransferStubTransport(responses: [
            response(
                """
                {
                  "success": true,
                  "object": {
                    "object_id": "publication:attachment",
                    "size_bytes": 16,
                    "sha256": "2508f58332a50c3fee16cc39d28bd45b17d7c3d65ec32b7ebd024d55b7a1393d"
                  },
                  "access": {
                    "transfer_id": "transfer-1",
                    "url": "https://manager.example:7997/v1/transfers/transfer-1/upload",
                    "bearer": "upload-capability"
                  }
                }
                """
            ),
            ManagerTransferHTTPResponse(statusCode: 201, data: Data())
        ])
        let service = ManagerObjectTransferService(
            baseURL: URL(string: "https://manager.example:7998")!,
            managerToken: "manager-session",
            transport: transport
        )

        let receipt = try await service.uploadResearchAttachment(
            publicationID: "publication-1",
            attachmentID: "attachment-1",
            content: content,
            filename: "notes.txt",
            contentType: "text/plain"
        )

        XCTAssertEqual(receipt.transferID, "transfer-1")
        XCTAssertEqual(transport.requests.count, 2)
        XCTAssertEqual(transport.requests[0].url?.port, 7998)
        XCTAssertEqual(transport.requests[1].url?.port, 7997)
        XCTAssertEqual(
            transport.requests[1].value(forHTTPHeaderField: "Authorization"),
            "Bearer upload-capability"
        )
        XCTAssertEqual(transport.requests[1].httpBody, content)
        let body = try XCTUnwrap(transport.requests[0].httpBody)
        let payload = try XCTUnwrap(
            JSONSerialization.jsonObject(with: body) as? [String: Any]
        )
        XCTAssertEqual(payload["object_kind"] as? String, "research_attachment")
        XCTAssertEqual(payload["filename"] as? String, "notes.txt")
        XCTAssertEqual(payload["size_bytes"] as? Int, content.count)
        XCTAssertEqual(
            transport.requests[0].value(forHTTPHeaderField: "Authorization"),
            "Bearer manager-session"
        )
    }

    func testDownloadUses7997AndRejectsChangedAttachmentBytes() async throws {
        let expected = Data("attachment bytes".utf8)
        let transport = ManagerTransferStubTransport(responses: [
            response(
                """
                {
                  "success": true,
                  "object": {
                    "object_id": "publication:attachment",
                    "size_bytes": 16,
                    "sha256": "2508f58332a50c3fee16cc39d28bd45b17d7c3d65ec32b7ebd024d55b7a1393d"
                  },
                  "access": {
                    "transfer_id": "transfer-2",
                    "url": "https://manager.example:7997/v1/transfers/transfer-2/download",
                    "bearer": "download-capability",
                    "expected_size": 16
                  }
                }
                """
            ),
            ManagerTransferHTTPResponse(statusCode: 200, data: expected)
        ])
        let service = ManagerObjectTransferService(
            baseURL: URL(string: "https://manager.example:7998")!,
            managerToken: "manager-session",
            transport: transport
        )

        let value = try await service.downloadResearchAttachment(
            publicationID: "publication-1",
            attachmentID: "attachment-1"
        )

        XCTAssertEqual(value, expected)
        XCTAssertEqual(transport.requests[0].url?.path, "/api/transfers/objects/download-access")
        XCTAssertEqual(transport.requests[1].url?.port, 7997)
        XCTAssertEqual(
            transport.requests[1].value(forHTTPHeaderField: "Authorization"),
            "Bearer download-capability"
        )

        let badTransport = ManagerTransferStubTransport(responses: [
            response(
                """
                {
                  "success": true,
                  "object": {"size_bytes": 16, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
                  "access": {
                    "url": "https://manager.example:7997/v1/transfers/transfer-3/download",
                    "bearer": "download-capability",
                    "expected_size": 16
                  }
                }
                """
            ),
            ManagerTransferHTTPResponse(statusCode: 200, data: Data(repeating: 0, count: 16))
        ])
        let badService = ManagerObjectTransferService(
            baseURL: URL(string: "https://manager.example:7998")!,
            managerToken: "manager-session",
            transport: badTransport
        )
        do {
            _ = try await badService.downloadResearchAttachment(
                publicationID: "publication-1",
                attachmentID: "attachment-1"
            )
            XCTFail("A changed attachment must fail the hash check")
        } catch let error as APIError {
            XCTAssertTrue(error.localizedDescription.contains("完整性"))
        }
    }

    private func response(_ json: String) -> ManagerTransferHTTPResponse {
        ManagerTransferHTTPResponse(statusCode: 201, data: Data(json.utf8))
    }
}

private final class ManagerTransferStubTransport: ManagerTransferTransport {
    private(set) var requests: [URLRequest] = []
    private var responses: [ManagerTransferHTTPResponse]

    init(responses: [ManagerTransferHTTPResponse]) {
        self.responses = responses
    }

    func data(
        for request: URLRequest,
        allowedHosts: Set<String>
    ) async throws -> ManagerTransferHTTPResponse {
        requests.append(request)
        guard !responses.isEmpty else {
            throw APIError.transport("stub response queue is empty")
        }
        return responses.removeFirst()
    }
}
