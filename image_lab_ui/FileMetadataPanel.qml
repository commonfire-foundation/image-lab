import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: panel
    required property var theme
    required property var metadata
    signal refreshRequested()
    contentWidth: availableWidth
    ScrollBar.vertical.policy: contentHeight > availableHeight ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
    ColumnLayout {
        width: Math.max(0, panel.availableWidth - panel.effectiveScrollBarWidth - 6)
        spacing: 20
        Label {
            Layout.fillWidth: true
            text: "Read from the original file · not AI-generated"
            color: panel.theme.muted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Imagescope" + (panel.metadata.metadataVersion ? " · metadata-v" + panel.metadata.metadataVersion : "")
                color: panel.theme.muted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            ToolButton {
                objectName: "viewerMetadataRefresh"
                text: "Refresh"
                onClicked: panel.refreshRequested()
            }
        }
        Label {
            objectName: "viewerMetadataLoading"
            visible: !!panel.metadata.loading
            text: "Reading file information…"
            color: panel.theme.muted
        }
        Label {
            objectName: "viewerMetadataError"
            Layout.fillWidth: true
            visible: !!panel.metadata.error
            text: (panel.metadata.error || "") + (panel.metadata.errorCode ? "\n" + panel.metadata.errorCode : "")
            textFormat: Text.PlainText
            color: panel.theme.error
            wrapMode: Text.Wrap
        }
        ColumnLayout {
            objectName: "viewerMetadataWarnings"
            Layout.fillWidth: true
            visible: (panel.metadata.warnings || []).length > 0
            spacing: 10
            Repeater {
                model: panel.metadata.warnings || []
                Label {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.message + "\n" + modelData.field + " · " + modelData.code
                    textFormat: Text.PlainText
                    color: panel.theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
        }
        Repeater {
            model: panel.metadata.groups || []
            ColumnLayout {
                id: group
                required property var modelData
                Layout.fillWidth: true
                spacing: 12
                Label {
                    text: group.modelData.title
                    color: panel.theme.accent
                    font.pixelSize: 11
                    font.letterSpacing: 1.5
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
                Repeater {
                    model: group.modelData.rows
                    ColumnLayout {
                        id: fact
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: fact.modelData.label
                            color: panel.theme.muted
                            font.pixelSize: 11
                        }
                        Label {
                            Layout.fillWidth: true
                            text: fact.modelData.value
                            textFormat: Text.PlainText
                            color: panel.theme.foreground
                            font.pixelSize: 13
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            visible: !panel.metadata.loading && !panel.metadata.error
            text: "Header metadata only; pixels have not been validated. Unknown is not zero or absent. GPS fields are not displayed."
            color: panel.theme.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
}
