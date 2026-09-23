import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var batch
    required property var theme
    required property bool busy
    property bool submitting: false
    property var progress: ({})
    signal pauseRequested()
    signal resumeRequested()
    signal detailsRequested()
    implicitHeight: 100
    color: theme.panel
    Accessible.name: "Analysis queue"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 6
        RowLayout {
            Layout.fillWidth: true
            Label {
                text: "QUEUE"; color: root.theme.accent
                font.family: "monospace"; font.pixelSize: 11
            }
            Label {
                Layout.fillWidth: true
                text: root.progress.running ? "Analyzing · " + root.progress.name
                      : root.batch.currentName ? "Analyzing · " + root.batch.currentName
                      : root.submitting ? "Adding images…"
                      : root.batch.state === "paused" ? "Paused"
                      : root.batch.queued ? "Preparing next image…" : "No images waiting"
                elide: Text.ElideMiddle; color: root.theme.foreground; font.pixelSize: 12
            }
            Button {
                objectName: "pauseQueue"
                text: root.batch.state === "paused" ? "Resume" : "Pause after current"
                enabled: !root.submitting && (!!root.batch.queued || !!root.batch.running)
                onClicked: root.batch.state === "paused" ? root.resumeRequested() : root.pauseRequested()
            }
            Button { objectName: "showQueue"; text: "View queue"; onClicked: root.detailsRequested() }
        }
        ProgressBar {
            objectName: "batchProgressBar"
            Layout.fillWidth: true; implicitHeight: 4
            from: 0; to: Math.max(1, root.batch.total || 0); value: root.batch.terminal || 0
            palette.highlight: root.theme.accent
            Accessible.name: (root.batch.finished || 0) + " of " + (root.batch.total || 0) + " processed"
        }
        Label {
            Layout.fillWidth: true
            text: (root.batch.queued || 0) + " waiting · " + (root.batch.succeeded || 0) + " complete · "
                  + (root.batch.failed || 0) + " failed"
                  + (root.batch.state === "paused" && root.batch.running ? " · pausing after current" : "")
                  + (root.progress.running ? " · " + (root.progress.label || "Analyzing") + " · " + Number(root.progress.seconds || 0).toFixed(1) + "s" : "")
            elide: Text.ElideRight; color: root.theme.muted; font.pixelSize: 11
        }
    }
}
