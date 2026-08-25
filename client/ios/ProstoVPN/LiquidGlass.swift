import SwiftUI

struct GlassCard<Content: View>: View {
    var cornerRadius: CGFloat = 22

    var interactive: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .background {
                GlassBackground(cornerRadius: cornerRadius, interactive: interactive)
            }
    }
}

struct GlassBackground: View {
    var cornerRadius: CGFloat = 22
    var interactive: Bool = false

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        if #available(iOS 26.0, *), interactive {
            shape.fill(.clear).glassEffect(.regular.interactive(), in: shape)
        } else if #available(iOS 26.0, *) {
            shape.fill(.clear).glassEffect(.regular, in: shape)
        } else {
            ZStack {
                shape.fill(.ultraThinMaterial)

                shape.fill(Color.white.opacity(0.045))

                shape.strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.14), Color.white.opacity(0.02)],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    lineWidth: 1
                )
            }

            .compositingGroup()
        }
    }
}

struct GlassReveal<Content: View>: View {
    var delay: Double = 0
    @ViewBuilder var content: () -> Content

    @State private var shown = false

    var body: some View {
        content()
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 14)
            .animation(.spring(response: 0.42, dampingFraction: 0.86).delay(delay), value: shown)
            .onAppear { shown = true }

            .transaction { transaction in
                if UIAccessibility.isReduceMotionEnabled {
                    transaction.animation = nil
                }
            }
    }
}

struct GlowPulse: View {
    var color: Color
    var isActive: Bool

    var body: some View {
        TimelineView(.animation(paused: !isActive)) { context in
            Canvas { ctx, size in
                guard isActive else { return }
                let t = context.date.timeIntervalSinceReferenceDate

                let wave = (sin(t * 2.0) + 1) / 2
                let radius = size.width * (0.42 + 0.05 * wave)
                let opacity = 0.18 + 0.12 * wave

                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let gradient = Gradient(colors: [color.opacity(opacity), .clear])
                ctx.fill(
                    Circle().path(in: CGRect(
                        x: center.x - radius, y: center.y - radius,
                        width: radius * 2, height: radius * 2
                    )),
                    with: .radialGradient(
                        gradient,
                        center: center,
                        startRadius: radius * 0.25,
                        endRadius: radius
                    )
                )
            }
        }
        .allowsHitTesting(false)

        .accessibilityHidden(true)
    }
}

struct ProgressRing: View {
    var color: Color
    var isActive: Bool
    var lineWidth: CGFloat = 2.5

    var body: some View {
        TimelineView(.animation(paused: !isActive)) { context in
            Canvas { ctx, size in
                guard isActive else { return }
                let angle = context.date.timeIntervalSinceReferenceDate
                    .truncatingRemainder(dividingBy: 1.1) / 1.1

                let inset = lineWidth / 2
                let rect = CGRect(origin: .zero, size: size).insetBy(dx: inset, dy: inset)
                let path = Circle().path(in: rect)

                ctx.stroke(
                    path,
                    with: .conicGradient(
                        Gradient(stops: [
                            .init(color: .clear, location: 0),
                            .init(color: color.opacity(0.15), location: 0.55),
                            .init(color: color, location: 1),
                        ]),
                        center: CGPoint(x: size.width / 2, y: size.height / 2),
                        angle: .degrees(angle * 360)
                    ),
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.97

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .animation(.spring(response: 0.22, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

extension View {
    func flattenLayer() -> some View {
        drawingGroup()
    }
}
