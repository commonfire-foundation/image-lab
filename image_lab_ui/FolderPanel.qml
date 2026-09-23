import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Qt.labs.folderlistmodel

PanelDialog {
    id: panel
    required property var backend
    property string locationError: ""
    property string currentPath: ""
    title: "Choose a folder"
    subtitle: "Add images to your library, without moving a single file."
    function navigate(location) {
        var result = backend.resolveFolder(location.toString())
        if (!result.ok) { locationError = result.error; return false }
        locationError = ""
        folders.folder = result.url
        currentPath = result.path
        pathField.text = result.path
        folderList.currentIndex = -1
        return true
    }
    onOpened: {
        navigate(currentPath || StandardPaths.writableLocation(StandardPaths.PicturesLocation) || StandardPaths.writableLocation(StandardPaths.HomeLocation))
    }
    FolderListModel {
        id: folders
        showFiles: false
        showDotAndDotDot: false
        showHidden: hiddenFolders.checked
        showOnlyReadable: true
        sortField: FolderListModel.Name
        sortCaseSensitive: false
    }
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            PanelButton {
                theme: panel.theme; text: "Home"
                onClicked: panel.navigate(StandardPaths.writableLocation(StandardPaths.HomeLocation))
            }
            PanelButton {
                theme: panel.theme; text: "Pictures"
                onClicked: panel.navigate(StandardPaths.writableLocation(StandardPaths.PicturesLocation))
            }
            Item { Layout.fillWidth: true }
            PanelButton {
                objectName: "folderUp"
                theme: panel.theme; text: "Up"
                enabled: panel.currentPath !== "/" && panel.currentPath !== ""
                onClicked: panel.navigate(folders.parentFolder)
            }
        }
        Label { text: "Folder path"; color: panel.theme.muted; font.pixelSize: 12 }
        RowLayout {
            spacing: 8
            TextField {
                id: pathField
                objectName: "folderPath"
                Layout.fillWidth: true
                implicitHeight: 38
                color: panel.theme.foreground
                selectByMouse: true
                Accessible.name: "Folder path"
                onAccepted: panel.navigate(text)
                background: Rectangle {
                    radius: 6; color: panel.theme.background
                    border.color: pathField.activeFocus ? panel.theme.accent : panel.theme.border
                }
            }
            PanelButton { theme: panel.theme; text: "Go"; onClicked: panel.navigate(pathField.text) }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.minimumHeight: 120
            color: panel.theme.background; radius: 8; border.color: panel.theme.border
            ListView {
                id: folderList
                objectName: "folderList"
                anchors.fill: parent; anchors.margins: 6
                clip: true
                model: folders
                currentIndex: -1
                keyNavigationEnabled: true
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: folderRow
                    required property int index
                    required property string fileName
                    required property url fileUrl
                    width: folderList.width; height: 42
                    Accessible.name: fileName
                    highlighted: ListView.isCurrentItem
                    onClicked: { folderList.currentIndex = index; folderList.forceActiveFocus() }
                    onDoubleClicked: panel.navigate(fileUrl)
                    Keys.onReturnPressed: panel.navigate(fileUrl)
                    Keys.onEnterPressed: panel.navigate(fileUrl)
                    contentItem: RowLayout {
                        spacing: 12
                        Label { text: "▸"; color: panel.theme.accent; font.pixelSize: 18 }
                        Label { Layout.fillWidth: true; text: folderRow.fileName; elide: Text.ElideMiddle; color: folderRow.highlighted ? panel.theme.selectionText : panel.theme.foreground; font.pixelSize: 13 }
                        Label { text: "Folder"; color: folderRow.highlighted ? panel.theme.selectionText : panel.theme.muted; font.pixelSize: 11 }
                    }
                    background: Rectangle {
                        radius: 4
                        color: folderRow.highlighted ? panel.theme.selection : folderRow.hovered ? panel.theme.button : "transparent"
                        border.color: folderRow.visualFocus ? panel.theme.accent : "transparent"
                    }
                }
                Keys.onReturnPressed: {
                    if (currentIndex >= 0) panel.navigate(folders.get(currentIndex, "fileUrl"))
                }
                Keys.onEnterPressed: {
                    if (currentIndex >= 0) panel.navigate(folders.get(currentIndex, "fileUrl"))
                }
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Backspace && panel.currentPath !== "/") {
                        panel.navigate(folders.parentFolder)
                        event.accepted = true
                    }
                }
                Label {
                    anchors.centerIn: parent
                    width: parent.width - 24
                    horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                    visible: folders.count === 0
                    text: folders.status === FolderListModel.Loading ? "Opening folder…" : "No subfolders here\nYou can still scan this folder for images."
                    color: panel.theme.muted; font.pixelSize: 13
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            CheckBox { id: hiddenFolders; text: "Show hidden folders"; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            Label { text: "Double-click to open"; color: panel.theme.muted; font.pixelSize: 11 }
        }
        Label {
            Layout.fillWidth: true
            visible: !!panel.locationError
            text: panel.locationError
            color: panel.theme.error; wrapMode: Text.Wrap
            Accessible.name: text
        }
    }
    footer: ColumnLayout {
        spacing: 12
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.theme.border }
        RowLayout {
            Layout.fillWidth: true; Layout.margins: 24; Layout.topMargin: 4; Layout.bottomMargin: 20
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: "Includes subfolders.\nOriginals stay untouched."
                color: panel.theme.muted; font.pixelSize: 12
            }
            PanelButton { theme: panel.theme; text: "Cancel"; onClicked: panel.close() }
            PanelButton {
                objectName: "scanFolder"
                theme: panel.theme; primary: true; text: "Scan this folder"
                enabled: backend.canImport && panel.currentPath.length > 0
                onClicked: {
                    if (panel.navigate(pathField.text)) {
                        backend.importFolder(folders.folder)
                        panel.close()
                    }
                }
            }
        }
    }
}
