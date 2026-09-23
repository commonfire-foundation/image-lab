import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PanelDialog {
    id: panel
    title: "Image Lab"
    subtitle: "A closer look at your image library."
    header: ColumnLayout {
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 20
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            spacing: 16
            Label {
                Layout.fillWidth: true
                text: panel.title
                color: panel.theme.foreground
                font.pixelSize: 24
                font.weight: Font.DemiBold
            }
            PanelButton {
                objectName: "aboutClose"
                theme: panel.theme
                text: "\u00d7"
                implicitWidth: 38
                font.pixelSize: 24
                Accessible.name: "Close About Image Lab"
                ToolTip.visible: hovered
                ToolTip.text: "Close (Esc)"
                onClicked: panel.close()
            }
        }
        Label {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            text: panel.subtitle
            color: panel.theme.muted
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
    }
    component CreditLink: AbstractButton {
        id: link
        required property url destination
        implicitWidth: implicitContentWidth + 8
        implicitHeight: implicitContentHeight + 8
        padding: 4
        Accessible.role: Accessible.Link
        onClicked: Qt.openUrlExternally(destination)
        contentItem: Text {
            text: link.text
            color: panel.theme.accent
            font.pixelSize: 13
            font.underline: true
        }
        background: Rectangle {
            radius: 4
            color: link.hovered ? panel.theme.button : "transparent"
            border.color: link.visualFocus ? panel.theme.accent : "transparent"
        }
        ToolTip.visible: hovered
        ToolTip.text: destination.toString()
    }
    contentItem: ColumnLayout {
        spacing: 20
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 88
            color: panel.theme.background; radius: 8
            RowLayout {
                anchors.fill: parent; anchors.margins: 16; spacing: 16
                Rectangle {
                    width: 48; height: 48; radius: 6
                    color: panel.theme.selection
                    Label { anchors.centerIn: parent; text: "IL"; color: panel.theme.selectionText; font.pixelSize: 22; font.weight: Font.DemiBold }
                }
                Label {
                    Layout.fillWidth: true
                    text: "Explore images. Generate tags.\nRefine the details."
                    color: panel.theme.foreground; font.pixelSize: 14; wrapMode: Text.Wrap
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Your library, on this computer"; color: panel.theme.foreground; font.weight: Font.Medium }
            Label { Layout.fillWidth: true; text: "Your catalog is stored locally, ready to browse without running analysis."; color: panel.theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Originals stay yours"; color: panel.theme.foreground; font.weight: Font.Medium }
            Label { Layout.fillWidth: true; text: "Scanning and analysis leave your files untouched. Renaming always asks for confirmation."; color: panel.theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
        RowLayout {
            objectName: "aboutCredits"
            Layout.fillWidth: true
            spacing: 12
            Image {
                objectName: "commonfireLogo"
                Layout.preferredWidth: 48
                Layout.preferredHeight: 48
                source: "assets/commonfire-logo.svg"
                sourceSize.width: Math.round(48 * Screen.devicePixelRatio)
                sourceSize.height: Math.round(48 * Screen.devicePixelRatio)
                fillMode: Image.PreserveAspectFit
                smooth: true
                Accessible.ignored: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                CreditLink {
                    text: "Created by OldJobobo"
                    destination: "https://github.com/OldJobobo"
                }
                CreditLink {
                    text: "Published by CommonFIRE"
                    destination: "https://github.com/commonfire-foundation"
                }
            }
        }
    }
}
