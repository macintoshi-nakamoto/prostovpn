import SwiftUI

struct ScaleButtonStyle: ButtonStyle {
    var scale: CGFloat = 0.96

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .animation(Theme.spring(0.25), value: configuration.isPressed)
    }
}

struct GlassCircleButton<Content: View>: View {
    var size: CGFloat = 46
    let action: () -> Void
    @ViewBuilder var content: () -> Content

    var body: some View {
        if #available(iOS 26.0, *) {
            Button(action: action) {
                content()
                    .frame(width: size, height: size)
                    .clipShape(Circle())
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
        } else {
            legacyButton
        }
    }

    private var legacyButton: some View {
        Button(action: action) {
            content()
                .frame(width: size, height: size)
                .background {
                    ZStack {
                        Circle().fill(.ultraThinMaterial)
                        Circle().fill(
                            LinearGradient(
                                colors: [Color.white.opacity(0.12), Color.white.opacity(0.04)],
                                startPoint: .top, endPoint: .bottom
                            )
                        )
                    }
                }
                .clipShape(Circle())
                .overlay {
                    Circle().strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
                }
                .overlay {
                    Circle()
                        .strokeBorder(
                            LinearGradient(
                                colors: [Color.white.opacity(0.22), Color.white.opacity(0.02)],
                                startPoint: .top, endPoint: .bottom
                            ),
                            lineWidth: 1
                        )
                }
                .shadow(color: .black.opacity(0.35), radius: 12, y: 8)
                .contentShape(Circle())
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.92))
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 16
    var shadowOpacity: CGFloat = 0.3

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(Theme.primaryGradient)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(0.25), .clear],
                            startPoint: .top, endPoint: .center
                        ),
                        lineWidth: 1
                    )
            }
            .shadow(color: Theme.accent.opacity(shadowOpacity), radius: 12, y: 8)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.spring(0.2), value: configuration.isPressed)
    }
}

struct OrangeToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            Capsule()
                .fill(
                    configuration.isOn
                        ? AnyShapeStyle(Theme.accentGradient)
                        : AnyShapeStyle(Color.white.opacity(0.12))
                )
                .frame(width: 48, height: 29)
                .overlay(alignment: .leading) {
                    Circle()
                        .fill(Color.white)
                        .frame(width: 24, height: 24)
                        .shadow(color: .black.opacity(0.35), radius: 3, y: 2)
                        .offset(x: configuration.isOn ? 21.5 : 2.5)
                }
                .animation(Theme.spring(0.25), value: configuration.isOn)
        }
        .buttonStyle(.plain)
        .accessibilityRepresentation {
            Toggle(isOn: configuration.$isOn) { configuration.label }
        }
    }
}

struct CardGroup: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(6)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(alignment: .top) {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(0.06), .clear],
                            startPoint: .top, endPoint: .center
                        ),
                        lineWidth: 1
                    )
            }
    }
}

extension View {
    func cardGroup() -> some View {
        modifier(CardGroup())
    }
}

struct CardDivider: View {
    var body: some View {
        Rectangle()
            .fill(Theme.divider)
            .frame(height: 1)
            .padding(.horizontal, 10)
    }
}

struct FlagChip: View {
    let flag: String
    var size: CGFloat = 40

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(Theme.accentTint12)
            .frame(width: size, height: size)
            .overlay {
                Text(flag)
                    .font(.system(size: size * 0.5))
            }
    }
}

struct ProtocolBadge: View {
    var body: some View {
        Text("AWG2")
            .font(.manrope(11, .bold))
            .kerning(0.5)
            .foregroundColor(Theme.accentSoft)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Theme.accentTint12)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

struct FadeUp: ViewModifier {
    let delay: Double
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 16)
            .onAppear {
                withAnimation(.easeOut(duration: 0.55).delay(delay)) {
                    shown = true
                }
            }
    }
}

extension View {
    func fadeUp(delay: Double = 0) -> some View {
        modifier(FadeUp(delay: delay))
    }
}

extension View {
    @ViewBuilder
    func softScrollEdge() -> some View {
        if #available(iOS 26.0, *) {
            scrollEdgeEffectStyle(.soft, for: .top)
        } else {
            self
        }
    }

    @ViewBuilder
    func glassCardButton(cornerRadius: CGFloat = 26) -> some View {
        if #available(iOS 26.0, *) {
            buttonStyle(.plain)
                .glassEffect(.regular.interactive(), in: .rect(cornerRadius: cornerRadius))
        } else {
            buttonStyle(GlassCardButtonStyle(cornerRadius: cornerRadius))
        }
    }

    @ViewBuilder
    func warmSheetBackground() -> some View {
        if #available(iOS 26.0, *) {
            self
        } else {
            presentationBackground(Theme.sheetGradient)
        }
    }
}

struct GlassCardButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 26

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.1), lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.spring(0.25), value: configuration.isPressed)
    }
}

enum Haptics {
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func tap() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }
}
