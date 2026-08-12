import SwiftUI

struct PowerButton: View {
    @EnvironmentObject private var state: AppState

    @State private var popScale: CGFloat = 1

    private var isOn: Bool { state.phase == .on }
    private var isBusy: Bool { state.phase == .connecting }

    var body: some View {
        ZStack {
            RadialGradient(
                colors: [Theme.accent.opacity(0.25), .clear],
                center: .center, startRadius: 40, endRadius: 165
            )
            .frame(width: 330, height: 330)
            .opacity(isOn ? 1 : 0)
            .animation(.easeInOut(duration: 0.45), value: isOn)
            .allowsHitTesting(false)

            connectButton
                .shadow(
                    color: isOn ? Theme.accent.opacity(0.25) : .black.opacity(0.35),
                    radius: isOn ? 22 : 20,
                    y: isOn ? 0 : 12
                )
                .scaleEffect(popScale)

            if isBusy {
                SpinnerRing()
                    .frame(width: 176, height: 176)
                    .allowsHitTesting(false)
            }
        }
        .frame(width: 200, height: 200)
        .onChange(of: state.phase) { phase in
            if phase == .on {
                popIn()
            }
        }
    }

    @ViewBuilder
    private var connectButton: some View {
        if #available(iOS 26.0, *) {
            Button {
                Haptics.tap()
                state.toggleConnection()
            } label: {
                ZStack {
                    powerGlyph
                    ringStroke
                }
                .frame(width: 176, height: 176)
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
        } else {
            Button {
                Haptics.tap()
                state.toggleConnection()
            } label: {
                ZStack {
                    Circle()
                        .fill(.ultraThinMaterial)
                        .opacity(0.55)
                    Circle()
                        .fill(Color.white.opacity(0.05))

                    Circle()
                        .stroke(
                            LinearGradient(
                                colors: [Color.white.opacity(0.08), .clear],
                                startPoint: .top, endPoint: .center
                            ),
                            lineWidth: 1
                        )
                        .padding(1.5)

                    powerGlyph
                    ringStroke
                }
                .frame(width: 176, height: 176)
                .contentShape(Circle())
            }
            .buttonStyle(ScaleButtonStyle(scale: 0.96))
        }
    }

    private var ringStroke: some View {
        Circle()
            .strokeBorder(
                isOn ? Theme.accent.opacity(0.8) : Color.white.opacity(0.1),
                lineWidth: 1.5
            )
            .animation(.easeInOut(duration: 0.35), value: isOn)
            .allowsHitTesting(false)
    }

    private var powerGlyph: some View {
        Image(systemName: "power")
            .font(.system(size: 58, weight: .semibold))
            .foregroundColor(isOn || isBusy ? .white : Theme.glyphOff)
            .animation(.easeInOut(duration: 0.35), value: state.phase)
    }

    private func popIn() {
        popScale = 0.92
        withAnimation(.spring(response: 0.3, dampingFraction: 0.55)) {
            popScale = 1.03
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            withAnimation(.easeOut(duration: 0.18)) {
                popScale = 1
            }
        }
    }
}

private struct SpinnerRing: View {
    var body: some View {
        TimelineView(.animation) { context in
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
                .rotationEffect(.degrees(phase * 360))
        }
    }
}
