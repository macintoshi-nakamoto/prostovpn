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
 * Аккаунт: что оплачено, сколько осталось и кнопка выхода.
 *
 * Ни адресов серверов, ни ключей здесь нет — только то, что человеку
 * действительно нужно знать про свою подписку.
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

                headerText: PanelAuthController.accountName
                descriptionText: qsTr("Номер аккаунта: %1").arg(PanelAuthController.accountPublicId)
            }

            LabelWithButtonType {
                Layout.fillWidth: true
                Layout.topMargin: 24

                text: qsTr("Подписка")
                descriptionText: PanelAuthController.subscriptionActive
                        ? qsTr("%1 · осталось дней: %2")
                            .arg(PanelAuthController.subscriptionPlan)
                            .arg(PanelAuthController.subscriptionDaysLeft)
                        : qsTr("Не оплачена")
            }

            DividerType {}

            LabelWithButtonType {
                Layout.fillWidth: true

                text: qsTr("Трафик")
                descriptionText: qsTr("%1 из %2")
                        .arg(PanelAuthController.trafficUsedText)
                        .arg(PanelAuthController.trafficLimitText)
            }

            DividerType {}

            LabelWithButtonType {
                Layout.fillWidth: true

                text: qsTr("Логин")
                descriptionText: PanelAuthController.accountLogin
            }

            DividerType {}

            ParagraphTextType {
                Layout.fillWidth: true
                Layout.topMargin: 24

                visible: !PanelAuthController.subscriptionActive
                color: AmneziaStyle.color.vibrantRed
                wrapMode: Text.WordWrap
                text: qsTr("Пока подписка не оплачена, страны для подключения не выдаются. Напишите администратору сервиса.")
            }

            BasicButtonType {
                Layout.fillWidth: true
                Layout.topMargin: 32

                defaultColor: AmneziaStyle.color.transparent
                hoveredColor: AmneziaStyle.color.translucentWhite
                pressedColor: AmneziaStyle.color.sheerWhite
                textColor: AmneziaStyle.color.vibrantRed
                borderWidth: 1

                text: qsTr("Обновить список стран")

                clickedFunc: function() {
                    PanelAuthController.refresh()
                    PageController.showNotificationMessage(qsTr("Обновляем…"))
                }
            }

            BasicButtonType {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.bottomMargin: 32

                defaultColor: AmneziaStyle.color.transparent
                hoveredColor: AmneziaStyle.color.translucentWhite
                pressedColor: AmneziaStyle.color.sheerWhite
                textColor: AmneziaStyle.color.vibrantRed
                borderWidth: 1

                text: qsTr("Выйти из аккаунта")

                clickedFunc: function() {
                    PanelAuthController.logout()
                    PageController.goToPageHome()
                }
            }
        }
    }
}
