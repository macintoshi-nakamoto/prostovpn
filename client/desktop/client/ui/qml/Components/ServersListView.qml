import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects

import SortFilterProxyModel 0.2

import PageEnum 1.0
import ContainerProps 1.0
import ContainersModelFilters 1.0
import Style 1.0

import "./"
import "../Controls2"
import "../Controls2/TextTypes"
import "../Config"

ListViewType {
    id: root

    property int selectedIndex: ServersUiController.getServerIndexById(ServersUiController.defaultServerId)

    anchors.top: serversMenuHeader.bottom
    anchors.right: parent.right
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    anchors.topMargin: 8

    model: ServersModel

    Connections {
        target: ServersUiController
        function onDefaultServerIdChanged() {
            root.selectedIndex = ServersUiController.getServerIndexById(ServersUiController.defaultServerId)
        }
    }

    delegate: Item {
        id: menuContentDelegate
        objectName: "menuContentDelegate"

        property variant delegateData: model

        implicitWidth: root.width
        implicitHeight: serverRowButton.implicitHeight + 6

        Button {
            id: serverRowButton
            objectName: "serverRowButton"

            property bool isFocusable: true

            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: 16

            implicitHeight: 64

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
                radius: 16

                color: {
                    if (index === root.selectedIndex) {
                        return Qt.alpha(AmneziaStyle.color.goldenApricot, 0.07)
                    }
                    if (serverRowButton.hovered || serverRowButton.activeFocus) {
                        return AmneziaStyle.color.translucentWhite
                    }
                    return AmneziaStyle.color.transparent
                }

                Behavior on color {
                    PropertyAnimation { duration: 200 }
                }
            }

            contentItem: RowLayout {
                spacing: 14

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    Layout.leftMargin: 6

                    radius: 12
                    color: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.12)

                    Image {
                        anchors.centerIn: parent
                        width: 20
                        height: 20

                        source: "qrc:/images/controls/server.svg"

                        layer {
                            enabled: true
                            effect: ColorOverlay {
                                color: AmneziaStyle.color.softViolet
                            }
                        }
                    }
                }

                ColumnLayout {
                    spacing: 2

                    ListItemTitleType {
                        Layout.fillWidth: true

                        maximumLineCount: 1
                        elide: Qt.ElideRight

                        text: name
                    }

                    CaptionTextType {
                        Layout.fillWidth: true

                        visible: text !== ""
                        maximumLineCount: 1
                        elide: Qt.ElideRight

                        text: isServerFromGatewayApi && (isSubscriptionExpired || isSubscriptionExpiringSoon)
                            ? (isSubscriptionExpired ? qsTr("Subscription expired. Please renew") : qsTr("Subscription expiring soon"))
                            : serverDescription
                        color: isServerFromGatewayApi && (isSubscriptionExpired || isSubscriptionExpiringSoon)
                            ? (isSubscriptionExpired ? AmneziaStyle.color.vibrantRed : AmneziaStyle.color.softViolet)
                            : AmneziaStyle.color.mutedGray
                    }
                }

                Image {
                    Layout.preferredWidth: 22
                    Layout.preferredHeight: 22

                    visible: index === root.selectedIndex
                    source: "qrc:/images/controls/check.svg"

                    layer {
                        enabled: true
                        effect: ColorOverlay {
                            color: AmneziaStyle.color.goldenApricot
                        }
                    }
                }

                Item {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                }
            }

            onClicked: {
                if (ConnectionController.isConnected) {
                    PageController.showNotificationMessage(qsTr("Unable change server while there is an active connection"))
                    return
                }

                if (index === root.selectedIndex) {
                    return
                }

                root.selectedIndex = index

                ServersUiController.setDefaultServerAtIndex(index)
            }

            Keys.onEnterPressed: serverRowButton.clicked()
            Keys.onReturnPressed: serverRowButton.clicked()
        }

        ImageButtonType {
            id: serverInfoButton
            objectName: "serverInfoButton"

            anchors.verticalCenter: serverRowButton.verticalCenter
            anchors.right: serverRowButton.right
            anchors.rightMargin: 8

            image: "qrc:/images/controls/settings.svg"
            imageColor: AmneziaStyle.color.mutedGray

            icon.width: 20
            icon.height: 20
            backgroundRadius: 12
            horizontalPadding: 8
            topPadding: 8
            bottomPadding: 8

            z: 1

            onClicked: function() {
                ServersUiController.setProcessedServerId(serverId)

                if (ServersUiController.isServerFromApi(ServersUiController.processedServerId)) {
                    if (ServersUiController.isServerCountrySelectionAvailable(ServersUiController.processedServerId)) {
                        PageController.goToPage(PageEnum.PageSettingsApiAvailableCountries)
                    } else {
                        PageController.showBusyIndicator(true)
                        let result = SubscriptionUiController.getAccountInfo(ServersUiController.processedServerId, false)
                        PageController.showBusyIndicator(false)
                        if (!result) {
                            return
                        }

                        PageController.goToPage(PageEnum.PageSettingsApiServerInfo)
                    }
                } else {
                    PageController.goToPage(PageEnum.PageSettingsServerInfo)
                }

                drawer.closeTriggered()
            }
        }
    }
}
