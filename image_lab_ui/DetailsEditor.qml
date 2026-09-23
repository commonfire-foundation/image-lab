import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PanelDialog {
    id: editor
    required property var backend
    property int maximumHeight: 740
    property int imageId: -1
    property string revision: ""
    property string filename: ""
    property string thumbnail: ""
    property string dimensions: ""
    property string savedMedium: ""
    property string saveError: ""
    title: "Edit details"
    subtitle: "Your descriptions and labels, saved to this library—not the image file."
    closePolicy: Popup.NoAutoClose
    height: Math.min(740, maximumHeight)

    function reveal(field) {
        var view = scroll.contentItem
        var top = field.mapToItem(fields, 0, 0).y
        var bottom = top + Math.min(field.height, view.height)
        if (top < view.contentY) view.contentY = top
        else if (bottom > view.contentY + view.height) view.contentY = bottom - view.height
    }
    function save() {
        if (!backend.canEditDetails) return
        var result = backend.saveImageDetails(imageId, revision, {
            caption: description.text, tags: tags.values(), medium: medium.text,
            mood: mood.values(), composition: composition.values(),
            text_present: textPresent.checked, watermark_present: watermarkPresent.checked
        })
        if (result.ok) close()
        else saveError = result.error
    }
    onOpened: {
        var image = backend.detailsForEditing()
        imageId = image.imageId || -1
        revision = image.editRevision || ""
        filename = image.name || ""
        thumbnail = image.thumbnail || ""
        dimensions = image.dimensions || ""
        savedMedium = image.medium || ""
        description.text = image.caption || ""
        tags.load(image.tags)
        medium.text = image.medium || ""
        mood.load(image.moodEntries)
        composition.load(image.compositionEntries)
        textPresent.checked = !!image.textPresent
        watermarkPresent.checked = !!image.watermarkPresent
        saveError = ""
        tabs.currentIndex = 0
        scroll.contentItem.contentY = 0
        description.forceActiveFocus()
    }
    onClosed: thumbnail = ""
    component DetailTab: TabButton {
        id: tab
        implicitHeight: 40
        contentItem: Label {
            text: tab.text; textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            color: tab.checked ? editor.theme.selectionText : editor.theme.muted
            font.bold: tab.checked
        }
        background: Rectangle {
            radius: 6; color: tab.checked ? editor.theme.selection : editor.theme.background
            border.color: tab.activeFocus ? editor.theme.accent : "transparent"
        }
    }
    Shortcut { sequence: "Ctrl+Return"; enabled: editor.visible; onActivated: editor.save() }

    contentItem: RowLayout {
        spacing: 24
        Rectangle {
            Layout.preferredWidth: 184
            Layout.fillHeight: true
            visible: editor.width >= 760
            color: editor.theme.background
            radius: 8
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 12
                spacing: 12
                Image {
                    objectName: "detailsReferenceImage"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Layout.minimumHeight: 80
                    source: editor.visible ? editor.thumbnail : ""
                    sourceSize.width: 360; sourceSize.height: 480
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    Accessible.name: "Reference thumbnail for " + editor.filename
                    Label {
                        anchors.centerIn: parent
                        visible: parent.status === Image.Error || parent.status === Image.Null
                        text: "Preview unavailable"; color: editor.theme.muted; font.pixelSize: 12
                    }
                }
                Label { Layout.fillWidth: true; text: editor.filename; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; color: editor.theme.foreground; font.pixelSize: 13; font.bold: true }
                Label { text: editor.dimensions + " px"; color: editor.theme.muted; font.pixelSize: 12 }
                Label { Layout.fillWidth: true; text: editor.savedMedium; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: editor.theme.muted; font.pixelSize: 12 }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: editor.theme.border }
                Label { Layout.fillWidth: true; text: "Corrections stay yours, even when you regenerate tags."; wrapMode: Text.Wrap; color: editor.theme.muted; font.pixelSize: 12; lineHeight: 1.2 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 14
            Label {
                visible: editor.width < 760
                Layout.fillWidth: true
                text: editor.filename; textFormat: Text.PlainText; elide: Text.ElideMiddle
                color: editor.theme.muted; font.pixelSize: 12
            }
            TabBar {
                id: tabs; objectName: "detailsTabs"
                Layout.fillWidth: true
                onCurrentIndexChanged: scroll.contentItem.contentY = 0
                DetailTab { text: "Description & tags" }
                DetailTab { text: "Mood & details" }
            }
            ScrollView {
                id: scroll
                objectName: "detailsEditorScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                ColumnLayout {
                    id: fields
                    width: Math.max(0, scroll.availableWidth - scroll.effectiveScrollBarWidth - 8)
                    spacing: 18
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: tabs.currentIndex === 0
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Description"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Label { text: "In your own words"; color: editor.theme.muted; font.pixelSize: 12 }
                        }
                        TextArea {
                            id: description; objectName: "editDescription"
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            implicitHeight: Math.max(editor.height < 650 ? 92 : 156, contentHeight + topPadding + bottomPadding)
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap; selectByMouse: true
                            padding: 14
                            font.pixelSize: 15
                            color: editor.theme.foreground; placeholderTextColor: editor.theme.muted
                            placeholderText: "What stands out in this image?"
                            Accessible.name: "Description"
                            onActiveFocusChanged: if (activeFocus) editor.reveal(this)
                            Keys.onTabPressed: tags.focusInput()
                            Keys.onBacktabPressed: tabs.forceActiveFocus(Qt.BacktabFocusReason)
                            background: Rectangle { color: editor.theme.background; radius: 6; border.color: description.activeFocus ? editor.theme.accent : editor.theme.border; border.width: description.activeFocus ? 2 : 1 }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Tags"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                            Label { text: tags.entries.length; color: editor.theme.muted; font.pixelSize: 12 }
                            Item { Layout.fillWidth: true }
                        }
                        DetailTokens {
                            id: tags; objectName: "editTags"
                            Layout.fillWidth: true; theme: editor.theme
                            onFocusRequested: field => editor.reveal(field)
                            onSaveRequested: editor.save()
                        }
                        Label { Layout.fillWidth: true; text: "Enter or comma to add · Paste lists · No duplicates"; wrapMode: Text.Wrap; color: editor.theme.muted; font.pixelSize: 12 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: tabs.currentIndex === 1
                        spacing: 10
                        Label { text: "Medium"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                        TextField {
                            id: medium; objectName: "editMedium"
                            Layout.fillWidth: true; selectByMouse: true
                            placeholderText: "Photography, illustration, pixel art…"
                            Accessible.name: "Medium"
                            onActiveFocusChanged: if (activeFocus) editor.reveal(this)
                        }
                        Label { Layout.topMargin: 8; text: "Mood"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                        DetailTokens {
                            id: mood; objectName: "editMood"
                            Layout.fillWidth: true; theme: editor.theme
                            fieldName: "Mood"; placeholderText: "Calm, dramatic, playful…"
                            onFocusRequested: field => editor.reveal(field)
                            onSaveRequested: editor.save()
                        }
                        Label { Layout.topMargin: 8; text: "Composition"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                        DetailTokens {
                            id: composition; objectName: "editComposition"
                            Layout.fillWidth: true; theme: editor.theme
                            fieldName: "Composition"; placeholderText: "Centered, wide view, negative space…"
                            onFocusRequested: field => editor.reveal(field)
                            onSaveRequested: editor.save()
                        }
                        Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; implicitHeight: 1; color: editor.theme.border }
                        Label { text: "Visible in the image"; color: editor.theme.foreground; font.pixelSize: 15; font.bold: true }
                        CheckBox {
                            id: textPresent; objectName: "editTextPresent"; text: "Writing or lettering"
                            onActiveFocusChanged: if (activeFocus) editor.reveal(this)
                        }
                        CheckBox {
                            id: watermarkPresent; objectName: "editWatermarkPresent"; text: "A watermark"
                            onActiveFocusChanged: if (activeFocus) editor.reveal(this)
                        }
                    }
                }
            }
        }
    }
    footer: ColumnLayout {
        spacing: 0
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: editor.theme.border }
        Label {
            objectName: "detailsSaveError"
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.topMargin: 12
            visible: !!editor.saveError
            text: editor.saveError; textFormat: Text.PlainText
            color: editor.theme.error; wrapMode: Text.Wrap
            Accessible.name: text
        }
        RowLayout {
            Layout.fillWidth: true; Layout.margins: 20
            spacing: 10
            Label { Layout.fillWidth: true; text: "Original file stays untouched"; color: editor.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
            Button { objectName: "cancelImageDetails"; text: "Cancel"; onClicked: editor.close() }
            Button {
                id: saveButton; objectName: "saveImageDetails"
                text: "Save changes"
                enabled: editor.backend.canEditDetails
                onClicked: editor.save()
                contentItem: Label { text: saveButton.text; color: saveButton.enabled ? editor.theme.accentText : editor.theme.disabled; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.bold: true }
                background: Rectangle { radius: 6; color: saveButton.enabled ? editor.theme.accent : editor.theme.button; opacity: saveButton.down ? 0.8 : 1; border.width: saveButton.activeFocus ? 2 : 0; border.color: editor.theme.foreground }
                ToolTip.visible: hovered
                ToolTip.text: "Save changes · Ctrl+Enter"
            }
        }
    }
}
