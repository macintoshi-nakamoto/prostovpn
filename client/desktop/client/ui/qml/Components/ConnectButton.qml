import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import Qt5Compat.GraphicalEffects

import ConnectionState 1.0
import PageEnum 1.0
import Style 1.0

Button {
    id: root

    property string defaultButtonColor: AmneziaStyle.color.paleGray
    property string progressButtonColor: AmneziaStyle.color.paleGray
    property string connectedButtonColor: AmneziaStyle.color.goldenApricot
    property bool buttonActiveFocus: activeFocus && (Qt.platform.os !== "android" || SettingsController.isOnTv())

    property bool isFocusable: true

    readonly property bool isOn: ConnectionController.isConnected
    readonly property bool isBusy: ConnectionController.isConnectionInProgress

    readonly property color onStroke: Qt.rgba(255 / 255, 77 / 255, 94 / 255, 0.8)
    readonly property color idleStroke: Qt.rgba(1, 1, 1, 0.1)
    readonly property color glyphOff: Qt.rgba(235 / 255, 240 / 255, 255 / 255, 0.55)

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

    implicitWidth: 190
    implicitHeight: 190

    text: ConnectionController.connectionStateText

    Connections {
        target: ConnectionController

        function onPreparingConfig() {
            PageController.showNotificationMessage(qsTr("Unable to disconnect during configuration preparation"))
        }
    }

    property int connectedSeconds: 0

    function formatDuration(totalSeconds) {
        var minutes = Math.floor(totalSeconds / 60)
        var seconds = totalSeconds % 60
        return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0")
    }

    Timer {
        interval: 1000
        repeat: true
        running: root.isOn
        onTriggered: root.connectedSeconds += 1
    }

    onIsOnChanged: {
        connectedSeconds = 0
        if (isOn) {
            popAnimation.restart()
        }
    }

    SequentialAnimation {
        id: popAnimation

        NumberAnimation {
            target: circle
            property: "scale"
            from: 0.92
            to: 1.03
            duration: 270
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            target: circle
            property: "scale"
            to: 1.0
            duration: 180
            easing.type: Easing.OutCubic
        }
    }

    background: Item {
        implicitWidth: parent.width
        implicitHeight: parent.height
        transformOrigin: Item.Center
        scale: root.pressed ? 0.96 : 1

        Behavior on scale {
            NumberAnimation { duration: 120 }
        }

        RadialGradient {
            anchors.centerIn: parent
            width: 340
            height: 340
            horizontalRadius: width / 2
            verticalRadius: height / 2

            opacity: root.isOn ? 1 : 0
            visible: opacity > 0

            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(255 / 255, 77 / 255, 94 / 255, 0.28) }
                GradientStop { position: 0.5; color: AmneziaStyle.color.transparent }
            }

            Behavior on opacity {
                NumberAnimation { duration: 450 }
            }
        }

        Rectangle {
            id: circle

            anchors.centerIn: parent
            width: 190
            height: 190
            radius: width / 2

            color: AmneziaStyle.color.barelyTranslucentWhite
            border.width: 2
            border.color: {
                if (root.buttonActiveFocus) {
                    return AmneziaStyle.color.paleGray
                }
                return root.isOn ? root.onStroke : root.idleStroke
            }

            Behavior on border.color {
                ColorAnimation { duration: 350 }
            }
        }

        Shape {
            id: spinner

            x: circle.x
            y: circle.y
            width: 190
            height: 190

            visible: root.isBusy
            layer.enabled: true
            layer.samples: 4

            ShapePath {
                fillColor: AmneziaStyle.color.transparent
                strokeColor: AmneziaStyle.color.goldenApricot
                strokeWidth: 2.5
                capStyle: ShapePath.RoundCap

                PathAngleArc {
                    centerX: 95
                    centerY: 95
                    radiusX: 83
                    radiusY: 83
                    startAngle: 245
                    sweepAngle: -160
                }
            }

            RotationAnimator {
                target: spinner
                running: root.isBusy
                from: 0
                to: 360
                loops: Animation.Infinite
                duration: 1100
            }
        }
    }

    contentItem: Item {
        Shape {
            id: glyph

            property color glyphColor: (root.isOn || root.isBusy) ? "#FFFFFF" : root.glyphOff

            anchors.centerIn: parent
            width: 64
            height: 64
            layer.enabled: true
            layer.samples: 4

            Behavior on glyphColor {
                ColorAnimation { duration: 350 }
            }

            ShapePath {
                fillColor: AmneziaStyle.color.transparent
                strokeColor: glyph.glyphColor
                strokeWidth: 5
                capStyle: ShapePath.RoundCap

                PathAngleArc {
                    centerX: 32
                    centerY: 34
                    radiusX: 21
                    radiusY: 21
                    startAngle: -65
                    sweepAngle: 310
                }
            }

            ShapePath {
                fillColor: AmneziaStyle.color.transparent
                strokeColor: glyph.glyphColor
                strokeWidth: 5
                capStyle: ShapePath.RoundCap

                startX: 32
                startY: 7
                PathLine { x: 32; y: 31 }
            }
        }
    }

    MouseArea {
        anchors.fill: parent

        cursorShape: Qt.PointingHandCursor
        enabled: false
    }

    Text {
        id: statusLabel

        anchors.top: parent.bottom
        anchors.topMargin: 28
        anchors.horizontalCenter: parent.horizontalCenter

        font.family: "PT Root UI VF"
        font.weight: 700
        font.pixelSize: 22

        color: AmneziaStyle.color.paleGray
        text: root.text

        horizontalAlignment: Text.AlignHCenter
    }

    Text {
        id: durationLabel

        anchors.top: statusLabel.bottom
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter

        height: 20

        font.family: "PT Root UI VF"
        font.weight: 500
        font.pixelSize: 15

        color: AmneziaStyle.color.mutedGray
        text: root.isOn ? root.formatDuration(root.connectedSeconds) : ""

        horizontalAlignment: Text.AlignHCenter
    }

    onClicked: {
        ConnectionController.connectButtonClicked()
    }

    Keys.onEnterPressed: this.clicked()
    Keys.onReturnPressed: this.clicked()
}
