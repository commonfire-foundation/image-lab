import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

PanelDialog {
    id: root
    required property var backend
    property int revision: -1
    property var outputSize: [0, 0]
    property string error: ""
    width: Math.min(560, parent.width - 40)
    anchors.centerIn: parent
    title: "Export a copy"
    subtitle: outputSize[0] + " × " + outputSize[1] + " px · full-resolution source · sRGB"
    objectName: "exportGeometryDialog"
    function begin(path, size, token) {
        var slash = path.lastIndexOf("/")
        folder.text = path.substring(0, slash) || "/"
        var name = path.substring(slash+1), dot = name.lastIndexOf(".")
        filename.text = (dot > 0 ? name.substring(0,dot) : name) + "-edited.png"
        format.currentIndex = 0; consent.checked = false; addCopy.checked = false
        outputSize = size; revision = token; error = ""
        open(); filename.forceActiveFocus(); filename.selectAll()
    }
    FolderDialog {
        id: chooser
        title: "Choose the copy destination"
        onAccepted: folder.text = selectedFolder.toString()
    }
    contentItem: ScrollView {
        id: scroll
        implicitHeight: Math.min(form.implicitHeight, Math.max(180, root.parent.height - 236))
        contentWidth: availableWidth
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AlwaysOn
        ColumnLayout {
        id: form
        width: Math.max(0, scroll.availableWidth - scroll.effectiveScrollBarWidth - 6)
        spacing: 10
        Label { text: "Destination folder"; color: root.theme.muted }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: folder; objectName: "exportFolder"; Layout.fillWidth: true; Accessible.name: "Export destination folder"; selectByMouse: true }
            Button { text: "Browse…"; Accessible.name: "Browse export destination folders"; onClicked: chooser.open() }
        }
        Label { text: "New filename"; color: root.theme.muted }
        TextField { id: filename; objectName: "exportFilename"; Layout.fillWidth: true; Accessible.name: "New copy filename"; selectByMouse: true }
        RowLayout {
            Label { text: "Format"; color: root.theme.muted }
            ComboBox {
                id: format; objectName: "exportFormat"; model: ["PNG", "JPEG", "WEBP"]
                Accessible.name: "Export image format"
                onActivated: filename.text = filename.text.replace(/\.[^.]+$/, "") + (currentText === "JPEG" ? ".jpg" : "." + currentText.toLowerCase())
            }
            Label { text: "Quality"; visible: format.currentText !== "PNG"; color: root.theme.muted }
            SpinBox { id: quality; objectName: "exportQuality"; from: 1; to: 95; value: 90; editable: true; visible: format.currentText !== "PNG"; enabled: format.currentText !== "WEBP" || !lossless.checked; Accessible.name: "Lossy export quality, 1 to 95" }
        }
        CheckBox { id: lossless; objectName: "exportLossless"; text: "Lossless WebP"; checked: true; visible: format.currentText === "WEBP" }
        RowLayout {
            visible: format.currentText === "JPEG" && root.backend.editor.sourceMode === "RGBA"
            CheckBox { id: consent; objectName: "exportMatteConsent"; text: "Composite alpha onto"; Accessible.name: "Consent to JPEG transparency compositing" }
            TextField { id: matte; objectName: "exportMatte"; text: "#ffffff"; Layout.preferredWidth: 110; validator: RegularExpressionValidator { regularExpression: /#[0-9a-fA-F]{6}/ }
                Accessible.name: "JPEG matte color in hexadecimal" }
        }
        CheckBox { id: addCopy; objectName: "exportImport"; text: "Add the saved copy to my library" }
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.theme.muted; font.pixelSize: 12
            text: "Originals are never overwritten. EXIF, GPS and XMP are stripped. PNG/WebP preserve alpha; JPEG uses your chosen matte in encoded sRGB. Existing files and symlinked folders are refused."
        }
        Label { objectName: "exportValidationError"; Layout.fillWidth: true; visible: !!root.error; text: root.error; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.theme.error }
        }
    }
    footer: Item {
        implicitHeight: 64
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24; anchors.rightMargin: 24
            anchors.topMargin: 8; anchors.bottomMargin: 16
            Item { Layout.fillWidth: true }
            Button { text: "Cancel"; onClicked: root.close() }
            Button {
                objectName: "confirmExportCopy"; text: "Export copy"
                enabled: !!folder.text && !!filename.text && root.backend.editor.state === "ready"
                    && root.backend.editor.revision === root.revision
                    && (format.currentText !== "JPEG" || root.backend.editor.sourceMode !== "RGBA" || (consent.checked && matte.acceptableInput))
                onClicked: {
                    var accepted = root.backend.exportEditorCopy(folder.text, filename.text, format.currentText,
                        quality.value, format.currentText === "WEBP" && lossless.checked,
                        format.currentText === "JPEG" && consent.checked ? matte.text : "", addCopy.checked, root.revision)
                    if (accepted) root.close()
                    else root.error = root.backend.status
                }
            }
        }
    }
}
