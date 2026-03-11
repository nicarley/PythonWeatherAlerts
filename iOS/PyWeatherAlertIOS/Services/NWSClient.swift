import CoreLocation
import Foundation

enum NWSClientError: LocalizedError {
    case invalidLocation
    case invalidResponse
    case missingForecastURL

    var errorDescription: String? {
        switch self {
        case .invalidLocation:
            return "The location could not be resolved."
        case .invalidResponse:
            return "The weather service returned an unexpected response."
        case .missingForecastURL:
            return "The weather service did not return forecast URLs for this location."
        }
    }
}

actor NWSClient {
    private let session: URLSession
    private let decoder: JSONDecoder
    private let userAgent = "PyWeatherAlertIOS/1.0 (iPad native rewrite)"

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
    }

    func resolveLocation(query: String) async throws -> ResolvedLocation {
        if let parsed = parseLatLon(from: query) {
            return ResolvedLocation(
                latitude: parsed.latitude,
                longitude: parsed.longitude,
                suggestedName: query.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        }

        if let station = try await resolveStation(query: query) {
            return station
        }

        if let geocoded = try await geocode(query: query) {
            return geocoded
        }

        throw NWSClientError.invalidLocation
    }

    func fetchDashboard(for location: SavedLocation) async throws -> LocationDashboard {
        let forecastURLs = try await fetchForecastURLs(latitude: location.latitude, longitude: location.longitude)
        guard let hourlyURLString = forecastURLs.hourly, let dailyURLString = forecastURLs.daily else {
            throw NWSClientError.missingForecastURL
        }

        async let alertsTask = fetchAlerts(latitude: location.latitude, longitude: location.longitude)
        async let hourlyTask = fetchForecastPeriods(urlString: hourlyURLString, limit: 8)
        async let dailyTask = fetchForecastPeriods(urlString: dailyURLString, limit: 10)

        let alerts = try await alertsTask
        let sortedAlerts = alerts.sorted { lhs, rhs in
            if lhs.severityRank == rhs.severityRank {
                return lhs.title < rhs.title
            }
            return lhs.severityRank > rhs.severityRank
        }

        return LocationDashboard(
            alerts: sortedAlerts,
            hourlyForecast: try await hourlyTask,
            dailyForecast: try await dailyTask,
            lastUpdated: Date()
        )
    }

    private func parseLatLon(from query: String) -> (latitude: Double, longitude: Double)? {
        let parts = query.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        guard parts.count == 2,
              let latitude = Double(parts[0]),
              let longitude = Double(parts[1]),
              (-90.0...90.0).contains(latitude),
              (-180.0...180.0).contains(longitude) else {
            return nil
        }

        return (latitude, longitude)
    }

    private func resolveStation(query: String) async throws -> ResolvedLocation? {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard trimmed.count == 3 || trimmed.count == 4 else {
            return nil
        }
        guard trimmed.allSatisfy({ $0.isLetter }) else {
            return nil
        }

        let stationID = trimmed.count == 3 ? "K\(trimmed)" : trimmed
        guard let url = URL(string: "https://api.weather.gov/stations/\(stationID)") else {
            return nil
        }

        do {
            let response: StationResponse = try await performRequest(url: url)
            guard response.geometry.coordinates.count == 2 else {
                throw NWSClientError.invalidResponse
            }
            return ResolvedLocation(
                latitude: response.geometry.coordinates[1],
                longitude: response.geometry.coordinates[0],
                suggestedName: response.properties.name ?? stationID
            )
        } catch {
            return nil
        }
    }

    private func geocode(query: String) async throws -> ResolvedLocation? {
        let geocoder = CLGeocoder()
        let placemarks = try await geocoder.geocodeAddressString(query)
        guard let placemark = placemarks.first,
              let coordinate = placemark.location?.coordinate else {
            return nil
        }

        let suggestedName = [placemark.locality, placemark.administrativeArea]
            .compactMap { $0 }
            .joined(separator: ", ")

        return ResolvedLocation(
            latitude: coordinate.latitude,
            longitude: coordinate.longitude,
            suggestedName: suggestedName.isEmpty ? query : suggestedName
        )
    }

    private func fetchForecastURLs(latitude: Double, longitude: Double) async throws -> ForecastURLResponse.Properties {
        guard let url = URL(string: "https://api.weather.gov/points/\(latitude),\(longitude)") else {
            throw NWSClientError.invalidResponse
        }

        let response: ForecastURLResponse = try await performRequest(url: url)
        return response.properties
    }

    private func fetchAlerts(latitude: Double, longitude: Double) async throws -> [WeatherAlert] {
        var components = URLComponents(string: "https://api.weather.gov/alerts/active")
        components?.queryItems = [
            URLQueryItem(name: "point", value: "\(latitude),\(longitude)"),
            URLQueryItem(name: "certainty", value: "Possible,Likely,Observed"),
            URLQueryItem(name: "severity", value: "Extreme,Severe,Moderate,Minor"),
            URLQueryItem(name: "urgency", value: "Immediate,Future,Expected")
        ]

        guard let url = components?.url else {
            throw NWSClientError.invalidResponse
        }

        let response: AlertsResponse = try await performRequest(url: url)
        return response.features.map { feature in
            let event = feature.properties.event ?? "Alert"
            let headline = feature.properties.headline ?? event
            let title = headline == event ? event : "\(event): \(headline)"
            return WeatherAlert(
                id: feature.properties.apiIdentifier ?? feature.id ?? UUID().uuidString,
                title: title,
                summary: feature.properties.description ?? "No summary available.",
                severity: feature.properties.severity ?? "Unknown",
                urgency: feature.properties.urgency ?? "Unknown",
                certainty: feature.properties.certainty ?? "Unknown",
                event: event,
                areaDescription: feature.properties.areaDescription ?? "",
                link: feature.properties.apiIdentifier ?? feature.properties.uri ?? "",
                updated: feature.properties.updated ?? "",
                expires: feature.properties.expires ?? ""
            )
        }
    }

    private func fetchForecastPeriods(urlString: String, limit: Int) async throws -> [ForecastPeriod] {
        guard let url = URL(string: urlString) else {
            throw NWSClientError.invalidResponse
        }

        let response: ForecastResponse = try await performRequest(url: url)
        return response.properties.periods.prefix(limit).map { period in
            ForecastPeriod(
                name: period.name,
                startTime: formatTime(period.startTime),
                temperatureText: "\(period.temperature)°\(period.temperatureUnit)",
                windText: "\(period.windSpeed) \(period.windDirection)",
                precipitationText: precipitationText(from: period.probabilityOfPrecipitation?.value),
                shortForecast: period.shortForecast,
                detailedForecast: period.detailedForecast,
                isDaytime: period.isDaytime
            )
        }
    }

    private func precipitationText(from value: Double?) -> String {
        guard let value else {
            return "--"
        }
        return "\(Int(value.rounded()))%"
    }

    private func formatTime(_ rawValue: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: rawValue) else {
            return rawValue
        }

        let output = DateFormatter()
        output.dateStyle = .none
        output.timeStyle = .short
        return output.string(from: date)
    }

    private func performRequest<T: Decodable>(url: URL) async throws -> T {
        var request = URLRequest(url: url)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("application/geo+json", forHTTPHeaderField: "Accept")

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw NWSClientError.invalidResponse
        }

        return try decoder.decode(T.self, from: data)
    }
}

private struct StationResponse: Decodable {
    struct Geometry: Decodable {
        let coordinates: [Double]
    }

    struct Properties: Decodable {
        let name: String?
    }

    let geometry: Geometry
    let properties: Properties
}

private struct ForecastURLResponse: Decodable {
    struct Properties: Decodable {
        let forecast: String?
        let forecastHourly: String?

        var daily: String? { forecast }
        var hourly: String? { forecastHourly }
    }

    let properties: Properties
}

private struct AlertsResponse: Decodable {
    let features: [AlertFeature]
}

private struct AlertFeature: Decodable {
    let id: String?
    let properties: AlertProperties
}

private struct AlertProperties: Decodable {
    let apiIdentifier: String?
    let uri: String?
    let event: String?
    let headline: String?
    let description: String?
    let severity: String?
    let urgency: String?
    let certainty: String?
    let areaDescription: String?
    let updated: String?
    let expires: String?

    enum CodingKeys: String, CodingKey {
        case apiIdentifier = "@id"
        case uri
        case event
        case headline
        case description
        case severity
        case urgency
        case certainty
        case areaDescription = "areaDesc"
        case updated
        case expires
    }
}

private struct ForecastResponse: Decodable {
    struct Properties: Decodable {
        let periods: [ForecastPeriodDTO]
    }

    let properties: Properties
}

private struct ForecastPeriodDTO: Decodable {
    struct QuantitativeValue: Decodable {
        let value: Double?
    }

    let name: String
    let startTime: String
    let isDaytime: Bool
    let temperature: Int
    let temperatureUnit: String
    let windSpeed: String
    let windDirection: String
    let shortForecast: String
    let detailedForecast: String
    let probabilityOfPrecipitation: QuantitativeValue?
}
