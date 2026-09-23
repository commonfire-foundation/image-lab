import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

FocusScope {
    id: root
    required property var theme
    property string text: ""
    property string fieldName: "Tags"
    property string placeholderText: "Add a tag…"
    readonly property var entries: normalize(text.split("\n"))
    signal focusRequested(var field)
    signal saveRequested()
    implicitHeight: layout.implicitHeight
    onActiveFocusChanged: if (activeFocus && !input.activeFocus) input.forceActiveFocus()

    function normalize(items) {
        var result = [], seen = {}
        for (var i = 0; i < items.length; ++i) {
            var value = items[i].trim().replace(/\s+/g, " ")
            var key = value.toLowerCase()
            if (value && !Object.prototype.hasOwnProperty.call(seen, key)) {
                Object.defineProperty(seen, key, {value: true, enumerable: true})
                result.push(value)
            }
        }
        return result
    }
    function values() { return normalize(entries.concat(input.text.split(/[,\n]/))) }
    function commit() {
        text = values().join("\n")
        input.text = ""
    }
    function load(items) {
        input.text = ""
        text = (items || []).join("\n")
    }
    function focusInput() { input.forceActiveFocus(Qt.TabFocusReason) }
    function remove(index) {
        var items = entries.slice()
        items.splice(index, 1)
        text = items.join("\n")
        input.forceActiveFocus()
    }

    ColumnLayout {
        id: layout
        width: parent.width
        spacing: 10
        Flow {
            Layout.fillWidth: true
            spacing: 6
            visible: root.entries.length > 0
            Repeater {
                model: root.entries
                delegate: Rectangle {
                    id: chip
                    required property string modelData
                    required property int index
                    width: Math.min(chipText.implicitWidth + 48, parent.width)
                    height: 32
                    radius: 6
                    color: root.theme.selection
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 10
                        spacing: 2
                        Label {
                            id: chipText
                            Layout.fillWidth: true
                            text: chip.modelData; textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.theme.selectionText; font.pixelSize: 13
                        }
                        ToolButton {
                            objectName: root.objectName + "Remove" + chip.index
                            Layout.preferredWidth: 30; Layout.fillHeight: true
                            text: "×"
                            Accessible.name: "Remove " + chip.modelData + " from " + root.fieldName.toLowerCase()
                            onClicked: root.remove(chip.index)
                            contentItem: Label { text: "×"; color: root.theme.selectionText; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 18 }
                            background: Rectangle { color: parent.hovered || parent.activeFocus ? root.theme.button : "transparent"; radius: 5; border.color: parent.activeFocus ? root.theme.accent : "transparent" }
                            ToolTip.visible: hovered
                            ToolTip.text: "Remove " + chip.modelData
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            TextArea {
                id: input
                objectName: root.objectName + "Input"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                implicitHeight: Math.max(40, contentHeight + topPadding + bottomPadding)
                focus: true
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.Wrap
                clip: true
                selectByMouse: true
                topPadding: 10; bottomPadding: 10; leftPadding: 12; rightPadding: 12
                color: root.theme.foreground; placeholderTextColor: root.theme.muted
                placeholderText: root.placeholderText
                Accessible.name: root.fieldName + ", enter or comma to add"
                onTextChanged: if (text.indexOf(",") !== -1 || text.indexOf("\n") !== -1) root.commit()
                onActiveFocusChanged: if (activeFocus) root.focusRequested(root)
                Keys.onReturnPressed: event => { if (event.modifiers & Qt.ControlModifier) root.saveRequested(); else root.commit() }
                Keys.onEnterPressed: event => { if (event.modifiers & Qt.ControlModifier) root.saveRequested(); else root.commit() }
                Keys.onTabPressed: { root.commit(); nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason) }
                Keys.onBacktabPressed: { root.commit(); nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason) }
                background: Rectangle { color: root.theme.background; radius: 6; border.color: input.activeFocus ? root.theme.accent : root.theme.border; border.width: input.activeFocus ? 2 : 1 }
            }
            Button {
                text: "Add"
                Accessible.name: "Add to " + root.fieldName.toLowerCase()
                enabled: input.text.trim().length > 0
                onClicked: { root.commit(); root.focusInput() }
            }
        }
    }
}
