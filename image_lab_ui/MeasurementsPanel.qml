import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: panel
    required property var theme
    required property var measurements
    property string objectPrefix: "viewer"
    property bool refreshEnabled: true
    signal refreshRequested()
    contentWidth: availableWidth
    ScrollBar.vertical.policy: contentHeight > availableHeight ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
    ColumnLayout {
        width: Math.max(0, panel.availableWidth - panel.effectiveScrollBarWidth - 6)
        spacing: 18
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Imagescope · measured, not AI-generated"
                color: panel.theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            ToolButton {
                objectName: panel.objectPrefix + "MeasurementsRefresh"
                enabled: panel.refreshEnabled
                Accessible.name: "Refresh original-image measurements"
                text: "Refresh"
                onClicked: panel.refreshRequested()
            }
        }
        Label {
            objectName: panel.objectPrefix + "MeasurementsLoading"
            visible: !!panel.measurements.loading
            text: "Measuring the original image…"
            color: panel.theme.muted
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        Label {
            objectName: panel.objectPrefix + "MeasurementsError"
            visible: !!panel.measurements.error
            text: (panel.measurements.error || "") + "\n" + (panel.measurements.errorCode || "")
            textFormat: Text.PlainText
            color: panel.theme.error
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        Label {
            objectName: panel.objectPrefix + "MeasurementsPolicy"
            visible: !!panel.measurements.summary
            text: panel.measurements.summary || ""
            textFormat: Text.PlainText
            color: panel.theme.accent
            Layout.fillWidth: true
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Label {
            objectName: panel.objectPrefix + "MeasurementsGate"
            visible: !!panel.measurements.notice
            text: panel.measurements.notice || ""
            textFormat: Text.PlainText
            color: panel.theme.muted
            Layout.fillWidth: true
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Label {
            visible: !panel.measurements.loading && !panel.measurements.error && !!panel.measurements.result
            text: "PALETTE · APPROXIMATE OPACITY-WEIGHTED SHARES"
            color: panel.theme.accent
            Layout.fillWidth: true
            font.pixelSize: 11
            font.letterSpacing: 1
            wrapMode: Text.Wrap
        }
        Label {
            visible: !!panel.measurements.result && (panel.measurements.palette || []).length === 0
            text: "No contributing palette colors."
            color: panel.theme.muted
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        Repeater {
            model: panel.measurements.palette || []
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 12
                Rectangle {
                    implicitWidth: 30
                    implicitHeight: 30
                    color: modelData.hex
                    border.color: panel.theme.border
                }
                Label {
                    Layout.fillWidth: true
                    text: modelData.hex
                    color: panel.theme.foreground
                    font.pixelSize: 13
                }
                Label {
                    text: (modelData.fraction * 100).toFixed(2) + "%"
                    color: panel.theme.muted
                    font.pixelSize: 12
                }
            }
        }
        Repeater {
            model: panel.measurements.groups || []
            ColumnLayout {
                id: group
                required property var modelData
                Layout.fillWidth: true
                spacing: 12
                Label {
                    Layout.fillWidth: true
                    text: group.modelData.title
                    color: panel.theme.accent
                    font.pixelSize: 11
                    font.letterSpacing: 1.5
                    wrapMode: Text.Wrap
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
                Repeater {
                    model: group.modelData.rows
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            Layout.fillWidth: true
                            text: modelData.label
                            textFormat: Text.PlainText
                            color: panel.theme.muted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: modelData.value
                            textFormat: Text.PlainText
                            color: panel.theme.foreground
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
