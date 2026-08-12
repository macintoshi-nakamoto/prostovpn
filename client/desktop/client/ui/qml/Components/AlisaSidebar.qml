import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects

import Style 1.0

import "../Controls2"
import "../Controls2/TextTypes"
import "../Config"

Item {
    id: root

    property int currentIndex: 0

    property var tabs: []

    implicitWidth: GC.sidebarWidth

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: AmneziaStyle.color.translucentWhite
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 15
        anchors.topMargin: 8
        anchors.bottomMargin: 20

        spacing: 4

        Image {
            source: "qrc:/images/nexaBigLogo.png"
            fillMode: Image.PreserveAspectFit

            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 92
            Layout.preferredHeight: 62
            Layout.topMargin: 10
            Layout.bottomMargin: 14
        }

        Repeater {
            model: root.tabs.length

            delegate: Button {
                id: tabButton

                required property int index

                readonly property bool isActive: root.currentIndex === index

                property bool isFocusable: true

                Layout.fillWidth: true

                implicitHeight: 44

                hoverEnabled: true

                Keys.onTabPressed: {
                    FocusController.nextKeyTabItem()
                }
                Keys.onBacktabPressed: {
                    FocusController.previousKeyTabItem()
                }
                Keys.onUpPressed: {
                    FocusController.nextKeyUpItem()
                }
                Keys.onDownPressed: {
                    FocusController.nextKeyDownItem()
                }
                Keys.onLeftPressed: {
                    FocusController.nextKeyLeftItem()
                }
                Keys.onRightPressed: {
                    FocusController.nextKeyRightItem()
                }

                background: Rectangle {
                    radius: 13

                    color: {
                        if (tabButton.isActive) {
                            return AmneziaStyle.color.goldenApricot
                        }
                        if (tabButton.hovered || tabButton.activeFocus) {
                            return AmneziaStyle.color.translucentWhite
                        }
                        return AmneziaStyle.color.transparent
                    }

                    Behavior on color {
                        PropertyAnimation { duration: 200 }
                    }
                }

                contentItem: RowLayout {
                    spacing: 11

                    Item {
                        Layout.preferredWidth: 2
                    }

                    Image {
                        Layout.preferredWidth: 19
                        Layout.preferredHeight: 19

                        source: root.tabs[tabButton.index].icon

                        layer {
                            enabled: true
                            effect: ColorOverlay {
                                color: tabButton.isActive ? "#FFFFFF" : Qt.alpha(AmneziaStyle.color.paleGray, 0.55)
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true

                        font.family: "PT Root UI VF"
                        font.pixelSize: 15
                        font.weight: 700

                        color: tabButton.isActive ? "#FFFFFF" : Qt.alpha(AmneziaStyle.color.paleGray, 0.55)
                        text: root.tabs[tabButton.index].title

                        Behavior on color {
                            PropertyAnimation { duration: 200 }
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: false
                    cursorShape: Qt.PointingHandCursor
                }

                onClicked: {
                    root.currentIndex = index
                    root.tabs[index].handler()
                }

                Keys.onEnterPressed: this.clicked()
                Keys.onReturnPressed: this.clicked()
            }
        }

        Item {
            Layout.fillHeight: true
        }

        Button {
            id: userCard

            property bool isFocusable: true

            Layout.fillWidth: true

            implicitHeight: 54

            hoverEnabled: true

            Keys.onTabPressed: {
                FocusController.nextKeyTabItem()
            }
            Keys.onBacktabPressed: {
                FocusController.previousKeyTabItem()
            }
            Keys.onUpPressed: {
                FocusController.nextKeyUpItem()
            }
            Keys.onDownPressed: {
                FocusController.nextKeyDownItem()
            }
            Keys.onLeftPressed: {
                FocusController.nextKeyLeftItem()
            }
            Keys.onRightPressed: {
                FocusController.nextKeyRightItem()
            }

            readonly property bool showLogout: hovered || activeFocus

            background: Rectangle {
                radius: 14
                color: userCard.showLogout ? Qt.alpha(AmneziaStyle.color.goldenApricot, 0.1) : Qt.rgba(1, 1, 1, 0.04)

                Behavior on color {
                    PropertyAnimation { duration: 200 }
                }
            }

            contentItem: RowLayout {
                spacing: 10

                Item {
                    Layout.preferredWidth: 0
                }

                Rectangle {
                    Layout.preferredWidth: 34
                    Layout.preferredHeight: 34

                    radius: 17
                    color: AmneziaStyle.color.goldenApricot

                    Text {
                        anchors.centerIn: parent

                        font.family: "PT Root UI VF"
                        font.pixelSize: 14
                        font.weight: 800

                        color: "#FFFFFF"
                        text: "А"
                    }
                }

                Text {
                    Layout.fillWidth: true

                    font.family: "PT Root UI VF"
                    font.pixelSize: 13
                    font.weight: 700

                    elide: Text.ElideRight
                    color: userCard.showLogout ? AmneziaStyle.color.vibrantRed : AmneziaStyle.color.paleGray
                    text: userCard.showLogout ? qsTr("Выйти") : qsTr("Алиса VPN")

                    Behavior on color {
                        PropertyAnimation { duration: 150 }
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: false
                cursorShape: Qt.PointingHandCursor
            }

            onClicked: {
                var headerText = qsTr("Уверены, что хотите выйти?")
                var descriptionText = qsTr("Настройки будут сброшены, для входа понадобится снова ввести ключ доступа.")
                var yesButtonText = qsTr("Да")
                var noButtonText = qsTr("Нет")

                var yesButtonFunction = function() {
                    if (ServersUiController.isDefaultServerCurrentlyProcessed() && ConnectionController.isConnected) {
                        PageController.showNotificationMessage(qsTr("Нельзя выйти при активном подключении"))
                    } else {
                        SettingsController.clearSettings()
                        PageController.goToPageHome()
                    }
                }
                var noButtonFunction = function() {
                }

                showQuestionDrawer(headerText, descriptionText, yesButtonText, noButtonText, yesButtonFunction, noButtonFunction)
            }

            Keys.onEnterPressed: this.clicked()
            Keys.onReturnPressed: this.clicked()
        }
    }
}
