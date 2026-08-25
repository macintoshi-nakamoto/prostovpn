import SwiftUI

struct PowerButton: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var hovering = false

    private var isOn: Bool { state.phase == .on }
    private var isBusy: Bool { state.phase == .connecting || state.phase == .disconnecting }

    private let diameter: CGFloat = 156

    var body: some View {
        ZStack {
            RadialGradient(
                colors: [Theme.accent.opacity(0.24), .clear],
                center: .center, startRadius: 34, endRadius: 145
            )
            .frame(width: 290, height: 290)
            .opacity(isOn ? 1 : 0)
            .animation(.easeInOut(duration: 0.45), value: isOn)
            .allowsHitTesting(false)

            button
                .shadow(
                    color: isOn ? Theme.accent.opacity(0.28) : .black.opacity(0.35),
                    radius: isOn ? 22 : 18,
                    y: isOn ? 0 : 10
                )
                .help(isOn ? state.t.connected : state.t.tapToConnect)
                .accessibilityLabel(isOn ? state.t.connected : state.t.tapToConnect)

            if isBusy {
                SpinnerRing(paused: reduceMotion)
                    .frame(width: diameter, height: diameter)
                    .allowsHitTesting(false)
            }
        }
        .frame(width: 180, height: 180)
    }

    @ViewBuilder
    private var button: some View {
        if #available(macOS 26.0, *) {
            Button(action: state.toggle) {
                label
            }
            .buttonStyle(.plain)

            .glassCircle(tint: isOn ? Theme.accent.opacity(0.55) : nil)
            .animation(Theme.spring(0.35), value: isOn)
        } else {
            Button(action: state.toggle) {
                label
            }
            .buttonStyle(PressableButtonStyle(scale: 0.97))
            .glassCircle(tint: isOn ? Theme.accent : nil)
            .scaleEffect(hovering ? 1.02 : 1)
            .animation(Theme.spring(0.2), value: hovering)
            .onHover { hovering = $0 }
        }
    }

    private var label: some View {
        ZStack {
            powerGlyph
            ring
        }
        .frame(width: diameter, height: diameter)
        .contentShape(Circle())
    }

    private var ring: some View {
        Circle()
            .strokeBorder(isOn ? Color.white.opacity(0.45) : Color.white.opacity(0.10), lineWidth: 1.5)
            .animation(.easeInOut(duration: 0.35), value: isOn)
            .allowsHitTesting(false)
    }

    private var powerGlyph: some View {
        Image(systemName: "power")
            .font(.system(size: 50, weight: .semibold))
            .foregroundColor(isOn || isBusy ? .white : Theme.glyphOff)
            .animation(.easeInOut(duration: 0.35), value: state.phase)
    }
}

private struct SpinnerRing: View {
    var paused: Bool

    var body: some View {
        TimelineView(.animation(paused: paused)) { context in
            let phase = context.date.timeIntervalSinceReferenceDate
                .truncatingRemainder(dividingBy: 1.1) / 1.1

            Circle()
                .stroke(
                    AngularGradient(
                        gradient: Gradient(stops: [
                            .init(color: .clear, location: 0),
                            .init(color: .clear, location: 0.1),
                            .init(color: Theme.accent.opacity(0.15), location: 0.55),
                            .init(color: Theme.accent, location: 1),
                        ]),
                        center: .center
                    ),
                    style: StrokeStyle(lineWidth: 2.5, lineCap: .round)
                )
                .rotationEffect(.degrees(paused ? 0 : phase * 360))
        }
    }
}
