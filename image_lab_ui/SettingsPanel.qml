import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PanelDialog {
    id: panel
    required property var backend
    property int maximumHeight: 600
    property string saveError: ""
    title: "Settings"
    subtitle: "Make the library feel right for you."
    height: Math.min(implicitHeight, maximumHeight)
    onOpened: {
        viewerAutoplay.checked = backend.settings.autoplayViewerGifs
        sidebarAutoplay.checked = backend.settings.autoplaySidebarGifs
        hoverAnimation.checked = backend.settings.animateHoveredGifs
        saveError = ""
    }
    component PlaybackRow: Switch {
        id: control
        property string description
        Layout.fillWidth: true
        implicitHeight: rowText.implicitHeight + 32
        leftPadding: 0; rightPadding: 58
        contentItem: Column {
            id: rowText
            spacing: 5
            Label { width: parent.width; text: control.text; color: panel.theme.foreground; font.pixelSize: 14; font.weight: Font.Medium; wrapMode: Text.Wrap }
            Label { width: parent.width; text: control.description; color: panel.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
        }
        indicator: Rectangle {
            x: control.width - width; y: (control.height - height) / 2
            width: 38; height: 22; radius: 11
            color: control.checked ? panel.theme.selection : panel.theme.background
            border.color: control.visualFocus ? panel.theme.accent : panel.theme.border
            border.width: control.visualFocus ? 2 : 1
            Rectangle {
                x: control.checked ? 19 : 3; y: 3
                width: 16; height: 16; radius: 8
                color: control.checked ? panel.theme.selectionText : panel.theme.muted
            }
        }
        background: Rectangle {
            color: control.hovered ? panel.theme.button : "transparent"
            radius: 6
        }
    }
    contentItem: ScrollView {
        id: scroll
        contentWidth: availableWidth
        implicitHeight: settingsColumn.implicitHeight
        ColumnLayout {
            id: settingsColumn
            width: scroll.availableWidth
            spacing: 0
            Label { text: "GIF playback"; color: panel.theme.accent; font.pixelSize: 12; font.weight: Font.DemiBold; Layout.bottomMargin: 4 }
            PlaybackRow {
                id: viewerAutoplay
                objectName: "settingsViewerAutoplay"
                text: "Large viewer"
                description: "Play GIFs when you open an image."
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
            PlaybackRow {
                id: sidebarAutoplay
                objectName: "settingsSidebarAutoplay"
                text: "Sidebar preview"
                description: "Play GIFs alongside image details."
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
            PlaybackRow {
                id: hoverAnimation
                objectName: "settingsHoverAnimation"
                text: "Contact sheet"
                description: "Animate GIFs while the pointer is over them."
            }
            Label {
                Layout.fillWidth: true; Layout.topMargin: 14
                text: "When off, previews stay still. You can always play a GIF manually in the viewer."
                color: panel.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap
            }
        }
    }
    footer: ColumnLayout {
        spacing: 12
        Label {
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24
            visible: !!panel.saveError
            text: panel.saveError
            color: panel.theme.error; wrapMode: Text.Wrap
            Accessible.name: text
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 24; Layout.topMargin: 4; Layout.bottomMargin: 20
            spacing: 10
            Label { Layout.fillWidth: true; text: "Saved for this catalog"; color: panel.theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
            PanelButton { objectName: "cancelSettings"; theme: panel.theme; text: "Cancel"; onClicked: panel.close() }
            PanelButton {
                objectName: "saveSettings"
                theme: panel.theme; primary: true; text: "Save settings"
                onClicked: {
                    var result = panel.backend.saveSettings({
                        autoplayViewerGifs: viewerAutoplay.checked,
                        autoplaySidebarGifs: sidebarAutoplay.checked,
                        animateHoveredGifs: hoverAnimation.checked
                    })
                    if (result.ok) panel.close()
                    else panel.saveError = result.error
                }
            }
        }
    }
}
