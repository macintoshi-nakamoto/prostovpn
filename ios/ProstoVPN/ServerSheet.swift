import SwiftUI

struct CurrentServerCard: View {
    @EnvironmentObject private var state: AppState
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            ServerRow(server: state.currentServer) {
                Image(systemName: "chevron.up")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(Theme.textTertiary)
            }
            .padding(.vertical, 13)
            .padding(.horizontal, 16)
            .contentShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        }
        .glassCardButton(cornerRadius: 26)
    }
}

struct ServerListSheet: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.dismiss) private var dismiss

    private var t: L10n { state.t }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(state.displayServers().enumerated()), id: \.offset) { index, server in
                    row(server: server, index: index)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .softScrollEdge()
        .safeAreaInset(edge: .top, spacing: 0) {
            Text(t.chooseServer)
                .font(.manrope(13, .bold))
                .kerning(0.5)
                .foregroundColor(Theme.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 28)
                .padding(.top, 22)
                .padding(.bottom, 8)
        }
    }

    private func row(server: DisplayServer, index: Int) -> some View {
        let isActive = index == state.selectedServerIndex
        return Button {
            Haptics.selection()
            state.selectedServerIndex = index
            dismiss()
        } label: {
            ServerRow(server: server) {
                if isActive {
                    Image(systemName: "checkmark")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundColor(Theme.link)
                }
            }
            .padding(.vertical, 12)
            .padding(.horizontal, 8)
            .background(isActive ? Theme.accent.opacity(0.07) : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.98))
    }
}

struct ServerRow<Trailing: View>: View {
    let server: DisplayServer?
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 14) {
            FlagChip(flag: server?.flag ?? "🌐")

            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 8) {
                    Text(server?.name ?? "—")
                        .font(.manrope(15, .bold))
                        .foregroundColor(Theme.text)
                        .lineLimit(1)

                    ProtocolBadge()
                }

                Text(server?.sub ?? "")
                    .font(.manrope(12.5, .medium))
                    .foregroundColor(Theme.textMuted)
                    .lineLimit(1)
            }

            Spacer()

            trailing()
        }
    }
}
