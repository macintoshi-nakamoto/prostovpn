import WidgetKit
import SwiftUI
import ActivityKit

@main
struct ProstoVPNWidgets: WidgetBundle {
    var body: some Widget {
        ConnectionLiveActivity()
    }
}

private enum WidgetTheme {
    static let accent = Color(red: 1.0, green: 0.313, blue: 0.0)
    static let accentSoft = Color(red: 1.0, green: 0.541, blue: 0.313)
    static let bg = Color(red: 0.102, green: 0.066, blue: 0.043)
}

struct ConnectionLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: ConnectionAttributes.self) { context in
            LockScreenActivityView(context: context)
                .activityBackgroundTint(WidgetTheme.bg.opacity(0.85))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 8) {
                        powerBadge
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Prosto VPN")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundColor(.white)
                            Text(context.attributes.statusLabel)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundColor(WidgetTheme.accentSoft)
                        }
                    }
                    .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    timerText(context)
                        .font(.system(size: 22, weight: .bold))
                        .foregroundColor(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                        .frame(maxWidth: 92)
                        .padding(.trailing, 4)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack(spacing: 6) {
                        Text(context.attributes.serverFlag)
                            .font(.system(size: 13))
                        Text(context.attributes.serverName)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.white.opacity(0.75))
                    }
                    .padding(.top, 2)
                }
            } compactLeading: {
                Image(systemName: "power")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(WidgetTheme.accent)
            } compactTrailing: {
                timerText(context)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                    .frame(maxWidth: 46)
            } minimal: {
                Image(systemName: "power")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(WidgetTheme.accent)
            }
            .keylineTint(WidgetTheme.accent)
        }
    }

    private var powerBadge: some View {
        Circle()
            .fill(WidgetTheme.accent.opacity(0.18))
            .frame(width: 32, height: 32)
            .overlay {
                Image(systemName: "power")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(WidgetTheme.accent)
            }
    }

    private func timerText(_ context: ActivityViewContext<ConnectionAttributes>) -> Text {
        Text(
            timerInterval: context.state.startedAt...context.state.startedAt.addingTimeInterval(24 * 60 * 60),
            countsDown: false
        )
        .monospacedDigit()
    }
}

private struct LockScreenActivityView: View {
    let context: ActivityViewContext<ConnectionAttributes>

    var body: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(WidgetTheme.accent.opacity(0.18))
                .frame(width: 40, height: 40)
                .overlay {
                    Image(systemName: "power")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(WidgetTheme.accent)
                }

            VStack(alignment: .leading, spacing: 2) {
                Text(context.attributes.statusLabel)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundColor(.white)

                HStack(spacing: 5) {
                    Text(context.attributes.serverFlag)
                        .font(.system(size: 12))
                    Text(context.attributes.serverName)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white.opacity(0.6))
                }
            }

            Spacer()

            Text(
                timerInterval: context.state.startedAt...context.state.startedAt.addingTimeInterval(24 * 60 * 60),
                countsDown: false
            )
            .monospacedDigit()
            .font(.system(size: 24, weight: .bold))
            .foregroundColor(.white)
            .lineLimit(1)
            .minimumScaleFactor(0.6)
            .frame(maxWidth: 96)
        }
        .padding(16)
    }
}
