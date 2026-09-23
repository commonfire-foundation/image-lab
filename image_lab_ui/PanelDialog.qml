import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    required property var theme
    property string subtitle: ""
    modal: true
    focus: true
    padding: 24
    topPadding: 20
    bottomPadding: 20
    closePolicy: Popup.CloseOnEscape
    background: Rectangle {
        color: root.theme.panel
        radius: 12
        border.color: root.theme.border
    }
    Overlay.modal: Rectangle { color: "#99000000" }
    header: ColumnLayout {
        spacing: 8
        Label {
            Layout.fillWidth: true
            Layout.topMargin: 24
            Layout.leftMargin: 24; Layout.rightMargin: 24
            text: root.title
            color: root.theme.foreground
            font.pixelSize: 24; font.weight: Font.DemiBold
        }
        Label {
            Layout.fillWidth: true
            Layout.leftMargin: 24; Layout.rightMargin: 24
            Layout.bottomMargin: 4
            visible: text.length > 0
            text: root.subtitle
            color: root.theme.muted
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
    }
}
