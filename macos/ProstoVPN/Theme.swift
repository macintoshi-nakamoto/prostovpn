import SwiftUI
import AppKit

/// Палитра и типографика Prosto VPN — те же значения, что в приложениях для
/// iOS и Android: продукт должен узнаваться на любой платформе.
enum Theme {
    static let bgTop = Color(hex: 0x1A110B)
    static let bgBottom = Color(hex: 0x120C08)
    static let sheetTop = Color(hex: 0x241710)
    static let sheetBottom = Color(hex: 0x170F0A)

    static let accent = Color(hex: 0xFF5000)
    static let accentWarm = Color(hex: 0xFF711F)
    static let accentDeep = Color(hex: 0xFF4000)
    static let link = Color(hex: 0xFF6A1F)
    static let accentSoft = Color(hex: 0xFF8A50)
    static let accentHover = Color(hex: 0xFFB184)

    static let text = Color(hex: 0xEEF2FF)
    static let danger = Color(hex: 0xFF6B5A)
    static let success = Color(hex: 0x2EC27E)

    static var textSecondary: Color { text.opacity(0.45) }
    static var textMuted: Color { text.opacity(0.4) }
    static var textTertiary: Color { text.opacity(0.35) }
    static var textFaint: Color { text.opacity(0.28) }
    static var glyphOff: Color { text.opacity(0.55) }

    static var background: LinearGradient {
        LinearGradient(colors: [bgTop, bgBottom], startPoint: .top, endPoint: .bottom)
    }

    static var accentGradient: LinearGradient {
        LinearGradient(colors: [accent, accentDeep], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    static var primaryGradient: LinearGradient {
        LinearGradient(colors: [accentWarm, accentDeep], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    static var sheetGradient: LinearGradient {
        LinearGradient(colors: [sheetTop, sheetBottom], startPoint: .top, endPoint: .bottom)
    }

    static var card: Color { Color.white.opacity(0.045) }
    static var rowActive: Color { Color.white.opacity(0.05) }
    static var divider: Color { Color.white.opacity(0.06) }
    static var accentTint10: Color { accent.opacity(0.10) }
    static var accentTint12: Color { accent.opacity(0.12) }
    static var accentTint14: Color { accent.opacity(0.14) }

    static func spring(_ duration: Double = 0.25) -> Animation {
        .timingCurve(0.3, 0.9, 0.3, 1, duration: duration)
    }
}

enum Manrope: String {
    case regular = "Manrope-Regular"
    case medium = "Manrope-Medium"
    case semibold = "Manrope-SemiBold"
    case bold = "Manrope-Bold"
    case extraBold = "Manrope-ExtraBold"

    var systemWeight: Font.Weight {
        switch self {
        case .regular: return .regular
        case .medium: return .medium
        case .semibold: return .semibold
        case .bold: return .bold
        case .extraBold: return .heavy
        }
    }

    /// Шрифт лежит в бандле, но подстраховка нужна: без неё сборка без
    /// ресурсов молча теряет всю типографику.
    static let isAvailable: Bool = NSFont(name: Manrope.bold.rawValue, size: 12) != nil
}

extension Font {
    static func manrope(_ size: CGFloat, _ weight: Manrope) -> Font {
        Manrope.isAvailable
            ? .custom(weight.rawValue, size: size)
            : .system(size: size, weight: weight.systemWeight)
    }
}

extension View {
    func manrope(_ size: CGFloat, _ weight: Manrope) -> some View {
        font(.manrope(size, weight))
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

func flagEmoji(countryCode: String) -> String {
    countryCode.uppercased().unicodeScalars.compactMap {
        UnicodeScalar(127397 + $0.value).map(String.init)
    }.joined()
}

struct LogoImage: View {
    var body: some View {
        Image("logo")
            .resizable()
            .scaledToFit()
    }
}
