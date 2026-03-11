import SwiftUI

enum BrandPalette {
    static let skyTop = Color(red: 0.92, green: 0.96, blue: 0.99)
    static let skyBottom = Color(red: 0.84, green: 0.91, blue: 0.97)
    static let card = Color.white.opacity(0.86)
    static let cardBorder = Color(red: 0.72, green: 0.82, blue: 0.90)
    static let accent = Color(red: 0.12, green: 0.47, blue: 0.76)
    static let accentSoft = Color(red: 0.84, green: 0.91, blue: 0.97)
    static let ink = Color(red: 0.10, green: 0.19, blue: 0.30)
    static let mutedInk = Color(red: 0.22, green: 0.32, blue: 0.43)
}

struct BrandBackground: View {
    var body: some View {
        LinearGradient(
            colors: [BrandPalette.skyTop, BrandPalette.skyBottom],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .overlay(
            RadialGradient(
                colors: [Color.white.opacity(0.65), Color.clear],
                center: .topTrailing,
                startRadius: 10,
                endRadius: 420
            )
        )
        .ignoresSafeArea()
    }
}

struct BrandCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(BrandPalette.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(BrandPalette.cardBorder.opacity(0.9), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.06), radius: 18, x: 0, y: 10)
    }
}

extension View {
    func brandCard() -> some View {
        modifier(BrandCardModifier())
    }
}
