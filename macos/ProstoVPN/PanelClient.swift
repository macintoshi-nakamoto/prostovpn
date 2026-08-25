import Foundation

struct PanelServer: Codable, Identifiable, Equatable {
    var id: Int

    var name: String
    var country: String?
    var country_en: String?
    var city: String?
    var city_en: String?
    var country_code: String?

    var config: String

    var host: String = ""

    var alt_ports: [Int] = []

    init(
        id: Int,
        name: String,
        country: String? = nil,
        country_en: String? = nil,
        city: String? = nil,
        city_en: String? = nil,
        country_code: String? = nil,
        config: String,
        host: String = "",
        alt_ports: [Int] = []
    ) {
        self.id = id
        self.name = name
        self.country = country
        self.country_en = country_en
        self.city = city
        self.city_en = city_en
        self.country_code = country_code
        self.config = config
        self.host = host.isEmpty ? (AccessKeyParser.endpointHost(in: config) ?? "") : host
        self.alt_ports = alt_ports.filter { $0 > 0 && $0 < 65536 }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let config = try container.decodeIfPresent(String.self, forKey: .config) ?? ""
        self.init(
            id: try container.decodeIfPresent(Int.self, forKey: .id) ?? 0,
            name: try container.decodeIfPresent(String.self, forKey: .name) ?? "",
            country: try container.decodeIfPresent(String.self, forKey: .country),
            country_en: try container.decodeIfPresent(String.self, forKey: .country_en),
            city: try container.decodeIfPresent(String.self, forKey: .city),
            city_en: try container.decodeIfPresent(String.self, forKey: .city_en),
            country_code: try container.decodeIfPresent(String.self, forKey: .country_code),
            config: config,
            host: try container.decodeIfPresent(String.self, forKey: .host) ?? "",
            alt_ports: try container.decodeIfPresent([Int].self, forKey: .alt_ports) ?? []
        )
    }

    func name(lang: String) -> String {
        let localized = lang == "en" ? country_en : country
        return localized?.nilIfEmpty ?? country?.nilIfEmpty ?? name.nilIfEmpty ?? host
    }

    func city(lang: String) -> String? {
        let localized = lang == "en" ? city_en : city
        return localized?.nilIfEmpty ?? city?.nilIfEmpty
    }

    var flag: String {
        guard let code = country_code, !code.isEmpty else { return "🌐" }
        return flagEmoji(countryCode: code)
    }
}

struct PanelSubscription: Codable, Equatable {
    var active: Bool = false
    var plan: String?
    var expires_at: Date?
    var days_left: Int?
    var traffic_used_bytes: Int64 = 0

    var traffic_limit_bytes: Int64?
    var traffic_left_bytes: Int64?

    var traffic_low: Bool = false

    var expires_soon: Bool = false

    var renew_url: String?

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        active = try c.decodeIfPresent(Bool.self, forKey: .active) ?? false
        plan = try c.decodeIfPresent(String.self, forKey: .plan)
        expires_at = try c.decodeIfPresent(Date.self, forKey: .expires_at)
        days_left = try c.decodeIfPresent(Int.self, forKey: .days_left)
        traffic_used_bytes = try c.decodeIfPresent(Int64.self, forKey: .traffic_used_bytes) ?? 0
        traffic_limit_bytes = try c.decodeIfPresent(Int64.self, forKey: .traffic_limit_bytes)
        traffic_left_bytes = try c.decodeIfPresent(Int64.self, forKey: .traffic_left_bytes)
        traffic_low = try c.decodeIfPresent(Bool.self, forKey: .traffic_low) ?? false
        expires_soon = try c.decodeIfPresent(Bool.self, forKey: .expires_soon) ?? false
        renew_url = try c.decodeIfPresent(String.self, forKey: .renew_url)
    }
}

struct PanelAccount: Codable, Equatable {
    var public_id: String = ""
    var login: String = ""
    var name: String?

    init(public_id: String = "", login: String = "", name: String? = nil) {
        self.public_id = public_id
        self.login = login
        self.name = name
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        public_id = try c.decodeIfPresent(String.self, forKey: .public_id) ?? ""
        login = try c.decodeIfPresent(String.self, forKey: .login) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name)
    }

    var displayName: String { name?.nilIfEmpty ?? login }
}

struct PanelLogin: Decodable {
    var token: String
    var expires_at: Date?
    var account: PanelAccount
    var subscription: PanelSubscription
    var servers: [PanelServer]

    var notice: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(String.self, forKey: .token)
        expires_at = try c.decodeIfPresent(Date.self, forKey: .expires_at)
        account = try c.decodeIfPresent(PanelAccount.self, forKey: .account) ?? PanelAccount()
        subscription = try c.decodeIfPresent(PanelSubscription.self, forKey: .subscription) ?? PanelSubscription()
        servers = try c.decodeIfPresent([PanelServer].self, forKey: .servers) ?? []
        notice = try c.decodeIfPresent(String.self, forKey: .notice)
    }

    private enum CodingKeys: String, CodingKey {
        case token, expires_at, account, subscription, servers, notice
    }
}

struct PanelServers: Decodable {
    var subscription: PanelSubscription
    var servers: [PanelServer]
    var notice: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        subscription = try c.decodeIfPresent(PanelSubscription.self, forKey: .subscription) ?? PanelSubscription()
        servers = try c.decodeIfPresent([PanelServer].self, forKey: .servers) ?? []
        notice = try c.decodeIfPresent(String.self, forKey: .notice)
    }

    private enum CodingKeys: String, CodingKey {
        case subscription, servers, notice
    }
}

struct PanelUpdate: Decodable, Equatable {
    var update_available: Bool = false
    var version: String?
    var url: String?
    var changelog: String?
    var size_bytes: Int64?
    var sha256: String?

    var mandatory: Bool = false

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        update_available = try c.decodeIfPresent(Bool.self, forKey: .update_available) ?? false
        version = try c.decodeIfPresent(String.self, forKey: .version)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        changelog = try c.decodeIfPresent(String.self, forKey: .changelog)
        size_bytes = try c.decodeIfPresent(Int64.self, forKey: .size_bytes)
        sha256 = try c.decodeIfPresent(String.self, forKey: .sha256)
        mandatory = try c.decodeIfPresent(Bool.self, forKey: .mandatory) ?? false
    }

    private enum CodingKeys: String, CodingKey {
        case update_available, version, url, changelog, size_bytes, sha256, mandatory
    }
}

enum PanelError: LocalizedError {
    case badURL
    case unauthorized(String)

    case throttled(String, Int)
    case http(Int, String)
    case transport(String)

    var status: Int {
        switch self {
        case .badURL, .transport: return 0
        case .unauthorized: return 401
        case .throttled: return 429
        case .http(let code, _): return code
        }
    }

    var revokesSession: Bool {
        switch self {
        case .unauthorized: return true
        case .http(let code, _): return code == 403
        default: return false
        }
    }

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "неверный адрес панели"
        case .unauthorized(let detail):
            return detail.nilIfEmpty ?? "неверный логин или пароль"
        case .throttled(let detail, let seconds):
            if let text = detail.nilIfEmpty { return text }
            return seconds > 0
                ? "слишком много попыток — попробуйте через \(seconds) с"
                : "слишком много попыток — попробуйте позже"
        case .http(let code, let detail):
            return detail.nilIfEmpty ?? "панель ответила \(code)"
        case .transport(let message):
            return message
        }
    }
}

actor PanelClient {
    private var baseURL: URL
    private let session: URLSession

    init(baseURL: URL) {
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        configuration.waitsForConnectivity = false
        session = URLSession(configuration: configuration)
    }

    func setBaseURL(_ url: URL) {
        baseURL = url
    }

    func login(
        login: String,
        password: String,
        deviceID: String,
        deviceName: String
    ) async throws -> PanelLogin {
        try await request(
            "login",
            method: "POST",
            body: [
                "login": login,
                "password": password,
                "platform": "macos",
                "app_version": AppInfo.version,
                "device_id": deviceID,
                "device_name": String(deviceName.prefix(96)),
            ],
            token: nil
        )
    }

    func servers(token: String) async throws -> PanelServers {
        try await request("servers", method: "GET", body: nil, token: token)
    }

    @discardableResult
    func heartbeat(token: String) async throws -> [String: JSONAny] {
        try await request("heartbeat", method: "POST", body: nil, token: token)
    }

    func checkUpdate(current: String) async throws -> PanelUpdate {
        let escaped = current.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? current
        return try await request(
            "version?platform=macos&current=\(escaped)",
            method: "GET",
            body: nil,
            token: nil
        )
    }

    func logout(token: String) async {
        _ = try? await request("logout", method: "POST", body: nil, token: token) as [String: JSONAny]
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String,
        body: [String: String]?,
        token: String?
    ) async throws -> T {
        guard let url = URL(string: "api/v1/\(path)", relativeTo: baseURL) else {
            throw PanelError.badURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw PanelError.transport(error.localizedDescription)
        }

        let http = response as? HTTPURLResponse
        let code = http?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])
                .flatMap { $0?["detail"] as? String } ?? ""
            if code == 429 {
                let retry = Int(http?.value(forHTTPHeaderField: "Retry-After") ?? "") ?? 0
                throw PanelError.throttled(detail, retry)
            }
            throw code == 401 ? PanelError.unauthorized(detail) : PanelError.http(code, detail)
        }

        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw PanelError.transport("панель ответила неожиданным форматом")
        }
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            let withFraction = ISO8601DateFormatter()
            withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = withFraction.date(from: text) { return date }

            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let date = plain.date(from: text) { return date }

            let naive = DateFormatter()
            naive.locale = Locale(identifier: "en_US_POSIX")
            naive.timeZone = TimeZone(identifier: "UTC")
            for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss"] {
                naive.dateFormat = format
                if let date = naive.date(from: text) { return date }
            }
            throw DecodingError.dataCorruptedError(
                in: try decoder.singleValueContainer(),
                debugDescription: "неизвестный формат даты: \(text)"
            )
        }
        return decoder
    }()
}

struct JSONAny: Decodable {
    init(from decoder: Decoder) throws {
        _ = try? decoder.singleValueContainer()
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

enum AppInfo {
    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
    }
}
