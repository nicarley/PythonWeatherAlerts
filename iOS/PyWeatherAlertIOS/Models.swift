import Foundation

struct SavedLocation: Identifiable, Codable, Equatable, Hashable {
    let id: UUID
    var name: String
    var query: String
    var latitude: Double
    var longitude: Double
    var rules: LocationRules

    init(
        id: UUID = UUID(),
        name: String,
        query: String,
        latitude: Double,
        longitude: Double,
        rules: LocationRules = .default
    ) {
        self.id = id
        self.name = name
        self.query = query
        self.latitude = latitude
        self.longitude = longitude
        self.rules = rules
    }

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case query
        case latitude
        case longitude
        case rules
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        query = try container.decode(String.self, forKey: .query)
        latitude = try container.decode(Double.self, forKey: .latitude)
        longitude = try container.decode(Double.self, forKey: .longitude)
        rules = try container.decodeIfPresent(LocationRules.self, forKey: .rules) ?? .default
    }
}

struct LocationRules: Codable, Equatable, Hashable {
    var minimumSeverity: AlertSeverity
    var enabledKinds: [AlertKind]

    static let `default` = LocationRules(
        minimumSeverity: .minor,
        enabledKinds: [.warning, .watch, .advisory]
    )
}

struct RadarSource: Identifiable, Codable, Equatable, Hashable {
    let id: UUID
    var name: String
    var url: String

    init(id: UUID = UUID(), name: String, url: String) {
        self.id = id
        self.name = name
        self.url = url
    }
}

struct AppSettings: Codable, Equatable {
    var selectedLocationID: UUID
    var refreshInterval: TimeInterval
    var locations: [SavedLocation]
    var radarSources: [RadarSource]
    var selectedRadarSourceID: UUID
    var notificationsEnabled: Bool
    var notificationMinimumSeverity: AlertSeverity

    static let defaultLocation = SavedLocation(
        name: "Default",
        query: "62881",
        latitude: 38.3173,
        longitude: -88.9031
    )

    static let defaultRadarSources: [RadarSource] = [
        RadarSource(name: "N.W.S. Radar", url: "https://radar.weather.gov/"),
        RadarSource(name: "Windy.com", url: "https://www.windy.com/")
    ]

    static let `default`: AppSettings = {
        let location = defaultLocation
        let radar = defaultRadarSources[0]
        return AppSettings(
            selectedLocationID: location.id,
            refreshInterval: 900,
            locations: [location],
            radarSources: defaultRadarSources,
            selectedRadarSourceID: radar.id,
            notificationsEnabled: false,
            notificationMinimumSeverity: .severe
        )
    }()

    enum CodingKeys: String, CodingKey {
        case selectedLocationID
        case refreshInterval
        case locations
        case radarSources
        case selectedRadarSourceID
        case notificationsEnabled
        case notificationMinimumSeverity
    }

    init(
        selectedLocationID: UUID,
        refreshInterval: TimeInterval,
        locations: [SavedLocation],
        radarSources: [RadarSource],
        selectedRadarSourceID: UUID,
        notificationsEnabled: Bool,
        notificationMinimumSeverity: AlertSeverity
    ) {
        self.selectedLocationID = selectedLocationID
        self.refreshInterval = refreshInterval
        self.locations = locations
        self.radarSources = radarSources
        self.selectedRadarSourceID = selectedRadarSourceID
        self.notificationsEnabled = notificationsEnabled
        self.notificationMinimumSeverity = notificationMinimumSeverity
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        selectedLocationID = try container.decode(UUID.self, forKey: .selectedLocationID)
        refreshInterval = try container.decode(TimeInterval.self, forKey: .refreshInterval)
        locations = try container.decode([SavedLocation].self, forKey: .locations)
        radarSources = try container.decode([RadarSource].self, forKey: .radarSources)
        selectedRadarSourceID = try container.decode(UUID.self, forKey: .selectedRadarSourceID)
        notificationsEnabled = try container.decodeIfPresent(Bool.self, forKey: .notificationsEnabled) ?? false
        notificationMinimumSeverity = try container.decodeIfPresent(AlertSeverity.self, forKey: .notificationMinimumSeverity) ?? .severe
    }
}

enum AlertSeverity: String, Codable, CaseIterable, Identifiable {
    case minor
    case moderate
    case severe
    case extreme

    var id: String { rawValue }

    var rank: Int {
        switch self {
        case .minor:
            return 1
        case .moderate:
            return 2
        case .severe:
            return 3
        case .extreme:
            return 4
        }
    }

    var displayName: String {
        rawValue.capitalized
    }
}

enum AlertKind: String, Codable, CaseIterable, Identifiable {
    case warning
    case watch
    case advisory
    case other

    var id: String { rawValue }

    var displayName: String {
        rawValue.capitalized + "s"
    }
}

struct WeatherAlert: Identifiable, Hashable {
    let id: String
    let title: String
    let summary: String
    let severity: String
    let urgency: String
    let certainty: String
    let event: String
    let areaDescription: String
    let link: String
    let updated: String
    let expires: String

    var kind: AlertKind {
        let text = "\(title) \(event)".lowercased()
        if text.contains("warning") { return .warning }
        if text.contains("watch") { return .watch }
        if text.contains("advisory") { return .advisory }
        return .other
    }

    var severityRank: Int {
        switch severity.lowercased() {
        case "extreme":
            return 4
        case "severe":
            return 3
        case "moderate":
            return 2
        case "minor":
            return 1
        default:
            return 0
        }
    }

    var normalizedSeverity: AlertSeverity? {
        switch severity.lowercased() {
        case "extreme":
            return .extreme
        case "severe":
            return .severe
        case "moderate":
            return .moderate
        case "minor":
            return .minor
        default:
            return nil
        }
    }
}

struct ForecastPeriod: Identifiable, Hashable {
    let id: UUID = UUID()
    let name: String
    let startTime: String
    let temperatureText: String
    let windText: String
    let precipitationText: String
    let shortForecast: String
    let detailedForecast: String
    let isDaytime: Bool
}

struct LocationDashboard: Equatable {
    var alerts: [WeatherAlert]
    var hourlyForecast: [ForecastPeriod]
    var dailyForecast: [ForecastPeriod]
    var lastUpdated: Date?

    static let empty = LocationDashboard(alerts: [], hourlyForecast: [], dailyForecast: [], lastUpdated: nil)
}

struct ResolvedLocation {
    let latitude: Double
    let longitude: Double
    let suggestedName: String
}

struct LocationDraft: Identifiable {
    let id = UUID()
    let existingLocation: SavedLocation?
    var name: String
    var query: String
    var rules: LocationRules
}
