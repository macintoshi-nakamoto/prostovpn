import SwiftUI
import UniformTypeIdentifiers

struct SplitTunnelView: View {
    @EnvironmentObject private var state: AppState
    @Binding var route: Route

    @State private var importError: String?

    private var t: L10n { state.t }
    private var files: TunnelFiles { state.tunnelFiles }

    var body: some View {
        VStack(spacing: 0) {
            ScreenHeader(title: t.fileTitle) { route = .settings }

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(t.fileDesc)
                        .manrope(12, .medium)
                        .foregroundColor(Theme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)

                    VStack(spacing: 0) {
                        ForEach(Array(files.files.enumerated()), id: \.element.id) { index, file in
                            if index > 0 { CardDivider() }
                            row(file)
                        }
                    }
                    .cardGroup()

                    Button(action: pickFile) {
                        HStack(spacing: 8) {
                            Image(systemName: "plus")
                                .font(.system(size: 12, weight: .bold))
                            Text(t.addFile)
                                .manrope(14, .semibold)
                        }
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 44)
                    }
                    .buttonStyle(PrimaryButtonStyle())

                    if let importError {
                        Text(importError)
                            .manrope(12, .medium)
                            .foregroundColor(Theme.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Text(t.holdHint)
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textFaint)
                        .padding(.horizontal, 4)
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 20)
            }
        }
        .animation(Theme.spring(0.25), value: files.files)
        .animation(Theme.spring(0.2), value: importError)
    }

    private func row(_ file: TunnelFile) -> some View {
        let selected = file.id == files.activeID

        return Button {
            state.selectTunnelFile(file)
        } label: {
            HStack(spacing: 11) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 15))
                    .foregroundColor(selected ? Theme.accent : Theme.textFaint)
                    .frame(width: 22)

                VStack(alignment: .leading, spacing: 1) {
                    Text(file.name)
                        .manrope(14, .semibold)
                        .foregroundColor(Theme.text)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text(subtitle(for: file))
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textMuted)
                }

                Spacer(minLength: 6)

                if !file.isDefault {
                    Button {
                        state.removeTunnelFile(file)
                    } label: {
                        Image(systemName: "trash")
                            .font(.system(size: 12))
                            .foregroundColor(Theme.danger.opacity(0.85))
                            .frame(width: 26, height: 26)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help(t.del)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(HoverRowStyle())
        .contextMenu {
            if !file.isDefault {
                Button(t.del, role: .destructive) { state.removeTunnelFile(file) }
            }
        }
    }

    private func subtitle(for file: TunnelFile) -> String {
        let count = "\(file.count) \(t.entries)"
        return file.isDefault ? "\(t.defaultMeta) · \(count)" : count
    }

    private func pickFile() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.json, .plainText, .text]
        panel.prompt = t.chooseFile

        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try state.addTunnelFile(from: url)
            importError = nil
        } catch {
            importError = "\(t.importError): \(error.localizedDescription)"
        }
    }
}
