import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import PageEnum 1.0
import Style 1.0

import "./"
import "../Controls2"
import "../Config"
import "../Controls2/TextTypes"
import "../Components"

PageType {
    id: root

    BaseHeaderType {
        id: header

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 24 + PageController.safeAreaTopMargin
        anchors.leftMargin: 34
        anchors.rightMargin: 34

        headerText: qsTr("Настройки")
    }

    FlickableType {
        id: flickable

        anchors.top: header.bottom
        anchors.topMargin: 20
        anchors.bottom: parent.bottom

        contentHeight: content.height + 40

        ColumnLayout {
            id: content

            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 34
            anchors.rightMargin: 34

            spacing: 14

            Rectangle {
                Layout.fillWidth: true

                implicitHeight: togglesColumn.implicitHeight + 12
                radius: 20
                color: AmneziaStyle.color.barelyTranslucentWhite

                ColumnLayout {
                    id: togglesColumn

                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 6

                    spacing: 0

                    SwitcherType {
                        id: switcherKillSwitch

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Kill Switch")
                        descriptionText: qsTr("Блокировать интернет при обрыве VPN")

                        checked: SettingsController.isKillSwitchEnabled
                        onToggled: function() {
                            if (ConnectionController.isConnected) {
                                PageController.showNotificationMessage(qsTr("KillSwitch settings cannot be changed during an active connection"))
                                switcherKillSwitch.checked = SettingsController.isKillSwitchEnabled
                                return
                            }
                            SettingsController.isKillSwitchEnabled = checked
                        }
                    }

                    DividerType {
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    SwitcherType {
                        id: switcherAutoStart

                        visible: !GC.isMobile()

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Автозапуск")
                        descriptionText: qsTr("Запускать приложение при старте системы")

                        checked: SettingsController.autoStartEnabled
                        onToggled: function() {
                            if (checked !== SettingsController.autoStartEnabled) {
                                SettingsController.toggleAutoStart(checked)
                            }
                        }
                    }

                    DividerType {
                        visible: !GC.isMobile()
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    SwitcherType {
                        id: switcherAutoConnect

                        visible: !GC.isMobile()

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Автоподключение")
                        descriptionText: qsTr("Подключаться к VPN при запуске")

                        checked: SettingsController.isAutoConnectEnabled()
                        onToggled: function() {
                            if (checked !== SettingsController.isAutoConnectEnabled()) {
                                SettingsController.toggleAutoConnect(checked)
                            }
                        }
                    }

                    DividerType {
                        visible: !GC.isMobile() && !IsMacOsNeBuild
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    SwitcherType {
                        id: switcherStartMinimized

                        visible: !GC.isMobile()

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Запуск в фоне")
                        descriptionText: qsTr("Запускать приложение свёрнутым (работает вместе с автозапуском)")

                        enabled: SettingsController.autoStartEnabled
                        opacity: enabled ? 1.0 : 0.5

                        checked: SettingsController.autoStartEnabled && SettingsController.startMinimized
                        onToggled: function() {
                            if (checked !== SettingsController.startMinimized) {
                                SettingsController.toggleStartMinimized(checked)
                            }
                        }
                    }

                    DividerType {
                        visible: GC.isMobile()
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    SwitcherType {
                        id: switcherAllowScreenshots

                        visible: GC.isMobile()

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Разрешить скриншоты приложения")

                        checked: SettingsController.isScreenshotsEnabled()
                        onToggled: function() {
                            if (checked !== SettingsController.isScreenshotsEnabled()) {
                                SettingsController.toggleScreenshotsEnabled(checked)
                            }
                        }
                    }

                    DividerType {
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    LabelWithButtonType {
                        id: labelWithButtonLogging

                        Layout.fillWidth: true

                        text: qsTr("Логирование")
                        descriptionText: SettingsController.isLoggingEnabled ? qsTr("Включено") : qsTr("Выключено")
                        rightImageSource: "qrc:/images/controls/chevron-right.svg"

                        clickedFunction: function() {
                            PageController.goToPage(PageEnum.PageSettingsLogging)
                        }
                    }

                    SwitcherType {
                        id: switcherNewsNotificationEnabled

                        visible: ServersUiController.hasServersFromGatewayApi

                        Layout.fillWidth: true
                        Layout.margins: 12

                        text: qsTr("Уведомления о новостях")
                        descriptionText: qsTr("Показывать значок непрочитанных новостей")

                        checked: SettingsController.isNewsNotificationsEnabled()
                        onToggled: function() {
                            if (checked !== SettingsController.isNewsNotificationsEnabled()) {
                                SettingsController.toggleNewsNotificationsEnabled(checked)
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true

                implicitHeight: languageColumn.implicitHeight + 12
                radius: 20
                color: AmneziaStyle.color.barelyTranslucentWhite

                ColumnLayout {
                    id: languageColumn

                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 6

                    LabelWithButtonType {
                        id: labelWithButtonLanguage

                        Layout.fillWidth: true

                        text: qsTr("Язык")
                        descriptionText: LanguageUiController.currentLanguageName
                        rightImageSource: "qrc:/images/controls/chevron-right.svg"

                        clickedFunction: function() {
                            selectLanguageDrawer.openTriggered()
                        }
                    }
                }
            }

            BasicButtonType {
                id: resetButton

                Layout.fillWidth: true
                Layout.topMargin: 6

                implicitHeight: 48

                defaultColor: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.08)
                hoveredColor: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.14)
                pressedColor: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.2)
                textColor: AmneziaStyle.color.vibrantRed

                text: qsTr("Выйти из аккаунта")

                clickedFunc: function() {
                    var headerText = qsTr("Выйти из аккаунта?")
                    var descriptionText = qsTr("Настройки будут сброшены, для входа понадобится снова ввести ключ доступа.")
                    var yesButtonText = qsTr("Выйти")
                    var noButtonText = qsTr("Отмена")

                    var yesButtonFunction = function() {
                        if (ServersUiController.isDefaultServerCurrentlyProcessed() && ConnectionController.isConnected) {
                            PageController.showNotificationMessage(qsTr("Нельзя сбросить настройки при активном подключении"))
                        } else
                        {
                            SettingsController.clearSettings()
                            PageController.goToPageHome()
                        }
                    }
                    var noButtonFunction = function() {
                    }

                    showQuestionDrawer(headerText, descriptionText, yesButtonText, noButtonText, yesButtonFunction, noButtonFunction)
                }
            }
        }
    }

    SelectLanguageDrawer {
        id: selectLanguageDrawer

        width: root.width
        height: root.height
    }
}
