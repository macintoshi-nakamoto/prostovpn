import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import PageEnum 1.0
import Style 1.0

import "./"
import "../Controls2"
import "../Controls2/TextTypes"
import "../Config"
import "../Components"

/**
 * Обновление приложения.
 *
 * Кнопка скачивает установщик и запускает его. Он ставится поверх, поэтому
 * ни удалять приложение, ни входить заново не нужно — настройки и аккаунт
 * остаются на месте.
 */
PageType {
    id: root

    BackButtonType {
        id: backButton

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 20 + PageController.safeAreaTopMargin
    }

    FlickableType {
        id: fl

        anchors.top: backButton.bottom
        contentHeight: content.implicitHeight + 60

        ColumnLayout {
            id: content

            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 0

            Header2Type {
                Layout.fillWidth: true
                Layout.topMargin: 8

                headerText: AppUpdateController.updateAvailable
                        ? qsTr("Доступна версия %1").arg(AppUpdateController.latestVersion)
                        : qsTr("Обновлений нет")
                descriptionText: qsTr("Установлена версия %1").arg(AppUpdateController.currentVersion)
            }

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.topMargin: 20

                visible: AppUpdateController.mandatory
                color: AmneziaStyle.color.vibrantRed
                wrapMode: Text.WordWrap
                text: qsTr("Это обновление обязательное — без него подключение работать не будет.")
            }

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.topMargin: 16

                visible: AppUpdateController.changelog !== ""
                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.75)
                wrapMode: Text.WordWrap
                text: AppUpdateController.changelog
            }

            ProgressBarType {
                Layout.fillWidth: true
                Layout.topMargin: 24

                visible: AppUpdateController.busy
                value: AppUpdateController.progress / 100
            }

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.topMargin: 8

                visible: AppUpdateController.busy
                horizontalAlignment: Text.AlignHCenter
                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.6)
                text: qsTr("Скачиваем… %1%").arg(AppUpdateController.progress)
            }

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.topMargin: 16

                visible: AppUpdateController.errorString !== ""
                color: AmneziaStyle.color.vibrantRed
                wrapMode: Text.WordWrap
                text: AppUpdateController.errorString
            }

            BasicButtonType {
                Layout.fillWidth: true
                Layout.topMargin: 28

                visible: AppUpdateController.updateAvailable
                enabled: !AppUpdateController.busy

                text: AppUpdateController.busy ? qsTr("Скачиваем…") : qsTr("Обновить")

                clickedFunc: function() {
                    AppUpdateController.downloadAndInstall()
                }
            }

            BasicButtonType {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.bottomMargin: 32

                defaultColor: AmneziaStyle.color.transparent
                hoveredColor: AmneziaStyle.color.translucentWhite
                pressedColor: AmneziaStyle.color.sheerWhite
                textColor: AmneziaStyle.color.paleGray
                borderWidth: 1

                enabled: !AppUpdateController.busy
                text: qsTr("Проверить ещё раз")

                clickedFunc: function() {
                    AppUpdateController.check()
                    PageController.showNotificationMessage(qsTr("Проверяем…"))
                }
            }

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.bottomMargin: 32

                horizontalAlignment: Text.AlignHCenter
                color: Qt.alpha(AmneziaStyle.color.paleGray, 0.4)
                wrapMode: Text.WordWrap
                text: qsTr("Установщик ставится поверх: удалять приложение и входить заново не нужно.")
            }
        }
    }
}
