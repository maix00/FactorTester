import CoreGraphics
import Foundation

struct ResearchGraphEdgeRoute: Identifiable {
    let id: String
    let start: CGPoint
    let control1: CGPoint
    let control2: CGPoint
    let end: CGPoint

    var labelPoint: CGPoint { point(at: 0.5) }

    func point(at value: CGFloat) -> CGPoint {
        let t = min(max(value, 0), 1)
        let inverse = 1 - t
        let x = inverse * inverse * inverse * start.x
            + 3 * inverse * inverse * t * control1.x
            + 3 * inverse * t * t * control2.x
            + t * t * t * end.x
        let y = inverse * inverse * inverse * start.y
            + 3 * inverse * inverse * t * control1.y
            + 3 * inverse * t * t * control2.y
            + t * t * t * end.y
        return CGPoint(x: x, y: y)
    }

    func distance(to point: CGPoint) -> CGFloat {
        var best = CGFloat.greatestFiniteMagnitude
        var previous = start
        for step in 1...28 {
            let current = self.point(at: CGFloat(step) / 28)
            best = min(best, point.distance(toSegmentFrom: previous, to: current))
            previous = current
        }
        return best
    }
}

struct ResearchGraphCanvasLayout {
    static let nodeSize = CGSize(width: 236, height: 108)

    let nodeFrames: [String: CGRect]
    let edgeRoutes: [String: ResearchGraphEdgeRoute]
    let canvasSize: CGSize

    init(graph: ResearchGraphVersion) {
        let nodeIDs = graph.nodes.map(\.id)
        let ranks = Self.ranks(
            nodeIDs: nodeIDs,
            entryNode: graph.entryNode,
            outgoingEdges: graph.outgoingEdges(from:)
        )
        let grouped = Dictionary(grouping: nodeIDs) { ranks[$0, default: 0] }
        let maxRank = ranks.values.max() ?? 0
        let horizontalGap: CGFloat = 150
        let verticalGap: CGFloat = 42
        let inset: CGFloat = 42
        let tallestColumn = grouped.values.map(\.count).max() ?? 1
        let height = max(
            360,
            CGFloat(tallestColumn) * Self.nodeSize.height
                + CGFloat(max(tallestColumn - 1, 0)) * verticalGap
                + inset * 2
        )

        var frames: [String: CGRect] = [:]
        for rank in 0...maxRank {
            let nodes = grouped[rank] ?? []
            let columnHeight = CGFloat(nodes.count) * Self.nodeSize.height
                + CGFloat(max(nodes.count - 1, 0)) * verticalGap
            let originY = max(inset, (height - columnHeight) / 2)
            for (index, nodeID) in nodes.enumerated() {
                frames[nodeID] = CGRect(
                    x: inset + CGFloat(rank) * (Self.nodeSize.width + horizontalGap),
                    y: originY + CGFloat(index) * (Self.nodeSize.height + verticalGap),
                    width: Self.nodeSize.width,
                    height: Self.nodeSize.height
                )
            }
        }

        var routes: [String: ResearchGraphEdgeRoute] = [:]
        for (index, edge) in graph.edges.enumerated() {
            guard edge.fromNode != "*",
                  let source = frames[edge.fromNode],
                  let target = frames[edge.toNode] else { continue }
            routes[edge.id] = Self.route(
                edgeID: edge.id,
                source: source,
                target: target,
                lane: index % 5
            )
        }

        nodeFrames = frames
        edgeRoutes = routes
        canvasSize = CGSize(
            width: inset * 2 + CGFloat(maxRank + 1) * Self.nodeSize.width
                + CGFloat(maxRank) * horizontalGap,
            height: height
        )
    }

    func nearestEdge(to point: CGPoint, maximumDistance: CGFloat = 14) -> String? {
        edgeRoutes.values
            .map { ($0.id, $0.distance(to: point)) }
            .filter { $0.1 <= maximumDistance }
            .min { $0.1 < $1.1 }?.0
    }

    private static func ranks(
        nodeIDs: [String],
        entryNode: String,
        outgoingEdges: (String) -> [ResearchGraphEdge]
    ) -> [String: Int] {
        let knownNodes = Set(nodeIDs)
        let start = knownNodes.contains(entryNode) ? entryNode : nodeIDs.first
        guard let start else { return [:] }
        var ranks = [start: 0]
        var queue = [start]
        var cursor = 0
        while cursor < queue.count {
            let source = queue[cursor]
            cursor += 1
            let nextRank = ranks[source, default: 0] + 1
            for edge in outgoingEdges(source) {
                guard knownNodes.contains(edge.toNode),
                      ranks[edge.toNode] == nil else { continue }
                ranks[edge.toNode] = nextRank
                queue.append(edge.toNode)
            }
        }
        var fallbackRank = (ranks.values.max() ?? -1) + 1
        for nodeID in nodeIDs where ranks[nodeID] == nil {
            ranks[nodeID] = fallbackRank
            fallbackRank += 1
        }
        return ranks
    }

    private static func route(
        edgeID: String,
        source: CGRect,
        target: CGRect,
        lane: Int
    ) -> ResearchGraphEdgeRoute {
        if source == target {
            let start = CGPoint(x: source.maxX - 24, y: source.minY)
            let end = CGPoint(x: source.maxX, y: source.minY + 24)
            return ResearchGraphEdgeRoute(
                id: edgeID,
                start: start,
                control1: CGPoint(x: source.maxX + 70, y: source.minY - 70),
                control2: CGPoint(x: source.maxX + 70, y: source.minY + 8),
                end: end
            )
        }

        let laneOffset = CGFloat(lane - 2) * 8
        if target.midX > source.midX {
            let start = CGPoint(x: source.maxX, y: source.midY + laneOffset)
            let end = CGPoint(x: target.minX, y: target.midY + laneOffset)
            let bend = max(56, (end.x - start.x) * 0.45)
            return ResearchGraphEdgeRoute(
                id: edgeID,
                start: start,
                control1: CGPoint(x: start.x + bend, y: start.y),
                control2: CGPoint(x: end.x - bend, y: end.y),
                end: end
            )
        }

        let start = CGPoint(x: source.minX, y: source.midY + laneOffset)
        let end = CGPoint(x: target.maxX, y: target.midY + laneOffset)
        let arcY = max(18, min(source.minY, target.minY) - 34 - CGFloat(lane) * 9)
        return ResearchGraphEdgeRoute(
            id: edgeID,
            start: start,
            control1: CGPoint(x: start.x - 64, y: arcY),
            control2: CGPoint(x: end.x + 64, y: arcY),
            end: end
        )
    }
}

private extension CGPoint {
    func distance(toSegmentFrom start: CGPoint, to end: CGPoint) -> CGFloat {
        let dx = end.x - start.x
        let dy = end.y - start.y
        let lengthSquared = dx * dx + dy * dy
        guard lengthSquared > 0 else {
            return hypot(x - start.x, y - start.y)
        }
        let projection = min(
            max(((x - start.x) * dx + (y - start.y) * dy) / lengthSquared, 0),
            1
        )
        let nearest = CGPoint(
            x: start.x + projection * dx,
            y: start.y + projection * dy
        )
        return hypot(x - nearest.x, y - nearest.y)
    }
}
