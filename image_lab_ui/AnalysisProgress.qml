import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var job
    required property var theme
    readonly property bool running: job.running === true
    readonly property bool failed: !!job.name && !running && !job.success
    readonly property color accent: failed ? theme.error : theme.accent
    visible: !!job.name
    implicitHeight: content.implicitHeight + 28
    color: theme.panel
    radius: 6
    border.color: failed ? theme.error : theme.border
    Accessible.role: Accessible.Pane
    Accessible.name: (job.label || "") + ": " + (job.name || "")

    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 14
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Label {
                text: root.running ? "LOCAL ANALYZER" : root.failed ? "NEEDS ATTENTION" : "ANALYSIS COMPLETE"
                color: root.accent
                font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 0.5
                Layout.fillWidth: true
            }
            Label {
                text: Number(root.job.seconds || 0).toFixed(1) + "s"
                color: root.theme.foreground; font.family: "monospace"; font.pixelSize: 12
            }
        }
        Label {
            Layout.fillWidth: true
            text: root.job.name || ""
            color: root.theme.foreground; elide: Text.ElideMiddle; font.pixelSize: 12
        }
        ProgressBar {
            id: bar
            objectName: "analysisActivityBar"
            Layout.fillWidth: true
            implicitHeight: 6
            indeterminate: root.running
            value: root.job.success ? 1 : 0
            Accessible.name: root.job.label || "Analysis activity"
            background: Rectangle { color: root.theme.border; radius: 3 }
            contentItem: Item {
                clip: true
                Rectangle {
                    visible: !root.running
                    width: parent.width * bar.position; height: parent.height
                    color: root.accent; radius: 3
                }
                Rectangle {
                    id: pulse
                    visible: root.running
                    width: parent.width * 0.3; height: parent.height
                    color: root.accent; radius: 3
                    NumberAnimation on x {
                        from: -pulse.width
                        to: bar.availableWidth
                        duration: 1500
                        loops: Animation.Infinite
                        running: root.running && root.visible
                        easing.type: Easing.InOutSine
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: ["Image", "Model", "Tags", "Save"]
                Label {
                    required property int index
                    required property string modelData
                    Layout.fillWidth: true
                    text: (root.job.stage > index ? "✓ " : "") + modelData
                    color: root.job.stage >= index ? root.accent : root.theme.muted
                    font.pixelSize: 10
                    font.bold: root.running && root.job.stage === index
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: root.job.label || ""
            color: root.theme.foreground; font.pixelSize: 12; wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: root.running
                  ? (root.job.stage === 2 ? "Model loading can take longer on the first image. No completion estimate is available." : "Original image stays untouched.")
                  : root.failed ? "See the error below. You can try again." : "Saved locally. Review the predictions below."
            color: root.theme.muted; font.pixelSize: 10; wrapMode: Text.Wrap
        }
    }
}
