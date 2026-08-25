import Foundation
#if canImport(ActivityKit)
import ActivityKit

struct ConnectionAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var startedAt: Date
    }

    var serverName: String
    var serverFlag: String
    var statusLabel: String
}
#endif
