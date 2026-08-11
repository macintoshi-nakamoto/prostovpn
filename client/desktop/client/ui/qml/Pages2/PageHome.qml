import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects

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

    property var containersDropDownRef: null

    readonly property string defaultServerHost: ServersUiController.serverHostName(ServersUiController.defaultServerId)
    property string geoCountry: ""
    property string geoCity: ""
    property string geoFlag: ""

    function updateGeo() {
        geoCountry = GeoResolver.country(root.defaultServerHost)
        geoCity = GeoResolver.city(root.defaultServerHost)
        geoFlag = GeoResolver.flagSource(root.defaultServerHost)
    }

    onDefaultServerHostChanged: {
        GeoResolver.resolve(root.defaultServerHost)
        root.updateGeo()
    }

    Component.onCompleted: {
        GeoResolver.resolve(root.defaultServerHost)
        root.updateGeo()
    }

    Connections {
        target: GeoResolver

        function onResolved(host) {
            if (host === root.defaultServerHost) {
                root.updateGeo()
            }
        }
    }

    Connections {
        objectName: "pageControllerConnections"

        target: PageController

        function onRestorePageHomeState(isContainerInstalled) {
            PageController.goToPage(PageEnum.PageSettingsServersList)
        }
    }

    RadialGradient {
        anchors.horizontalCenter: parent.horizontalCenter
        y: -160
        width: parent.width + 160
        height: 420
        horizontalRadius: width / 2
        verticalRadius: height / 2

        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.alpha(AmneziaStyle.color.vibrantRed, 0.14) }
            GradientStop { position: 0.7; color: AmneziaStyle.color.transparent }
        }
    }

    Item {
        objectName: "homeColumnItem"

        anchors.fill: parent

        ColumnLayout {
            objectName: "homeColumnLayout"

            anchors.fill: parent
            anchors.topMargin: 16 + PageController.safeAreaTopMargin
            anchors.bottomMargin: 20

            BasicButtonType {
                id: devGatewayButton
                objectName: "devGatewayButton"

                property bool isDevGatewayEnabled: SettingsController.isDevGatewayEnv

                Layout.alignment: Qt.AlignHCenter

                implicitHeight: 32

                defaultColor: AmneziaStyle.color.transparent
                hoveredColor: AmneziaStyle.color.translucentWhite
                pressedColor: AmneziaStyle.color.sheerWhite
                disabledColor: AmneziaStyle.color.mutedGray
                textColor: AmneziaStyle.color.mutedGray
                borderWidth: 0

                buttonTextLabel.font.pixelSize: 13

                visible: SettingsController.isDevModeEnabled && isDevGatewayEnabled
                text: qsTr("Dev gateway enabled")

                Keys.onEnterPressed: this.clicked()
                Keys.onReturnPressed: this.clicked()

                onClicked: {
                    PageController.goToPage(PageEnum.PageDevMenu)
                }
            }

            Item {
                Layout.fillHeight: true
            }

            ConnectButton {
                id: connectButton
                objectName: "connectButton"

                Layout.alignment: Qt.AlignHCenter
            }

            Item {
                Layout.preferredHeight: 84
            }

            Button {
                id: currentServerCard
                objectName: "currentServerCard"

                property bool isFocusable: true

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 10

                implicitWidth: Math.max(340, cardContent.implicitWidth + 36)
                implicitHeight: 68

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
                    color: currentServerCard.hovered || currentServerCard.activeFocus
                           ? Qt.rgba(1, 1, 1, 0.07)
                           : Qt.rgba(1, 1, 1, 0.045)

                    Behavior on color {
                        PropertyAnimation { duration: 200 }
                    }
                }

                contentItem: RowLayout {
                    id: cardContent

                    spacing: 14

                    Item {
                        Layout.preferredWidth: 4
                    }

                    Rectangle {
                        Layout.preferredWidth: 40
                        Layout.preferredHeight: 40

                        radius: 12
                        color: Qt.alpha(AmneziaStyle.color.goldenApricot, 0.12)

                        readonly property string flagPath: ServersUiController.defaultServerImagePathCollapsed !== ""
                                                           ? ServersUiController.defaultServerImagePathCollapsed
                                                           : root.geoFlag

                        Image {
                            anchors.centerIn: parent
                            width: 26
                            height: 26
                            fillMode: Image.PreserveAspectFit

                            visible: parent.flagPath !== ""
                            source: parent.flagPath !== "" ? parent.flagPath : ""
                        }

                        Image {
                            anchors.centerIn: parent
                            width: 22
                            height: 22

                            visible: parent.flagPath === ""
                            source: "qrc:/images/controls/globe-2.svg"

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
                            Layout.maximumWidth: 280

                            maximumLineCount: 1
                            elide: Qt.ElideRight

                            text: ServersUiController.isDefaultServerFromApi || root.geoCountry === ""
                                  ? ServersUiController.defaultServerName
                                  : root.geoCountry
                        }

                        CaptionTextType {
                            Layout.maximumWidth: 300

                            visible: text !== ""
                            maximumLineCount: 1
                            elide: Qt.ElideRight

                            color: AmneziaStyle.color.mutedGray
                            text: {
                                if (!ServersUiController.isDefaultServerFromApi && root.geoCity !== "") {
                                    return root.geoCity
                                }
                                return GC.stripIp(ServersUiController.defaultServerDescriptionCollapsed)
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Image {
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18

                        source: "qrc:/images/controls/chevron-right.svg"

                        layer {
                            enabled: true
                            effect: ColorOverlay {
                                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.35)
                            }
                        }
                    }

                    Item {
                        Layout.preferredWidth: 4
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: false
                    cursorShape: Qt.PointingHandCursor
                }

                onClicked: {
                    PageController.goToPage(PageEnum.PageSettingsServersList)
                }

                Keys.onEnterPressed: this.clicked()
                Keys.onReturnPressed: this.clicked()
            }

            Item {
                Layout.fillHeight: true
            }

            AdLabel {
                id: adLabel

                Layout.fillWidth: true
                Layout.preferredHeight: adLabel.contentHeight
                Layout.leftMargin: 16
                Layout.rightMargin: 16
                Layout.topMargin: 12
            }
        }
    }
}
