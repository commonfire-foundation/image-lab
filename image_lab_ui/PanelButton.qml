import QtQuick
import QtQuick.Controls

Button {
    id: control
    required property var theme
    property bool primary: false
    implicitHeight: 38
    implicitWidth: Math.max(80, implicitContentWidth + 28)
    horizontalPadding: 14
    font.pixelSize: 13
    font.weight: primary ? Font.DemiBold : Font.Normal
    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? control.theme.disabled : control.primary ? control.theme.selectionText : control.theme.foreground
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 6
        color: control.primary ? control.theme.selection : control.down ? control.theme.background : control.hovered ? control.theme.button : "transparent"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? control.theme.accent : control.primary ? control.theme.selection : control.theme.border
        opacity: control.enabled ? 1 : 0.5
    }
}
