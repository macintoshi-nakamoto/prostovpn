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

    BaseHeaderType {
        id: header

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 24 + PageController.safeAreaTopMargin
        anchors.leftMargin: 34
        anchors.rightMargin: 34

        headerText: qsTr("Поддержка")
    }

    FlickableType {
        id: flickable

        anchors.top: header.bottom
        anchors.topMargin: 8
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

            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                Layout.bottomMargin: 6

                spacing: 2

                Image {
                    source: "qrc:/images/nexaBigLogo.png"
                    fillMode: Image.PreserveAspectFit

                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 74
                }

                Header2TextType {
                    Layout.fillWidth: true

                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("Алиса VPN")
                }

                CaptionTextType {
                    Layout.fillWidth: true

                    horizontalAlignment: Text.AlignHCenter
                    color: AmneziaStyle.color.mutedGray
                    text: qsTr("Версия %1").arg(SettingsController.getAppVersion())

                    MouseArea {
                        property int clickCount: 0
                        anchors.fill: parent
                        onClicked: {
                            if (clickCount > 10) {
                                SettingsController.enableDevMode()
                            } else {
                                clickCount++
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true

                implicitHeight: supportColumn.implicitHeight + 12
                radius: 20
                color: AmneziaStyle.color.barelyTranslucentWhite

                ColumnLayout {
                    id: supportColumn

                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 6

                    spacing: 0

                    LabelWithButtonType {
                        Layout.fillWidth: true

                        text: qsTr("Поддержка в Telegram")
                        descriptionText: "@alisa_vpn_support"
                        leftImageSource: "qrc:/images/controls/telegram.svg"
                        rightImageSource: "qrc:/images/controls/chevron-right.svg"

                        clickedFunction: function() {
                            Qt.openUrlExternally("https://t.me/alisa_vpn_support")
                        }
                    }

                    DividerType {
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    LabelWithButtonType {
                        Layout.fillWidth: true

                        text: qsTr("Наш сайт")
                        descriptionText: "alisavpn.com"
                        leftImageSource: "qrc:/images/controls/globe-2.svg"
                        rightImageSource: "qrc:/images/controls/chevron-right.svg"

                        clickedFunction: function() {
                            Qt.openUrlExternally("https://alisavpn.com")
                        }
                    }

                    DividerType {
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                    }

                    LabelWithButtonType {
                        Layout.fillWidth: true

                        text: qsTr("Частые вопросы")
                        descriptionText: qsTr("Как настроить и решить проблемы")
                        leftImageSource: "qrc:/images/controls/help-circle.svg"
                        rightImageSource: "qrc:/images/controls/chevron-right.svg"

                        clickedFunction: function() {
                            Qt.openUrlExternally("https://alisavpn.com/faq")
                        }
                    }
                }
            }

            CaptionTextType {
                Layout.fillWidth: true
                Layout.topMargin: 8

                horizontalAlignment: Text.AlignHCenter
                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.28)
                text: qsTr("Свободное ПО на основе Amnezia VPN")
            }
        }
    }
}
