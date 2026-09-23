import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Drawer {
    id: root
    required property var backend
    required property var theme
    signal clearRequested()
    edge: Qt.BottomEdge
    modal: false
    dim: false
    background: Rectangle { color: root.theme.panel; border.color: root.theme.border }
    function stateLabel(state) {
        return ({running: "Analyzing", queued: "Queued", succeeded: "Complete", failed: "Failed", canceled: "Removed"})[state] || state
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Label { text: "ANALYSIS QUEUE"; color: root.theme.accent; font.family: "monospace"; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            Button {
                text: "Clear waiting"
                enabled: !root.backend.submitting && root.backend.batch.queued > 0
                onClicked: root.clearRequested()
            }
            Button { text: "Close"; onClicked: root.close() }
        }
        Label {
            Layout.fillWidth: true
            text: "One image at a time. Keep browsing or add more images while analysis runs."
            color: root.theme.muted; wrapMode: Text.Wrap; font.pixelSize: 12
        }
        ListView {
            id: jobs
            objectName: "queueJobs"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 4
            model: root.backend.queueEntries
            ScrollBar.vertical: ScrollBar {}
            Label { anchors.centerIn: parent; visible: jobs.count === 0; text: "Generate tags on an image to start."; color: root.theme.muted }
            delegate: Rectangle {
                id: entry
                required property var modelData
                readonly property color ink: modelData.state === "running" ? root.theme.selectionText : root.theme.foreground
                readonly property color muted: modelData.state === "running" ? root.theme.selectionText : root.theme.muted
                width: jobs.width; height: 68
                color: modelData.state === "running" ? root.theme.selection : root.theme.background
                RowLayout {
                    anchors.fill: parent; anchors.margins: 10; spacing: 12
                    Label {
                        Layout.preferredWidth: 78
                        text: root.stateLabel(modelData.state)
                        color: modelData.state === "failed" ? root.theme.error : modelData.state === "running" ? entry.ink : root.theme.accent
                        font.pixelSize: 12
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        Label { Layout.fillWidth: true; text: modelData.path.split('/').pop(); elide: Text.ElideMiddle; color: entry.ink; font.pixelSize: 12 }
                        Label {
                            Layout.fillWidth: true
                            text: modelData.error || modelData.path
                            elide: Text.ElideMiddle; color: entry.muted; font.pixelSize: 10
                            ToolTip.text: text
                            ToolTip.visible: hover.hovered
                            HoverHandler { id: hover }
                        }
                    }
                    Button { text: "View image"; onClicked: { root.backend.select(modelData.image_id); root.close() } }
                    Button {
                        text: modelData.state === "failed" ? "Retry" : "Remove"
                        visible: modelData.state === "queued" || modelData.state === "failed"
                        enabled: root.backend.canQueue && (modelData.state === "queued" || !!modelData.retryable)
                        onClicked: modelData.state === "queued" ? root.backend.removeQueued(modelData.id) : root.backend.retryJob(modelData.id)
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Running and waiting first · recent history below"; color: root.theme.muted; font.pixelSize: 11; Layout.fillWidth: true }
            Button { text: "Previous"; enabled: root.backend.queuePage > 0; onClicked: root.backend.showQueuePage(root.backend.queuePage - 1) }
            Label { text: (root.backend.queuePage + 1) + " / " + root.backend.queuePages; color: root.theme.muted }
            Button { text: "Next"; enabled: root.backend.queuePage + 1 < root.backend.queuePages; onClicked: root.backend.showQueuePage(root.backend.queuePage + 1) }
        }
    }
}
