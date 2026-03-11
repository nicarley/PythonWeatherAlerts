import Foundation
import UserNotifications

enum NotificationAuthorizationState: String {
    case notDetermined
    case denied
    case authorized
}

actor NotificationService {
    private let center = UNUserNotificationCenter.current()

    func authorizationState() async -> NotificationAuthorizationState {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return .authorized
        case .denied:
            return .denied
        case .notDetermined:
            return .notDetermined
        @unknown default:
            return .notDetermined
        }
    }

    func requestAuthorization() async -> Bool {
        do {
            return try await center.requestAuthorization(options: [.alert, .sound, .badge])
        } catch {
            return false
        }
    }

    func sendNotification(for alert: WeatherAlert, locationName: String) async {
        let content = UNMutableNotificationContent()
        content.title = "\(locationName): \(alert.title)"
        content.body = alert.summary
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "\(locationName)-\(alert.id)",
            content: content,
            trigger: nil
        )

        try? await center.add(request)
    }
}
