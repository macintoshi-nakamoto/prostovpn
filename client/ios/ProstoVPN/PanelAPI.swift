import Foundation

enum PanelAPI {
    enum Failure: Error {
        case network

        case badCredentials

        case blocked

        case disabled

        case throttled(retryAfter: Int)

        case unauthorized

        case server(status: Int)

        case badResponse
    }

    struct Account: Decodable {
        let publicId: String
        let login: String
        let name: String?

        enum CodingKeys: String, CodingKey {
            case publicId = "public_id"
            case login, name
        }
    }

    struct Subscription: Decodable {
        let active: Bool
        let plan: String?
        let expiresAt: Date?
        let daysLeft: Int
        let trafficUsedBytes: Int64

        let trafficLimitBytes: Int64?
        let trafficLeftBytes: Int64?

        let trafficLow: Bool
        let expiresSoon: Bool
        let renewUrl: String?

        enum CodingKeys: String, CodingKey {
            case active, plan
            case expiresAt = "expires_at"
            case daysLeft = "days_left"
            case trafficUsedBytes = "traffic_used_bytes"
            case trafficLimitBytes = "traffic_limit_bytes"
            case trafficLeftBytes = "traffic_left_bytes"
            case trafficLow = "traffic_low"
            case expiresSoon = "expires_soon"
            case renewUrl = "renew_url"
        }

        var trafficExhausted: Bool {
            trafficLimitBytes != nil && (trafficLeftBytes ?? 0) <= 0
        }
    }

    struct Server: Decodable, Equatable {
        let id: Int
        let name: String
        let country: String?
        let countryEn: String?
        let city: String?
        let cityEn: String?
        let countryCode: String?
        let config: String?

        enum CodingKeys: String, CodingKey {
            case id, name, country, city, config
            case countryEn = "country_en"
            case cityEn = "city_en"
            case countryCode = "country_code"
        }

        func countryFor(lang: String) -> String? {
            lang == "en" ? (countryEn ?? country) : (country ?? countryEn)
        }

        func cityFor(lang: String) -> String? {
            lang == "en" ? (cityEn ?? city) : (city ?? cityEn)
        }
    }

    struct Session: Decodable {
        let token: String?
        let expiresAt: Date?
        let account: Account?
        let subscription: Subscription
        let servers: [Server]

        let notice: String?

        enum CodingKeys: String, CodingKey {
            case token, account, subscription, servers, notice
            case expiresAt = "expires_at"
        }
    }

    struct UpdateInfo: Decodable {
        let updateAvailable: Bool
        let version: String?
        let url: String?
        let changelog: String?
        let mandatory: Bool

        enum CodingKeys: String, CodingKey {
            case updateAvailable = "update_available"
            case version, url, changelog, mandatory
        }
    }

    static var baseURL: URL {
        let raw = (Bundle.main.object(forInfoDictionaryKey: "PanelURL") as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard let url = URL(string: raw), url.scheme == "https" else {
            fatalError("PanelURL в Info.plist пуст или не https — соберите с -PanelURL=https://ваш-домен")
        }
        return url
    }

    static func login(
        login: String,
        password: String,
        deviceId: String,
        deviceName: String
    ) async throws -> Session {
        try await post(
            "/api/v1/login",
            body: [
                "login": login,
                "password": password,
                "platform": "ios",
                "app_version": appVersion,
                "device_id": deviceId,
                "device_name": deviceName,
            ]
        )
    }

    static func servers(token: String) async throws -> Session {
        try await get("/api/v1/servers", token: token)
    }

    static func logout(token: String) async {
        _ = try? await postRaw("/api/v1/logout", body: [:], token: token)
    }

    static func heartbeat(token: String) async {
        _ = try? await postRaw("/api/v1/heartbeat", body: [:], token: token)
    }

    static func checkUpdate(current: String) async throws -> UpdateInfo {
        var components = URLComponents(url: baseURL.appendingPathComponent("api/v1/version"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "platform", value: "ios"),
            URLQueryItem(name: "current", value: current),
        ]
        guard let url = components?.url else { throw Failure.badResponse }
        let (data, response) = try await send(URLRequest(url: url))
        try check(response, data: data)
        return try decoder.decode(UpdateInfo.self, from: data)
    }

    static var appVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()

        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]

        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            if let date = withFraction.date(from: text) ?? plain.date(from: text) {
                return date
            }

            let fallback = DateFormatter()
            fallback.locale = Locale(identifier: "en_US_POSIX")
            fallback.timeZone = TimeZone(identifier: "UTC")
            fallback.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
            if let date = fallback.date(from: text) { return date }
            fallback.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            if let date = fallback.date(from: text) { return date }
            throw Failure.badResponse
        }
        return decoder
    }()

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30

        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.httpAdditionalHeaders = ["Accept": "application/json"]
        return URLSession(configuration: config)
    }()

    private static func get<T: Decodable>(_ path: String, token: String?) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        request.httpMethod = "GET"
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await send(request)
        try check(response, data: data)
        return try decode(data)
    }

    private static func post<T: Decodable>(_ path: String, body: [String: Any], token: String? = nil) async throws -> T {
        let data = try await postRaw(path, body: body, token: token)
        return try decode(data)
    }

    @discardableResult
    private static func postRaw(_ path: String, body: [String: Any], token: String? = nil) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await send(request)
        try check(response, data: data)
        return data
    }

    private static func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw Failure.network
        }
    }

    private static func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw Failure.badResponse
        }
    }

    private static func check(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw Failure.badResponse }
        if (200..<300).contains(http.statusCode) { return }

        let code = http.value(forHTTPHeaderField: "X-Error-Code") ?? ""
        switch code {
        case "bad_credentials": throw Failure.badCredentials
        case "blocked": throw Failure.blocked
        case "disabled": throw Failure.disabled
        case "throttled":
            let retry = Int(http.value(forHTTPHeaderField: "Retry-After") ?? "") ?? 60
            throw Failure.throttled(retryAfter: retry)
        default: break
        }

        switch http.statusCode {
        case 401, 403: throw Failure.unauthorized
        case 429: throw Failure.throttled(retryAfter: 60)
        default: throw Failure.server(status: http.statusCode)
        }
    }
}
