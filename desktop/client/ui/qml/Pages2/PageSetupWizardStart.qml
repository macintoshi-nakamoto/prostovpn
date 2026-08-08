import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects

import PageEnum 1.0
import Style 1.0

import "./"
import "../Controls2"
import "../Config"
import "../Controls2/TextTypes"
import "../Components"

PageType {
    id: root
    enableTimer: (SettingsController.isOnTv()) ? false : true

    property string errorText: ""

    Connections {
        target: ImportController

        function onImportFinished() {
            PageController.showBusyIndicator(false)
            PageController.goToPageHome()
        }

        function onImportErrorOccurred(error, goToPageHome) {
            PageController.showBusyIndicator(false)
            root.errorText = qsTr("Не удалось применить ключ. Проверьте ключ и попробуйте ещё раз")
        }
    }

    function submitLogin() {
        var credentials = loginField.text.trim()

        if (credentials === "") {
            root.errorText = qsTr("Введите логин")
            return
        }

        if (credentials.startsWith("vpn://")) {
            if (ImportController.extractConfigFromData(credentials)) {
                root.errorText = ""
                PageController.showBusyIndicator(true)
                ImportController.importConfig()
            } else {
                root.errorText = qsTr("Не удалось применить ключ. Проверьте ключ и попробуйте ещё раз")
            }
            return
        }

        if (passwordField.text.length < 4) {
            root.errorText = qsTr("Пароль слишком короткий")
            return
        }

        root.errorText = qsTr("Неверный логин или пароль")
    }

    RadialGradient {
        x: -80
        y: -120
        width: 340
        height: 340
        horizontalRadius: width / 2
        verticalRadius: height / 2

        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.alpha(AmneziaStyle.color.vibrantRed, 0.2) }
            GradientStop { position: 0.7; color: AmneziaStyle.color.transparent }
        }
    }

    RadialGradient {
        x: parent.width - 200
        y: parent.height - 260
        width: 300
        height: 300
        horizontalRadius: width / 2
        verticalRadius: height / 2

        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(255 / 255, 120 / 255, 80 / 255, 0.14) }
            GradientStop { position: 0.7; color: AmneziaStyle.color.transparent }
        }
    }

    FlickableType {
        anchors.top: parent.top
        anchors.bottom: parent.bottom

        contentHeight: Math.max(content.implicitHeight, root.height)

        ColumnLayout {
            id: content

            anchors.horizontalCenter: parent.horizontalCenter
            width: 360
            height: root.height

            spacing: 0

            Item {
                Layout.fillHeight: true
            }

            Image {
                source: "qrc:/images/nexaBigLogo.png"
                fillMode: Image.PreserveAspectFit

                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 170
                Layout.preferredHeight: 114
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: -4

                font.family: "PT Root UI VF"
                font.pixelSize: 28
                font.weight: 800
                font.letterSpacing: 0.5

                color: AmneziaStyle.color.paleGray
                text: qsTr("Алиса VPN")
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 4

                font.family: "PT Root UI VF"
                font.pixelSize: 14
                font.weight: 500

                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.45)
                text: qsTr("Свободный и безопасный интернет")
            }

            Rectangle {
                id: formCard

                Layout.fillWidth: true
                Layout.topMargin: 34

                implicitHeight: formColumn.implicitHeight + 12
                radius: 20
                color: AmneziaStyle.color.barelyTranslucentWhite

                ColumnLayout {
                    id: formColumn

                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 6

                    spacing: 0

                    Rectangle {
                        id: loginRow

                        Layout.fillWidth: true

                        implicitHeight: 52
                        radius: 14
                        color: loginField.activeFocus ? Qt.alpha(AmneziaStyle.color.goldenApricot, 0.08) : AmneziaStyle.color.transparent
                        border.width: loginField.activeFocus ? 2 : 0
                        border.color: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.5)

                        Behavior on color {
                            PropertyAnimation { duration: 200 }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14

                            spacing: 12

                            Image {
                                Layout.preferredWidth: 20
                                Layout.preferredHeight: 20

                                source: "qrc:/images/controls/text-cursor.svg"

                                layer {
                                    enabled: true
                                    effect: ColorOverlay {
                                        color: Qt.alpha(AmneziaStyle.color.paleGray, 0.4)
                                    }
                                }
                            }

                            TextField {
                                id: loginField

                                Layout.fillWidth: true

                                font.family: "PT Root UI VF"
                                font.pixelSize: 16
                                font.weight: 500

                                color: AmneziaStyle.color.paleGray
                                placeholderText: qsTr("Логин")
                                placeholderTextColor: Qt.alpha(AmneziaStyle.color.paleGray, 0.32)

                                background: Item {}

                                onTextChanged: root.errorText = ""
                                onAccepted: passwordField.forceActiveFocus()
                            }
                        }
                    }

                    DividerType {
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    Rectangle {
                        id: passwordRow

                        Layout.fillWidth: true

                        implicitHeight: 52
                        radius: 14
                        color: passwordField.activeFocus ? Qt.alpha(AmneziaStyle.color.goldenApricot, 0.08) : AmneziaStyle.color.transparent
                        border.width: passwordField.activeFocus ? 2 : 0
                        border.color: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.5)

                        Behavior on color {
                            PropertyAnimation { duration: 200 }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14

                            spacing: 12

                            Image {
                                Layout.preferredWidth: 20
                                Layout.preferredHeight: 20

                                source: "qrc:/images/controls/eye-off.svg"
                                visible: false
                            }

                            Image {
                                id: lockIcon

                                Layout.preferredWidth: 20
                                Layout.preferredHeight: 20

                                source: "qrc:/images/controls/file-check-2.svg"

                                layer {
                                    enabled: true
                                    effect: ColorOverlay {
                                        color: Qt.alpha(AmneziaStyle.color.paleGray, 0.4)
                                    }
                                }
                            }

                            TextField {
                                id: passwordField

                                property bool hidePassword: true

                                Layout.fillWidth: true

                                font.family: "PT Root UI VF"
                                font.pixelSize: 16
                                font.weight: 500

                                echoMode: hidePassword ? TextInput.Password : TextInput.Normal

                                color: AmneziaStyle.color.paleGray
                                placeholderText: qsTr("Пароль")
                                placeholderTextColor: Qt.alpha(AmneziaStyle.color.paleGray, 0.32)

                                background: Item {}

                                onTextChanged: root.errorText = ""
                                onAccepted: root.submitLogin()
                            }

                            ImageButtonType {
                                image: passwordField.hidePassword ? "qrc:/images/controls/eye-off.svg" : "qrc:/images/controls/eye.svg"
                                imageColor: Qt.alpha(AmneziaStyle.color.paleGray, 0.4)

                                icon.width: 22
                                icon.height: 22
                                backgroundRadius: 11

                                onClicked: {
                                    passwordField.hidePassword = !passwordField.hidePassword
                                }
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Layout.leftMargin: 8
                Layout.rightMargin: 8

                visible: root.errorText !== ""

                font.family: "PT Root UI VF"
                font.pixelSize: 13
                font.weight: 600

                wrapMode: Text.WordWrap
                color: AmneziaStyle.color.softViolet
                text: root.errorText
            }

            // CTA
            BasicButtonType {
                id: startButton

                Layout.fillWidth: true
                Layout.topMargin: 12

                implicitHeight: 56

                text: qsTr("Войти")

                clickedFunc: function() {
                    root.submitLogin()
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 24

                font.family: "PT Root UI VF"
                font.pixelSize: 12

                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.28)
                text: qsTr("Продолжая, вы принимаете условия сервиса")
            }

            Item {
                Layout.fillHeight: true
            }
        }
    }

    Timer {
        interval: 250
        running: SettingsController.isOnTv()
        repeat: true
        onTriggered: {
            startButton.forceActiveFocus()
            if (startButton.activeFocus) {
                running = false
            }
        }
    }

    onVisibleChanged: {
        if (visible && SettingsController.isOnTv()) {
            startButton.forceActiveFocus()
        }
    }
}
