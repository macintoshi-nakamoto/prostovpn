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
import "../Components"

PageType {
    id: root

    property int selectedIndex: ServersUiController.getServerIndexById(ServersUiController.defaultServerId)

    property var apiAvailableProtocols: []
    property string apiCurrentProtocol: ""

    readonly property bool isApiProtocolSelectionVisible: ServersUiController.isDefaultServerFromApi && root.apiAvailableProtocols.length > 0

    function updateApiProtocolState() {
        if (ServersUiController.isDefaultServerFromApi) {
            root.apiAvailableProtocols = SubscriptionUiController.availableProtocols(ServersUiController.defaultServerId)
            root.apiCurrentProtocol = SubscriptionUiController.currentProtocol(ServersUiController.defaultServerId)
        } else {
            root.apiAvailableProtocols = []
            root.apiCurrentProtocol = ""
        }
    }

    function protocolDisplayName(protocol) {
        switch (protocol) {
        case "awg": return "AmneziaWG"
        case "vless": return "VLESS"
        default: return protocol
        }
    }

    Component.onCompleted: {
        root.updateApiProtocolState()
    }

    Connections {
        target: ServersUiController

        function onDefaultServerIdChanged() {
            root.selectedIndex = ServersUiController.getServerIndexById(ServersUiController.defaultServerId)
            root.updateApiProtocolState()
        }
    }

    ColumnLayout {
        id: header

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right

        anchors.topMargin: 24 + PageController.safeAreaTopMargin

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 34
            Layout.rightMargin: 28

            BaseHeaderType {
                Layout.fillWidth: true

                headerText: qsTr("Серверы")
            }
        }

        RowLayout {
            objectName: "protocolRowLayout"
            Layout.leftMargin: 34
            Layout.topMargin: 2

            visible: root.isApiProtocolSelectionVisible

            BasicButtonType {
                id: protocolButton
                objectName: "protocolButton"

                enabled: root.apiAvailableProtocols.length > 1
                hoverEnabled: enabled

                implicitHeight: 36

                leftPadding: 16
                rightPadding: 16

                defaultColor: AmneziaStyle.color.transparent
                hoveredColor: AmneziaStyle.color.translucentWhite
                pressedColor: AmneziaStyle.color.sheerWhite
                disabledColor: AmneziaStyle.color.transparent
                textColor: AmneziaStyle.color.mutedGray

                buttonTextLabel.lineHeight: 16
                buttonTextLabel.font.pixelSize: 13
                buttonTextLabel.font.weight: 400

                text: root.apiAvailableProtocols.length > 1
                    ? root.protocolDisplayName(root.apiCurrentProtocol)
                    : root.protocolDisplayName(root.apiAvailableProtocols[0])
                leftImageSource: "qrc:/images/controls/arrow-left-right.svg"
                leftImageColor: AmneziaStyle.color.mutedGray

                rightImageSource: enabled ? "qrc:/images/controls/chevron-down.svg" : ""

                Keys.onEnterPressed: this.clicked()
                Keys.onReturnPressed: this.clicked()

                onClicked: {
                    if (ConnectionController.isConnectionInProgress) {
                        PageController.showNotificationMessage(qsTr("Unable change protocol while trying to make an active connection"))
                        return
                    }
                    if (ConnectionController.isConnected) {
                        PageController.showNotificationMessage(qsTr("Cannot change protocol during active connection"))
                        return
                    }
                    protocolSelectionDrawer.openTriggered()
                }
            }
        }
    }

    ListViewType {
        id: servers
        objectName: "servers"

        anchors.top: header.bottom
        anchors.topMargin: 12
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right

        model: ServersModel

        delegate: Item {
            id: menuContentDelegate

            property variant delegateData: model

            readonly property string rowHost: hostName
            readonly property bool useGeo: !isServerFromGatewayApi
            property string geoCountry: ""
            property string geoCity: ""
            property string geoFlag: ""

            function updateGeo() {
                geoCountry = GeoResolver.country(rowHost)
                geoCity = GeoResolver.city(rowHost)
                geoFlag = GeoResolver.flagSource(rowHost)
            }

            Component.onCompleted: {
                if (useGeo) {
                    GeoResolver.resolve(rowHost)
                    updateGeo()
                }
            }

            Connections {
                target: GeoResolver
                enabled: menuContentDelegate.useGeo

                function onResolved(host) {
                    if (host === menuContentDelegate.rowHost) {
                        menuContentDelegate.updateGeo()
                    }
                }
            }

            implicitWidth: servers.width
            implicitHeight: serverRowButton.implicitHeight + 8

            Button {
                id: serverRowButton
                objectName: "serverRowButton"

                property bool isFocusable: true

                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 28
                anchors.rightMargin: 28

                implicitHeight: 70

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
                    radius: 18

                    color: {
                        if (index === root.selectedIndex) {
                            return Qt.alpha(AmneziaStyle.color.goldenApricot, 0.07)
                        }
                        if (serverRowButton.hovered || serverRowButton.activeFocus) {
                            return AmneziaStyle.color.translucentWhite
                        }
                        return AmneziaStyle.color.barelyTranslucentWhite
                    }

                    Behavior on color {
                        PropertyAnimation { duration: 200 }
                    }
                }

                contentItem: RowLayout {
                    spacing: 14

                    Item {
                        Layout.preferredWidth: 4
                    }

                    Rectangle {
                        Layout.preferredWidth: 44
                        Layout.preferredHeight: 44

                        radius: 13
                        color: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.12)

                        Image {
                            anchors.centerIn: parent
                            width: 26
                            height: 26
                            fillMode: Image.PreserveAspectFit

                            visible: menuContentDelegate.geoFlag !== ""
                            source: menuContentDelegate.geoFlag !== "" ? menuContentDelegate.geoFlag : ""
                        }

                        Image {
                            anchors.centerIn: parent
                            width: 22
                            height: 22

                            visible: menuContentDelegate.geoFlag === ""
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

                            text: menuContentDelegate.useGeo && menuContentDelegate.geoCountry !== ""
                                  ? menuContentDelegate.geoCountry
                                  : name
                        }

                        CaptionTextType {
                            Layout.fillWidth: true

                            visible: text !== ""
                            maximumLineCount: 1
                            elide: Qt.ElideRight

                            text: {
                                if (isServerFromGatewayApi && (isSubscriptionExpired || isSubscriptionExpiringSoon)) {
                                    return isSubscriptionExpired ? qsTr("Subscription expired. Please renew") : qsTr("Subscription expiring soon")
                                }
                                if (menuContentDelegate.useGeo && menuContentDelegate.geoCity !== "") {
                                    return menuContentDelegate.geoCity
                                }
                                return GC.stripIp(serverDescription)
                            }
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
                        Layout.preferredWidth: 10
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: false
                    cursorShape: Qt.PointingHandCursor
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

        }
    }

    DrawerType2 {
        id: protocolSelectionDrawer
        objectName: "protocolSelectionDrawer"

        anchors.fill: parent

        expandedStateContent: Item {
            id: protocolDrawerContainer

            implicitHeight: root.height * 0.5

            Component.onCompleted: {
                protocolSelectionDrawer.expandedHeight = protocolDrawerContainer.implicitHeight
            }

            ColumnLayout {
                id: protocolDrawerHeader

                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.topMargin: 16

                BackButtonType {
                    id: protocolDrawerBackButton

                    Layout.fillWidth: true

                    backButtonImage: "qrc:/images/controls/arrow-left.svg"
                    backButtonFunction: function() { protocolSelectionDrawer.closeTriggered() }
                }

                Header2Type {
                    Layout.fillWidth: true
                    Layout.topMargin: 16
                    Layout.leftMargin: 16
                    Layout.rightMargin: 16

                    headerText: qsTr("VPN protocol")
                }
            }

            ListViewType {
                id: protocolDrawerListView

                anchors.top: protocolDrawerHeader.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.topMargin: 16

                model: root.apiAvailableProtocols

                ButtonGroup {
                    id: protocolDrawerButtonGroup
                }

                delegate: Item {
                    implicitWidth: protocolDrawerListView.width
                    implicitHeight: protocolDrawerDelegate.implicitHeight

                    ColumnLayout {
                        id: protocolDrawerDelegate

                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16

                        VerticalRadioButton {
                            id: protocolDrawerRadioButton

                            Layout.fillWidth: true

                            text: root.protocolDisplayName(modelData)

                            ButtonGroup.group: protocolDrawerButtonGroup

                            checkable: !ConnectionController.isConnected
                            checked: modelData === root.apiCurrentProtocol

                            onClicked: {
                                protocolSelectionDrawer.closeTriggered()

                                if (modelData === root.apiCurrentProtocol) {
                                    return
                                }

                                if (ConnectionController.isConnected) {
                                    PageController.showNotificationMessage(qsTr("Cannot change protocol during active connection"))
                                    return
                                }

                                PageController.showBusyIndicator(true)
                                ServersUiController.setProcessedServerId(ServersUiController.defaultServerId)
                                SubscriptionUiController.setCurrentProtocol(ServersUiController.defaultServerId, modelData)
                                if (!SubscriptionUiController.updateServiceFromGateway(ServersUiController.defaultServerId, "", "", true)) {
                                    SubscriptionUiController.setCurrentProtocol(ServersUiController.defaultServerId, root.apiCurrentProtocol)
                                }
                                root.updateApiProtocolState()
                                PageController.showBusyIndicator(false)
                            }

                            Keys.onEnterPressed: protocolDrawerRadioButton.clicked()
                            Keys.onReturnPressed: protocolDrawerRadioButton.clicked()
                        }

                        DividerType {
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
    }
}
