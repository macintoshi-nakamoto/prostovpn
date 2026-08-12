pragma Singleton

import QtQuick

QtObject {
    property QtObject color: QtObject {
        readonly property color transparent: 'transparent'
        readonly property color paleGray: '#EEF2FF'
        readonly property color lightGray: '#C9CFE2'
        readonly property color mutedGray: '#8A8C99'
        readonly property color charcoalGray: '#4A4048'
        readonly property color slateGray: '#2C2127'
        readonly property color onyxBlack: '#21191D'
        readonly property color midnightBlack: '#100A0C'
        readonly property color goldenApricot: goldenApricotString
        readonly property color benefitsPanelBackground: '#21191D'
        readonly property color softViolet: '#FF7A8A'
        readonly property color burntOrange: '#A82837'
        readonly property color mutedBrown: '#84424E'
        readonly property color richBrown: '#631F2B'
        readonly property color deepBrown: '#401419'
        readonly property color vibrantRed: '#FF5A6E'
        readonly property color darkCharcoal: '#261A1E'
        readonly property color pearlGray: '#EAEAEC'

        readonly property color sheerWhite: Qt.rgba(1, 1, 1, 0.12)
        readonly property color translucentWhite: Qt.rgba(1, 1, 1, 0.08)
        readonly property color barelyTranslucentWhite: Qt.rgba(1, 1, 1, 0.05)
        readonly property color translucentMidnightBlack: Qt.rgba(16/255, 10/255, 12/255, 0.8)
        readonly property color softGoldenApricot: Qt.rgba(255/255, 77/255, 94/255, 0.3)
        readonly property color mistyGray: Qt.rgba(238/255, 242/255, 255/255, 0.8)
        readonly property color cloudyGray: Qt.rgba(238/255, 242/255, 255/255, 0.65)
        readonly property color translucentRichBrown: Qt.rgba(99/255, 31/255, 43/255, 0.26)
        readonly property color translucentSlateGray: Qt.rgba(92/255, 85/255, 88/255, 0.13)
        readonly property color translucentOnyxBlack: Qt.rgba(33/255, 25/255, 29/255, 0.13)

        readonly property color accentDeep: '#E0284F'

        readonly property string goldenApricotString: '#FF4D5E'
    }
}
