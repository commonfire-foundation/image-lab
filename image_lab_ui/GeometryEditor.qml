import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Popup {
    id: root
    required property var backend
    required property var theme
    signal leaveCancelled()
    readonly property var session: backend.editor
    readonly property var recipe: session.recipe
    readonly property bool previewReady: previewImage.status === Image.Ready
    property string recipeKey: ""
    property bool cropDirty: false
    property bool sizeDirty: false
    property bool dragMode: false
    property int dragRevision: -1
    readonly property bool pendingFields: cropDirty || sizeDirty || (dragMode && cropOverlay.changedSelection)
    readonly property bool prepared: !!recipe.source_size
    readonly property bool editable: prepared && !dragMode && !session.exporting && session.state !== "closing" && session.state !== "error"
    readonly property bool canExport: editable && !pendingFields && previewReady && session.state === "ready" && !session.comparingOriginal && session.colorPolicy === "srgb-v1"
    readonly property string exportHint: session.exporting ? session.exportPhase
        : pendingFields ? "Apply or revert pending changes before exporting."
        : dragMode ? "Apply or cancel the crop selection before exporting."
        : session.comparingOriginal ? "Turn off original comparison to export your edits."
        : session.state === "error" ? "Resolve the preview error before exporting."
        : !canExport ? "Preparing the editing preview…"
        : "Original untouched · Export a copy to keep edits"
    readonly property bool dialogOpen: discard.visible || exportDialog.visible || measurementsDialog.visible
    width: parent.width; height: parent.height
    padding: 0; margins: 0
    modal: true; focus: true
    closePolicy: Popup.NoAutoClose
    background: Rectangle { color: root.theme.background }

    function beginDrag() {
        if (!previewReady || session.state !== "ready" || session.comparingOriginal || pendingFields) return
        cropOverlay.reset()
        dragRevision = session.revision
        dragMode = true
        cropOverlay.forceActiveFocus()
    }
    function cancelDrag() { dragMode = false; cropOverlay.reset() }
    function applyDrag() {
        var b = cropOverlay.bounds
        if (session.cropView(b[0], b[1], b[2], b[3], dragRevision)) cancelDrag()
    }
    function dimensions() {
        if (!prepared) return [0, 0]
        if (recipe.output_size) return recipe.output_size
        var w = recipe.crop[2] - recipe.crop[0], h = recipe.crop[3] - recipe.crop[1]
        return recipe.quarter_turns % 2 ? [h, w] : [w, h]
    }
    function applyCrop() {
        if (!editable || sizeDirty || !leftField.acceptableInput || !topField.acceptableInput || !rightField.acceptableInput || !bottomField.acceptableInput) return
        var bounds = [Number(leftField.text), Number(topField.text), Number(rightField.text), Number(bottomField.text)]
        if (JSON.stringify(bounds) === JSON.stringify(recipe.crop)) { syncFields(); session.refresh(); return }
        if (session.crop(bounds[0], bounds[1], bounds[2], bounds[3])) syncFields()
    }
    function applySize(horizontal) {
        if (!editable || cropDirty || !(horizontal ? widthField.acceptableInput && widthField.enabled : heightField.acceptableInput && heightField.enabled)) return
        var value = Number(horizontal ? widthField.text : heightField.text)
        if (value === dimensions()[horizontal ? 0 : 1]) {
            syncFields(); session.refresh(); return
        }
        if (horizontal ? session.resizeWidth(value) : session.resizeHeight(value)) syncFields()
    }
    function syncFields() {
        if (!prepared) return
        leftField.text = String(recipe.crop[0]); topField.text = String(recipe.crop[1])
        rightField.text = String(recipe.crop[2]); bottomField.text = String(recipe.crop[3])
        var size = dimensions()
        widthField.text = String(size[0]); heightField.text = String(size[1])
        widthField.enabled = true; heightField.enabled = true
        cropDirty = false; sizeDirty = false
    }
    function showExport() {
        if (canExport) exportDialog.begin(backend.editorRecord.path, dimensions(), session.revision)
    }
    function textInputFocused() {
        var window = root.contentItem.Window.window
        var item = window ? window.activeFocusItem : null
        return item && typeof item.selectAll === "function"
    }
    function requestLeave() {
        if (session.exporting) { backend.setStatus("Wait for export or cancel it before leaving the editor."); return }
        if (session.state === "closing") return
        exportDialog.close()
        measurementsDialog.close()
        if (session.dirty || pendingFields) {
            discard.revision = session.revision
            discard.stale = false
            discard.open()
        } else {
            backend.closeEditor(false, session.revision)
        }
    }
    Connections {
        target: root.session
        function onChanged() {
            var key = JSON.stringify(root.recipe)
            if (key !== root.recipeKey) {
                root.recipeKey = key
                root.syncFields()
            }
        }
        function onClosed() {
            discard.close()
            exportDialog.close()
            measurementsDialog.close()
            root.cancelDrag()
            root.cropDirty = false; root.sizeDirty = false; root.recipeKey = ""
            root.close()
        }
    }
    Shortcut {
        sequence: "Escape"; autoRepeat: false
        enabled: root.visible && !root.dialogOpen
        onActivated: { if (root.dragMode) root.cancelDrag(); else root.requestLeave() }
    }
    Shortcut {
        sequence: "Ctrl+Z"
        enabled: root.visible && root.editable && !root.pendingFields && !root.dialogOpen && !root.textInputFocused()
        onActivated: root.session.undo()
    }
    Shortcut {
        sequences: ["Ctrl+Shift+Z", "Ctrl+Y"]
        enabled: root.visible && root.editable && !root.pendingFields && !root.dialogOpen && !root.textInputFocused()
        onActivated: root.session.redo()
    }
    Shortcut {
        sequence: "Ctrl+Shift+S"
        enabled: root.visible && root.canExport && !root.dialogOpen
        onActivated: root.showExport()
    }
    ExportDialog { id: exportDialog; theme: root.theme; backend: root.backend }
    PanelDialog {
        id: measurementsDialog; objectName: "editorMeasurementsDialog"
        theme: root.theme; anchors.centerIn: parent
        width: Math.min(680, root.width - 48); height: root.height - 48
        title: "Original measurements"
        subtitle: "Managed sRGB · unedited source only · not statistics for your edits"
        contentItem: MeasurementsPanel {
            theme: root.theme; measurements: root.session.measurements; objectPrefix: "editor"
            refreshEnabled: root.session.state === "ready"
            onRefreshRequested: root.session.requestMeasurements()
        }
        footer: Button { text: "Close measurements"; onClicked: measurementsDialog.close() }
    }
    PanelDialog {
        id: discard
        objectName: "discardGeometryDialog"
        onRejected: root.leaveCancelled()
        theme: root.theme
        anchors.centerIn: parent
        width: Math.min(460, root.width - 48)
        property int revision: -1
        property bool stale: false
        title: "Discard this editing session?"
        subtitle: "Unexported edits and un-applied field values will be lost. Your original file is untouched. Export a copy to keep the applied recipe."
        contentItem: ColumnLayout {
            Label {
                Layout.fillWidth: true
                visible: discard.stale
                text: "The session changed. Keep editing, then close again to review the current draft."
                wrapMode: Text.Wrap; color: root.theme.error
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button { objectName: "keepGeometry"; text: "Keep editing"; focus: true; onClicked: { discard.close(); root.leaveCancelled() } }
                Button { text: "Export copy…"; enabled: root.canExport && !discard.stale; onClicked: { discard.close(); root.leaveCancelled(); root.showExport() } }
                Button {
                    objectName: "discardGeometry"
                    text: "Discard edits"; enabled: !discard.stale
                    onClicked: {
                        if (root.backend.closeEditor(true, discard.revision)) discard.close()
                        else discard.stale = true
                    }
                }
            }
        }
    }
    contentItem: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.margins: 16
            Button { objectName: "closeGeometryEditor"; text: "Back to image"; enabled: !root.session.exporting; onClicked: root.requestLeave() }
            ColumnLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: (root.backend.editorRecord.name || "Image editor") + (root.session.dirty ? " · Unsaved" : "")
                    textFormat: Text.PlainText; elide: Text.ElideMiddle
                    color: root.theme.foreground; font.pixelSize: 19; font.bold: true
                }
                Label {
                    objectName: "editorExportHint"
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: root.exportHint; color: root.theme.muted; font.pixelSize: 12
                }
            }
            Button { objectName: "openExportCopy"; text: "Export copy…"; visible: !root.session.exporting; enabled: root.canExport; onClicked: root.showExport() }
            Button { objectName: "cancelEditorExport"; text: "Cancel export"; visible: root.session.exporting; onClicked: root.session.cancelExport() }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.theme.border }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                objectName: "geometryStage"
                Layout.fillWidth: true; Layout.fillHeight: true
                color: root.theme.preview
                Image {
                    id: previewImage
                    objectName: "geometryPreview"
                    anchors.fill: parent; anchors.margins: 24
                    source: root.visible ? root.session.preview.url : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true; cache: false
                    Accessible.role: Accessible.Graphic
                    Accessible.name: root.session.errorCode === "unknown_color_space" ? "Unmanaged original reference; color confirmation required" : root.session.comparingOriginal ? "Original geometry under the selected color policy" : "Edited geometry preview"
                }
                CropOverlay {
                    id: cropOverlay
                    objectName: "cropOverlay"
                    anchors.centerIn: previewImage
                    width: previewImage.paintedWidth; height: previewImage.paintedHeight
                    accent: root.theme.accent
                    pixelWidth: root.prepared ? (root.recipe.quarter_turns % 2 ? root.recipe.crop[3]-root.recipe.crop[1] : root.recipe.crop[2]-root.recipe.crop[0]) : 1
                    pixelHeight: root.prepared ? (root.recipe.quarter_turns % 2 ? root.recipe.crop[2]-root.recipe.crop[0] : root.recipe.crop[3]-root.recipe.crop[1]) : 1
                    visible: root.dragMode && root.previewReady && root.session.revision === root.dragRevision
                    enabled: visible && root.session.state === "ready"
                }
                BusyIndicator { anchors.centerIn: parent; running: root.session.state === "opening" || root.session.state === "rendering"; visible: running }
                Rectangle {
                    objectName: "editorPreviewRecovery"
                    anchors.centerIn: parent
                    width: Math.min(420, parent.width - 48)
                    height: recoveryContent.implicitHeight + 32
                    visible: root.session.state === "error"
                    color: root.theme.panel; border.color: root.theme.border; radius: 8
                    ColumnLayout {
                        id: recoveryContent
                        anchors.fill: parent; anchors.margins: 16
                        spacing: 12
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.theme.foreground
                            font.bold: true
                            text: root.session.errorCode === "unknown_color_space" ? "Confirm the image’s color interpretation" : "The editing preview could not be prepared"
                        }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.theme.foreground
                            textFormat: Text.PlainText
                            text: root.session.errorCode === "unknown_color_space"
                                ? "This image has no color profile. The reference behind this message is unmanaged. Confirm sRGB to edit and export, or go back without changing anything."
                                : root.session.error
                        }
                        Button {
                            objectName: "confirmEditorSrgb"
                            visible: root.session.errorCode === "unknown_color_space"
                            text: "Treat this image as sRGB"
                            onClicked: root.session.set_color_policy("srgb-v1", true)
                        }
                        Button { text: "Back to image"; onClicked: root.requestLeave() }
                    }
                }
                Label {
                    anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottomMargin: 12
                    text: root.session.errorCode === "unknown_color_space" ? "Unmanaged reference · editing requires color confirmation" : root.session.comparingOriginal ? "Original geometry · current color interpretation" : "Edited preview · original file unchanged"
                    color: root.theme.muted; font.pixelSize: 12
                }
            }
            ScrollView {
                id: controls
                Layout.preferredWidth: 340; Layout.fillHeight: true
                padding: 16
                clip: true; contentWidth: availableWidth
                ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                ColumnLayout {
                    width: controls.availableWidth; spacing: 10
                    Label {
                        objectName: "editorExportResult"
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        visible: !!root.session.lastExport.path
                        text: (root.session.lastExport.published && root.session.lastExport.path_confirmed ? "Copy saved: " : "Inspect publication: ")
                            + (root.session.lastExport.path || "") + "\n"
                            + ((root.session.lastExport.warnings || []).join("\n"))
                            + (root.session.lastExport.import_error || "")
                            + (root.session.lastExport.imported ? "Added to library." : "")
                        wrapMode: Text.Wrap; textFormat: Text.PlainText; color: root.theme.foreground; font.pixelSize: 12
                    }
                    Button {
                        objectName: "retryEditorImport"; text: "Import saved copy"
                        visible: !!root.session.lastExport.published && !!root.session.lastExport.path_confirmed && !root.session.lastExport.imported
                        enabled: root.session.state === "ready" && !root.pendingFields && !root.dragMode
                        onClicked: root.session.retryImport()
                    }
                    Button {
                        objectName: "openEditorMeasurements"; text: "Original measurements…"
                        enabled: root.editable && !root.pendingFields && root.session.state === "ready" && root.session.colorPolicy === "srgb-v1"
                        onClicked: { if (root.session.requestMeasurements()) measurementsDialog.open() }
                    }
                    Label { Layout.topMargin: 16; text: "COLOR INTERPRETATION"; color: root.theme.muted; font.pixelSize: 11 }
                    Label {
                        objectName: "editorSourceColor"
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        text: "Source: " + root.session.sourceColorDescription
                            + "\nWorking: " + (root.session.colorPolicy === "srgb-v1" ? "sRGB" : "unmanaged")
                        textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.theme.muted
                    }
                    Label {
                        objectName: "editorAssumedSrgbNotice"
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        visible: root.session.canAssumeSrgb && root.session.assumeSrgb
                        text: "Using sRGB by convention for this untagged image. Original unchanged; exported copies are tagged sRGB."
                        textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.theme.foreground
                    }
                    CheckBox {
                        objectName: "assumeEditorSrgb"
                        text: "Use sRGB for this untagged image"
                        visible: root.session.canAssumeSrgb
                        checked: root.session.assumeSrgb
                        enabled: root.prepared && !root.session.exporting && !root.dragMode && !root.pendingFields && root.session.state !== "closing"
                        onToggled: root.session.set_color_policy("srgb-v1", checked)
                    }
                    Label {
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        text: root.session.error
                        visible: text.length > 0; wrapMode: Text.Wrap
                        textFormat: Text.PlainText; color: root.theme.error
                    }
                    Button {
                        objectName: "beginDragCrop"; text: "Drag crop"
                        visible: !root.dragMode
                        enabled: root.editable && !root.pendingFields && root.previewReady && root.session.state === "ready" && !root.session.comparingOriginal
                        onClicked: root.beginDrag()
                    }
                    RowLayout {
                        visible: root.dragMode
                        Button {
                            objectName: "applyDragCrop"; text: "Apply drag crop"
                            enabled: cropOverlay.changedSelection && !cropOverlay.dragging && root.previewReady && root.session.state === "ready" && root.session.revision === root.dragRevision
                            onClicked: root.applyDrag()
                        }
                        Button { objectName: "cancelDragCrop"; text: "Cancel crop"; onClicked: root.cancelDrag() }
                    }
                    Label {
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        visible: root.dragMode
                        text: root.session.revision !== root.dragRevision ? "Preview changed. Cancel crop and start again." : "Drag to select; move inside or resize corners. Arrow keys move by one source pixel (Shift: ten). Escape cancels. Apply makes one undo step and clears resize."
                        wrapMode: Text.Wrap; color: root.theme.muted; font.pixelSize: 12
                    }
                    Label { text: "CROP · ORIENTED ORIGINAL PIXELS"; color: root.theme.muted; font.pixelSize: 11 }
                    Label {
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        text: "Zero-based bounds; right and bottom are exclusive. Applied before rotation."
                        wrapMode: Text.Wrap; color: root.theme.muted; font.pixelSize: 12
                    }
                    GridLayout {
                        columns: 2; Layout.fillWidth: true; Layout.rightMargin: 16
                        enabled: root.editable && !root.sizeDirty
                        Label { text: "Left"; color: root.theme.foreground }
                        TextField {
                            id: leftField; objectName: "cropLeft"; Layout.fillWidth: true; Accessible.name: "Crop left"
                            onAccepted: root.applyCrop()
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: root.cropDirty = true
                        }
                        Label { text: "Top"; color: root.theme.foreground }
                        TextField {
                            id: topField; objectName: "cropTop"; Layout.fillWidth: true; Accessible.name: "Crop top"
                            onAccepted: root.applyCrop()
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: root.cropDirty = true
                        }
                        Label { text: "Right"; color: root.theme.foreground }
                        TextField {
                            id: rightField; objectName: "cropRight"; Layout.fillWidth: true; Accessible.name: "Crop right"
                            onAccepted: root.applyCrop()
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: root.cropDirty = true
                        }
                        Label { text: "Bottom"; color: root.theme.foreground }
                        TextField {
                            id: bottomField; objectName: "cropBottom"; Layout.fillWidth: true; Accessible.name: "Crop bottom"
                            onAccepted: root.applyCrop()
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: root.cropDirty = true
                        }
                    }
                    Button {
                        objectName: "applyGeometryCrop"; text: "Apply crop"
                        enabled: root.editable && !root.sizeDirty && leftField.acceptableInput && topField.acceptableInput && rightField.acceptableInput && bottomField.acceptableInput
                        onClicked: root.applyCrop()
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.rightMargin: 16
                        enabled: root.editable && !root.pendingFields
                        ComboBox {
                            id: cropPreset; objectName: "geometryCropPreset"
                            Layout.fillWidth: true
                            Accessible.name: "Crop aspect ratio preset"
                            model: ["Original ratio", "Square · 1:1", "4:3", "3:2", "16:9", "9:16", "21:9"]
                        }
                        Button {
                            objectName: "applyGeometryPreset"; text: "Apply ratio"
                            onClicked: {
                                var ratios = [root.recipe.source_size, [1, 1], [4, 3], [3, 2], [16, 9], [9, 16], [21, 9]]
                                var ratio = ratios[cropPreset.currentIndex]
                                root.session.aspect(ratio[0], ratio[1])
                            }
                        }
                    }
                    Label { text: "ORIENTATION"; color: root.theme.muted; font.pixelSize: 11 }
                    RowLayout {
                        enabled: root.editable && !root.pendingFields
                        Button { objectName: "rotateGeometry"; text: "Rotate 90°"; onClicked: root.session.rotate(1) }
                        Button { Layout.minimumWidth: 0; Layout.preferredWidth: 70; text: "Flip H"; Accessible.name: "Flip horizontally"; onClicked: root.session.flip(true, false) }
                        Button { Layout.minimumWidth: 0; Layout.preferredWidth: 70; text: "Flip V"; Accessible.name: "Flip vertically"; onClicked: root.session.flip(false, true) }
                    }
                    Label { text: "SIZE · ASPECT LOCKED"; color: root.theme.muted; font.pixelSize: 11 }
                    Label {
                        objectName: "editorOutputDimensions"
                        text: root.prepared ? "Output: " + root.dimensions()[0] + " × " + root.dimensions()[1] + " px" : "Preparing dimensions…"
                        color: root.theme.foreground
                    }
                    GridLayout {
                        columns: 2; Layout.fillWidth: true; Layout.rightMargin: 16
                        enabled: root.editable && !root.cropDirty
                        TextField {
                            id: widthField; objectName: "geometryWidth"; Layout.fillWidth: true; Accessible.name: "Output width"
                            onAccepted: root.applySize(true)
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: { root.sizeDirty = true; heightField.enabled = false }
                        }
                        Button { objectName: "applyGeometryWidth"; text: "Set width"; enabled: widthField.acceptableInput && widthField.enabled; onClicked: root.applySize(true) }
                        TextField {
                            id: heightField; objectName: "geometryHeight"; Layout.fillWidth: true; Accessible.name: "Output height"
                            onAccepted: root.applySize(false)
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,8}$/ }
                            onTextEdited: { root.sizeDirty = true; widthField.enabled = false }
                        }
                        Button { objectName: "applyGeometryHeight"; text: "Set height"; enabled: heightField.acceptableInput && heightField.enabled; onClicked: root.applySize(false) }
                    }
                    CheckBox { text: "Allow upscaling"; checked: root.prepared && !!root.recipe.allow_upscale; enabled: root.editable && !root.pendingFields; onToggled: root.session.allowUpscale(checked) }
                    Button { objectName: "revertGeometryFields"; text: "Revert fields"; visible: root.cropDirty || root.sizeDirty; onClicked: { root.syncFields(); root.session.refresh() } }
                    RowLayout {
                        enabled: root.editable && !root.pendingFields
                        Button { objectName: "undoGeometry"; text: "Undo"; enabled: root.session.canUndo; onClicked: root.session.undo() }
                        Button { text: "Redo"; enabled: root.session.canRedo; onClicked: root.session.redo() }
                    }
                    Button { text: "Reset geometry"; enabled: root.editable && !root.pendingFields; onClicked: root.session.reset() }
                    CheckBox { text: "Compare original geometry"; checked: root.session.comparingOriginal; enabled: root.editable && !root.pendingFields; onToggled: root.session.compareOriginal(checked) }
                    Button { text: "Retry preview"; enabled: root.prepared && !root.dragMode && !root.pendingFields && !root.session.busy && root.session.state !== "closing"; onClicked: root.session.refresh() }
                    Label { Layout.fillWidth: true; Layout.rightMargin: 16; Layout.bottomMargin: 16; text: "Drag crop trims the current preview. Numeric bounds or Reset can expand it again. Original measurements are not edited-image statistics. Export writes a separate full-resolution copy."; wrapMode: Text.Wrap; color: root.theme.muted; font.pixelSize: 12 }
                }
            }
        }
    }
}
