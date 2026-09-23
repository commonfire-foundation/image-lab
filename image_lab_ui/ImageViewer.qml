import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: viewer
    required property var backend
    required property var theme
    property int imageId: -1
    property var record: ({})
    property bool gifPaused: false
    width: parent.width
    height: parent.height
    padding: 0
    margins: 0
    modal: true
    focus: true
    closePolicy: backend.editorActive ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: Rectangle { color: viewer.theme.background }

    function openImage(id) {
        if (backend.editorActive) return
        var details = backend.imageDetails(id)
        if (!details.imageId) return
        imageId = id
        record = details
        backend.inspectImageFile(id)
        infoTabs.currentIndex = 0
        fileInfo.contentItem.contentY = 0
        gifPaused = !backend.settings.autoplayViewerGifs
        detailsScroll.contentItem.contentY = 0
        open()
    }
    onClosed: {
        backend.inspectImageFile(-1)
        imageId = -1
        record = ({})
        gifPaused = false
    }
    Connections {
        target: viewer.backend
        function onChanged() {
            if (viewer.visible) {
                var details = viewer.backend.imageDetails(viewer.imageId)
                if (details.path !== viewer.record.path || details.fileRevision !== viewer.record.fileRevision) {
                    viewer.backend.inspectImageFile(viewer.imageId)
                    if (infoTabs.currentIndex === 2) viewer.backend.inspectImageMeasurements(viewer.imageId)
                }
                viewer.record = details
            }
        }
        function onSettingsChanged() {
            if (viewer.visible) viewer.gifPaused = !viewer.backend.settings.autoplayViewerGifs
        }
    }

    Connections {
        target: viewer.backend.editor
        function onClosed() {
            if (viewer.visible) {
                viewer.backend.inspectImageFile(viewer.imageId)
                if (infoTabs.currentIndex === 2) viewer.backend.inspectImageMeasurements(viewer.imageId)
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 18
            spacing: 18
            Button {
                objectName: "closeImageViewer"
                text: "Back to library"
                implicitHeight: 40
                onClicked: viewer.close()
                ToolTip.text: "Back to library · Esc"
                ToolTip.visible: hovered
            }
            Button {
                objectName: "openGeometryEditor"
                text: "Edit image"
                enabled: viewer.backend.canOpenEditor && !viewer.record.isGif
                onClicked: viewer.backend.openEditor(viewer.imageId)
                ToolTip.text: viewer.record.isGif ? "Animated images are read-only" : viewer.backend.editorBlockedReason || "Crop, rotate, resize and export a separate copy"
                ToolTip.visible: hovered
            }
            Button {
                objectName: "toggleGifPlayback"
                visible: !!viewer.record.isGif
                enabled: animatedImage.frameCount > 1
                text: viewer.gifPaused ? "Play GIF" : "Pause GIF"
                onClicked: viewer.gifPaused = !viewer.gifPaused
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    objectName: "viewerFilename"
                    Layout.fillWidth: true
                    text: viewer.record.name || "Image unavailable"
                    textFormat: Text.PlainText
                    color: viewer.theme.foreground
                    font.pixelSize: 19; font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }
                Label {
                    text: (viewer.record.dimensions || "") + " · Fit to window"
                    color: viewer.theme.muted; font.pixelSize: 12
                }
            }
        }
        Label {
            objectName: "viewerEditorBlockedReason"
            Layout.fillWidth: true
            Layout.leftMargin: 18; Layout.rightMargin: 18; Layout.bottomMargin: 10
            visible: !!text && !viewer.backend.editorActive
            text: viewer.record.isGif ? "Animated images are read-only; editing is unavailable." : viewer.backend.editorBlockedReason
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: viewer.theme.muted
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: viewer.theme.border }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 0
            Rectangle {
                id: stage
                objectName: "viewerStage"
                Layout.fillWidth: true; Layout.fillHeight: true
                color: viewer.theme.preview
                Image {
                    id: largeImage
                    objectName: "viewerImage"
                    anchors.fill: parent
                    anchors.margins: 24
                    source: viewer.visible && !viewer.backend.editorActive && !viewer.record.isGif ? viewer.record.preview || "" : ""
                    sourceSize.width: 4096; sourceSize.height: 4096
                    asynchronous: true; cache: false; autoTransform: true
                    fillMode: Image.PreserveAspectFit
                    Accessible.role: Accessible.Graphic
                    Accessible.name: viewer.record.caption || viewer.record.name || "Image preview"
                }
                GifPreview {
                    id: animatedImage
                    objectName: "viewerGif"
                    anchors.fill: parent; anchors.margins: 24
                    imageSource: viewer.record.preview || ""
                    active: viewer.visible && !viewer.backend.editorActive && !!viewer.record.isGif
                    pauseRequested: viewer.gifPaused
                    pixelWidth: viewer.record.pixelWidth || 1
                    pixelHeight: viewer.record.pixelHeight || 1
                    maximumWidth: 2048; maximumHeight: 2048
                    Accessible.role: Accessible.Graphic
                    Accessible.name: viewer.record.caption || viewer.record.name || "Animated GIF"
                }
                BusyIndicator {
                    anchors.centerIn: parent
                    running: (viewer.record.isGif ? animatedImage.status : largeImage.status) === Image.Loading
                    visible: running
                }
                Label {
                    objectName: "viewerImageError"
                    anchors.centerIn: parent
                    width: Math.max(0, parent.width - 64)
                    visible: (viewer.record.isGif ? animatedImage.status : largeImage.status) === Image.Error || !viewer.record.preview
                    text: "Image unavailable\nThe original may have been moved or removed. Saved details are still shown."
                    color: viewer.theme.muted
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
            Rectangle { Layout.fillHeight: true; implicitWidth: 1; color: viewer.theme.border }
            Rectangle {
                Layout.preferredWidth: Math.min(380, viewer.width * 0.34)
                Layout.fillHeight: true
                color: viewer.theme.panel
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 18
                    TabBar {
                        id: infoTabs
                        objectName: "viewerInfoTabs"
                        Layout.fillWidth: true
                        onCurrentIndexChanged: {
                            if (viewer.imageId > 0)
                                viewer.backend.inspectImageMeasurements(currentIndex === 2 ? viewer.imageId : -1)
                        }
                        TabButton { text: "File info"; font.pixelSize: 12 }
                        TabButton { objectName: "viewerNotesTab"; text: "Library notes"; font.pixelSize: 12 }
                        TabButton { objectName: "viewerMeasurementsTab"; text: "Measures"; font.pixelSize: 12 }
                    }
                    FileMetadataPanel {
                        id: fileInfo
                        objectName: "viewerFileInfo"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: infoTabs.currentIndex === 0
                        theme: viewer.theme
                        metadata: viewer.backend.viewerMetadata.data
                        onRefreshRequested: viewer.backend.inspectImageFile(viewer.imageId)
                    }
                    MeasurementsPanel {
                        objectName: "viewerMeasurementsPanel"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: infoTabs.currentIndex === 2
                        theme: viewer.theme
                        measurements: viewer.backend.viewerMeasurements.data
                        onRefreshRequested: viewer.backend.inspectImageMeasurements(viewer.imageId)
                    }
                    ScrollView {
                    id: detailsScroll
                    objectName: "viewerDetailsScroll"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: infoTabs.currentIndex === 1
                    contentWidth: availableWidth
                    ScrollBar.vertical.policy: detailsScroll.contentHeight > detailsScroll.availableHeight ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: Math.max(0, detailsScroll.availableWidth - detailsScroll.effectiveScrollBarWidth - 6)
                        spacing: 18
                        Label {
                            text: "LIBRARY NOTES"
                            color: viewer.theme.accent
                            font.pixelSize: 11; font.letterSpacing: 1.5
                        }
                        Label {
                            Layout.fillWidth: true
                            text: viewer.record.userEdited ? "With your saved corrections"
                                  : viewer.record.analyzed ? "AI-generated · review for accuracy" : "Not analyzed yet"
                            color: viewer.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "viewerDescription"
                            Layout.fillWidth: true
                            text: viewer.record.caption || (viewer.record.analyzed ? "No description saved." : "Generate tags from the library to add a description and searchable notes.")
                            textFormat: Text.PlainText
                            color: viewer.theme.foreground
                            font.pixelSize: 18; wrapMode: Text.Wrap; lineHeight: 1.25
                        }
                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: viewer.theme.border }
                        Label {
                            text: "TAGS · " + (viewer.record.tags || []).length
                            color: viewer.theme.accent; font.pixelSize: 11; font.letterSpacing: 1
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 7
                            Repeater {
                                model: viewer.record.tags || []
                                Rectangle {
                                    required property string modelData
                                    width: Math.min(chip.implicitWidth + 20, parent.width)
                                    height: chip.implicitHeight + 12
                                    radius: 4
                                    color: viewer.theme.selection
                                    Label {
                                        id: chip
                                        width: parent.width - 20
                                        anchors.centerIn: parent
                                        text: parent.modelData; textFormat: Text.PlainText
                                        color: viewer.theme.selectionText
                                        font.pixelSize: 12; wrapMode: Text.WrapAnywhere
                                    }
                                }
                            }
                        }
                        Label {
                            visible: !(viewer.record.tags || []).length
                            text: "No tags saved."
                            color: viewer.theme.muted
                        }
                        Repeater {
                            model: [
                                { label: "MEDIUM", value: viewer.record.analyzed ? viewer.record.medium : "" },
                                { label: "MOOD", value: viewer.record.mood },
                                { label: "COMPOSITION", value: viewer.record.composition }
                            ]
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 5
                                Label { text: parent.modelData.label; color: viewer.theme.muted; font.pixelSize: 11; font.letterSpacing: 1 }
                                Label {
                                    Layout.fillWidth: true
                                    text: parent.modelData.value || "—"; textFormat: Text.PlainText
                                    color: viewer.theme.foreground; wrapMode: Text.Wrap
                                }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: viewer.theme.border }
                        Label {
                            Layout.fillWidth: true
                            text: viewer.record.analyzed
                                  ? "Writing present   " + (viewer.record.textPresent ? "Yes" : "No") + "\nWatermark present   " + (viewer.record.watermarkPresent ? "Yes" : "No")
                                  : "Writing / watermark   Not analyzed"
                            color: viewer.theme.muted; wrapMode: Text.Wrap; lineHeight: 1.5
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: !!viewer.record.error
                            text: viewer.record.error || ""; textFormat: Text.PlainText
                            color: viewer.theme.error; wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: viewer.record.path || ""; textFormat: Text.PlainText
                            color: viewer.theme.muted; font.pixelSize: 11; wrapMode: Text.WrapAnywhere
                        }
                    }
                    }
                }
            }
        }
    }
}
