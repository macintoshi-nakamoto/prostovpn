import SwiftUI

/// Шторка выбора сервера.
///
/// Не отдельное окно и не popover: она выезжает снизу внутри того же
/// экрана и вырастает прямо из карточки сервера — то же стекло меняет
/// форму, а не появляется рядом. Поэтому понятно, что это раскрытая
/// карточка, а не новое место.
struct ServerCurtain: View {
    @EnvironmentObject private var state: AppState
    @Binding var isPresented: Bool
    let namespace: Namespace.ID

    @State private var drag: CGFloat = 0
    @GestureState private var dragging = false

    private var t: L10n { state.t }

    /// За сколько пикселей вниз шторка считается закрытой.
    private let dismissDistance: CGFloat = 90

    private let rowHeight: CGFloat = 54

    /// Список ровно по числу серверов, но не выше половины окна.
    private var listHeight: CGFloat {
        min(CGFloat(state.servers.count) * rowHeight + 14, 250)
    }

    var body: some View {
        VStack(spacing: 0) {
            // Тянется только шапка. Если повесить жест на всю шторку, он
            // начнёт спорить с прокруткой списка, и длинный список станет
            // невозможно листать.
            VStack(spacing: 0) {
                grabber

                HStack {
                    Text(t.chooseServer)
                        .manrope(11, .bold)
                        .kerning(1.1)
                        .foregroundColor(Theme.textTertiary)
                    Spacer()
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 8)
            }
            .contentShape(Rectangle())
            .gesture(dragGesture)

            ScrollView {
                VStack(spacing: 2) {
                    ForEach(state.servers) { server in
                        row(server)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 14)
            }
            // Высота по содержимому, а не «сколько дадут»: ScrollView иначе
            // растягивается во всё окно, и под одним сервером остаётся
            // ладонь пустого стекла.
            .frame(height: listHeight)
        }
        .frame(maxWidth: .infinity)
        .glassCard(cornerRadius: 26, interactive: false)
        .glassID(HomeGlass.servers, in: namespace)
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
        .offset(y: max(0, drag) + rubberBand(drag))
    }

    // MARK: - Ручка

    private var grabber: some View {
        Capsule()
            .fill(Color.white.opacity(dragging ? 0.34 : 0.18))
            .frame(width: 38, height: 5)
            .padding(.top, 10)
            .padding(.bottom, 12)
            .frame(maxWidth: .infinity)
            // Тянуть можно за всю верхнюю полосу, а не за пять пикселей
            // самой ручки: попасть в неё курсором иначе слишком тонко.
            .contentShape(Rectangle())
            .animation(Theme.spring(0.2), value: dragging)
    }

    // MARK: - Перетаскивание

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 2)
            .updating($dragging) { _, isDragging, _ in isDragging = true }
            .onChanged { value in
                drag = value.translation.height
            }
            .onEnded { value in
                // Резкий бросок вниз закрывает шторку раньше, чем палец
                // дошёл до порога: ждать полного пути там, где намерение
                // уже понятно, ощущается как залипание.
                let thrown = value.predictedEndTranslation.height > dismissDistance * 2
                let dragged = value.translation.height > dismissDistance

                if thrown || dragged {
                    close()
                } else {
                    withAnimation(.spring(response: 0.34, dampingFraction: 0.78)) {
                        drag = 0
                    }
                }
            }
    }

    /// Сопротивление при движении вверх: шторка выше своего места не едет,
    /// но и не упирается в стену намертво.
    private func rubberBand(_ offset: CGFloat) -> CGFloat {
        offset < 0 ? -pow(-offset, 0.62) * 1.6 : 0
    }

    private func close() {
        withAnimation(.spring(response: 0.36, dampingFraction: 0.84)) {
            isPresented = false
        }
        drag = 0
    }

    // MARK: - Строки

    private func row(_ server: PanelServer) -> some View {
        let selected = server.id == state.currentServer?.id

        return Button {
            select(server, wasSelected: selected)
        } label: {
            HStack(spacing: 11) {
                FlagChip(flag: server.flag, size: 34)

                VStack(alignment: .leading, spacing: 1) {
                    Text(server.name(lang: state.lang))
                        .manrope(14, .semibold)
                        .foregroundColor(Theme.text)
                        .lineLimit(1)
                    Text(server.city(lang: state.lang) ?? server.host)
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textMuted)
                        .lineLimit(1)
                }

                Spacer(minLength: 6)

                if selected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundColor(Theme.accent)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Theme.accentTint10 : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(HoverRowStyle())
        .animation(Theme.spring(0.2), value: selected)
    }

    private func select(_ server: PanelServer, wasSelected: Bool) {
        guard !wasSelected else {
            close()
            return
        }
        let wasOn = state.phase == .on
        state.selectedServerID = server.id
        close()
        // Смена сервера при поднятом туннеле — это переподключение. Делаем
        // его сразу: оставлять человека подключённым к прежнему серверу,
        // показывая выбранным другой, нельзя.
        if wasOn {
            Task {
                await state.disconnect()
                await state.connect()
            }
        }
    }
}

/// Метки стеклянных элементов главного экрана. Одна на карточку и шторку —
/// именно по ней система перетекает из одной формы в другую.
enum HomeGlass: Hashable, Sendable {
    case servers
}

/// Подсветка строки под курсором — на маке это основной способ показать,
/// что список кликабельный.
struct HoverRowStyle: ButtonStyle {
    @State private var hovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .fill(Color.white.opacity(hovering ? 0.05 : 0))
            )
            .opacity(configuration.isPressed ? 0.75 : 1)
            .onHover { hovering = $0 }
            .animation(.easeOut(duration: 0.12), value: hovering)
    }
}
