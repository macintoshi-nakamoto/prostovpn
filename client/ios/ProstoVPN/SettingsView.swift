import SwiftUI
import UniformTypeIdentifiers

struct SettingsView: View {
    @EnvironmentObject private var state: AppState

    @AppStorage("prosto.split") private var splitTunneling = true
    @AppStorage("prosto.killSwitch") private var killSwitch = true
    @AppStorage("prosto.autostart") private var autoStart = false
    @AppStorage("prosto.autoconnect") private var autoConnect = false
    @AppStorage("prosto.logging") private var logging = true

    @State private var showLogoutConfirm = false
    @State private var showFileSheet = false

    private var t: L10n { state.t }

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()

            VStack(alignment: .leading, spacing: 0) {
                Text(t.settings)
                    .font(.manrope(30, .extraBold))
                    .foregroundColor(Theme.text)
                    .padding(.leading, 2)
                    .padding(.top, 6)
                    .padding(.bottom, 22)

                ScrollView(showsIndicators: false) {
                    VStack(spacing: 14) {
                        togglesCard
                        languageCard
                    }
                }
                .softScrollEdge()

                Spacer(minLength: 14)

                logoutButton
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 16)
        }
        .navigationBarTitleDisplayMode(.inline)
        .alert(t.logoutConfirmTitle, isPresented: $showLogoutConfirm) {
            Button(t.no, role: .cancel) {}
            Button(t.yes, role: .destructive) {
                state.logout()
            }
        } message: {
            Text(t.logoutConfirmMessage)
        }
        .sheet(isPresented: $showFileSheet) {
            TunnelFileSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .warmSheetBackground()
        }
    }

    private var togglesCard: some View {
        VStack(spacing: 0) {
            toggleRow(t.split, t.splitDesc, $splitTunneling)

            if splitTunneling {
                addFileButton
                    .padding(.horizontal, 8)
                    .padding(.top, 2)
                    .padding(.bottom, 10)
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .top)))
            }

            CardDivider()
            toggleRow(t.kill, t.killDesc, $killSwitch)
            CardDivider()
            toggleRow(t.autostart, t.autostartDesc, $autoStart)
            CardDivider()
            toggleRow(t.autoconnect, t.autoconnectDesc, $autoConnect)
            CardDivider()
            toggleRow(t.logging, t.loggingDesc, $logging)
        }
        .cardGroup()
        .animation(Theme.spring(0.3), value: splitTunneling)
    }

    private func toggleRow(_ title: String, _ subtitle: String, _ value: Binding<Bool>) -> some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.manrope(15, .bold))
                    .foregroundColor(Theme.text)
                Text(subtitle)
                    .font(.manrope(12.5, .medium))
                    .foregroundColor(Theme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()

            if #available(iOS 26.0, *) {
                Toggle("", isOn: value)
                    .labelsHidden()
                    .tint(Theme.accent)
            } else {
                Toggle("", isOn: value)
                    .labelsHidden()
                    .toggleStyle(OrangeToggleStyle())
            }
        }
        .padding(.vertical, 13)
        .padding(.horizontal, 10)
    }

    private var addFileButton: some View {
        Button {
            showFileSheet = true
        } label: {
            HStack(spacing: 9) {
                Image(systemName: "plus")
                    .font(.system(size: 16, weight: .bold))
                Text(t.addFile)
                    .font(.manrope(14.5, .bold))
            }
            .foregroundColor(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 46)
        }
        .buttonStyle(PrimaryButtonStyle(cornerRadius: 15))
    }

    private var languageCard: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(t.language)
                    .font(.manrope(15, .bold))
                    .foregroundColor(Theme.text)
                Text(t.langName)
                    .font(.manrope(12.5, .medium))
                    .foregroundColor(Theme.textMuted)
            }

            Spacer()

            Picker(t.language, selection: langBinding) {
                Text("RU").tag("ru")
                Text("EN").tag("en")
            }
            .pickerStyle(.segmented)
            .frame(width: 128)
        }
        .padding(.vertical, 13)
        .padding(.horizontal, 10)
        .cardGroup()
    }

    private var langBinding: Binding<String> {
        Binding(
            get: { state.lang },
            set: { newValue in
                withAnimation(.easeOut(duration: 0.2)) { state.lang = newValue }
            }
        )
    }

    private var logoutButton: some View {
        Button {
            showLogoutConfirm = true
        } label: {
            Text(t.logout)
                .font(.manrope(15, .bold))
                .foregroundColor(Theme.link)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background(Theme.accentTint08)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.98))
    }
}

private struct TunnelFileSheet: View {
    @EnvironmentObject private var state: AppState

    @State private var showImporter = false
    @State private var showImportError = false

    private var t: L10n { state.t }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 8) {
                ForEach(state.tunnelFiles) { file in
                    fileRow(file)
                }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 10)
        }
        .softScrollEdge()
        .safeAreaInset(edge: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text(t.fileTitle)
                    .font(.manrope(20, .extraBold))
                    .foregroundColor(Theme.text)

                Text(t.fileDesc)
                    .font(.manrope(13, .medium))
                    .foregroundColor(Theme.textSecondary)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 22)
            .padding(.top, 24)
            .padding(.bottom, 6)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 14) {
                Text(t.holdHint)
                    .font(.manrope(11.5, .semibold))
                    .foregroundColor(Theme.text.opacity(0.3))
                    .frame(maxWidth: .infinity)

                Button {
                    showImporter = true
                } label: {
                    HStack(spacing: 9) {
                        Image(systemName: "square.and.arrow.up")
                            .font(.system(size: 16, weight: .semibold))
                        Text(t.chooseFile)
                            .font(.manrope(15, .bold))
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(.horizontal, 22)
            .padding(.top, 6)
            .padding(.bottom, 16)
        }
        .alert(t.importError, isPresented: $showImportError) {
            Button("OK", role: .cancel) {}
        }
        .fileImporter(
            isPresented: $showImporter,
            allowedContentTypes: [.json, .plainText, .text],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                do {
                    try state.addTunnelFile(from: url)
                } catch {
                    showImportError = true
                }
            }
        }
    }

    @ViewBuilder
    private func fileRow(_ file: TunnelFile) -> some View {
        if file.isDefault {
            fileRowContent(file)
        } else {
            fileRowContent(file)
                .contextMenu {
                    Button(role: .destructive) {
                        withAnimation(Theme.spring(0.3)) {
                            state.deleteTunnelFile(file)
                        }
                    } label: {
                        Label(t.del, systemImage: "trash")
                    }
                } preview: {
                    filePreview(file)
                }
        }
    }

    private func fileRowContent(_ file: TunnelFile) -> some View {
        let isActive = file.id == state.activeTunnelFileID

        return HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Theme.accentTint14)
                .frame(width: 36, height: 36)
                .overlay {
                    Image(systemName: "doc")
                        .font(.system(size: 16, weight: .medium))
                        .foregroundColor(Theme.accentSoft)
                }

            VStack(alignment: .leading, spacing: 1) {
                Text(file.name)
                    .font(.manrope(14, .bold))
                    .foregroundColor(Theme.text)
                    .lineLimit(1)
                    .truncationMode(.middle)

                Text(meta(for: file))
                    .font(.manrope(12, .semibold))
                    .foregroundColor(Theme.accentSoft)
            }

            Spacer()

            if isActive {
                Image(systemName: "checkmark")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(Theme.link)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(isActive ? Theme.accentTint10 : Color.white.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .onTapGesture {
            withAnimation(Theme.spring(0.3)) {
                state.selectTunnelFile(file)
            }
        }
    }

    private func filePreview(_ file: TunnelFile) -> some View {
        HStack(spacing: 16) {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Theme.accentTint14)
                .frame(width: 54, height: 54)
                .overlay {
                    Image(systemName: "doc.text")
                        .font(.system(size: 24, weight: .medium))
                        .foregroundColor(Theme.accentSoft)
                }

            VStack(alignment: .leading, spacing: 3) {
                Text(file.name)
                    .font(.manrope(16, .bold))
                    .foregroundColor(Theme.text)
                    .lineLimit(2)
                    .truncationMode(.middle)

                Text(meta(for: file))
                    .font(.manrope(13, .semibold))
                    .foregroundColor(Theme.accentSoft)
            }

            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(width: 320)
        .background(Theme.sheetGradient)
    }

    private func meta(for file: TunnelFile) -> String {
        let entries = "\(file.count) \(t.entries)"
        return file.isDefault ? "\(t.defaultMeta) · \(entries)" : entries
    }
}
