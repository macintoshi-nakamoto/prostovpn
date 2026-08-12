pragma Singleton
import QtQuick

Item {
    readonly property string screenHome: "qrc:/ScreenHome.qml"
    readonly property string screenHomeIntroGifEx1: "qrc:/ScreenHomeIntroGifEx1.qml"

    readonly property int screenWidth: 380
    readonly property int screenHeight: 680

    readonly property int desktopWidth: 1060
    readonly property int desktopHeight: 680
    readonly property int sidebarWidth: 230

    readonly property int defaultMargin: 20

    function stripIp(text) {
        if (!text) {
            return ""
        }
        return String(text)
            .replace(/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?\b/g, "")
            .replace(/\s*[·,:|-]\s*$/g, "")
            .replace(/^\s*[·,:|-]\s*/g, "")
            .trim()
    }

    function isMobile() {
        if (Qt.platform.os === "android" ||
                Qt.platform.os === "ios") {
            return true
        }
        return false
    }

    function isDesktop() {
        if (Qt.platform.os === "windows" ||
                Qt.platform.os === "linux" ||
                Qt.platform.os === "osx") {
            return true
        }
        return false
    }

    TextEdit{
        id: clipboard
        visible: false
    }

    function copyToClipBoard(text) {
        clipboard.text = text
        clipboard.selectAll()
        clipboard.copy()
        clipboard.select(0, 0)
    }
}
