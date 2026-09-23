import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280; height: 820
    minimumWidth: 900; minimumHeight: 600
    visible: true
    title: "Image Lab — image library"
    readonly property var theme: controller.themeColors
    color: theme.background
    font.family: "Noto Sans"
    font.pixelSize: 14
    readonly property color ink: theme.foreground
    readonly property color muted: theme.muted
    readonly property color accent: theme.accent
    readonly property color panel: theme.panel
    readonly property color line: theme.border
    property var item: controller.selected
    property bool quitRequested: false
    property bool quitWaiting: false
    function cancelQuit() {
        quitRequested = false; quitWaiting = false
        controller.cancelWindowClose()
        quitWork.close()
    }
    function requestQuit() {
        quitRequested = true
        if (controller.canClose) { window.close(); return }
        if (controller.editorActive && !controller.editor.exporting) geometryEditor.requestLeave()
        else quitWork.open()
    }
    function continueQuit() {
        if (!quitRequested) return
        if (controller.canClose) { quitWork.close(); window.close() }
        else if (quitWaiting && !controller.busy && !controller.editor.exporting) {
            quitWaiting = false
            quitWork.close()
            requestQuit()
        }
    }
    palette.window: color
    palette.windowText: ink
    palette.text: ink
    palette.base: theme.background
    palette.alternateBase: panel
    palette.button: theme.button
    palette.buttonText: ink
    palette.placeholderText: muted
    palette.toolTipBase: panel
    palette.toolTipText: ink
    palette.light: theme.button
    palette.midlight: panel
    palette.mid: line
    palette.dark: theme.preview
    palette.shadow: theme.preview
    palette.brightText: theme.error
    palette.link: accent
    palette.linkVisited: accent
    palette.disabled.buttonText: theme.disabled
    palette.disabled.text: theme.disabled
    palette.disabled.windowText: theme.disabled
    palette.highlight: theme.selection
    palette.highlightedText: theme.selectionText
    function reportControlState() {
        controller.reportUiState({visible: window.visible, active: window.active,
            viewerId: imageViewer.visible ? imageViewer.imageId : null,
            gifPaused: imageViewer.gifPaused,
            panels: {queue: queuePanel.visible, settings: settingsPanel.visible,
                     details: detailsEditor.visible, about: aboutDialog.visible}})
    }
    Component.onCompleted: reportControlState()
    onVisibleChanged: reportControlState()
    onActiveChanged: reportControlState()
    Connections {
        target: controller
        function onChanged() {
            if (controller.editorActive && !geometryEditor.visible) geometryEditor.open()
            if (window.quitRequested) Qt.callLater(window.continueQuit)
        }
        function onUiAction(action, id) {
            if (controller.editorActive && ["editor.close", "window.show", "window.focus", "window.close"].indexOf(action) === -1) return
            switch (action) {
            case "editor.close": geometryEditor.requestLeave(); break
            case "window.show": window.show(); break
            case "window.hide": window.hide(); break
            case "window.focus": window.show(); window.requestActivate(); break
            case "window.close": window.close(); break
            case "viewer.open": imageViewer.openImage(id); break
            case "viewer.close": imageViewer.close(); break
            case "viewer.play": imageViewer.gifPaused = false; break
            case "viewer.pause": imageViewer.gifPaused = true; break
            case "queue.open": queuePanel.open(); break
            case "queue.close": queuePanel.close(); break
            case "settings.open": settingsPanel.open(); break
            case "settings.close": settingsPanel.close(); break
            case "details.open": detailsEditor.open(); break
            case "details.close": detailsEditor.close(); break
            case "about.open": aboutDialog.open(); break
            case "about.close": aboutDialog.close(); break
            case "view.reveal": grid.currentIndex = id; grid.positionViewAtIndex(id, GridView.Contain); break
            case "view.search": searchField.text = controller.viewQuery; searchDelay.stop(); break
            }
            window.reportControlState()
        }
    }
    Connections { target: imageViewer
        function onVisibleChanged() { window.reportControlState() }
        function onImageIdChanged() { window.reportControlState() }
        function onGifPausedChanged() { window.reportControlState() }
    }
    Connections { target: queuePanel; function onVisibleChanged() { window.reportControlState() } }
    Connections { target: settingsPanel; function onVisibleChanged() { window.reportControlState() } }
    Connections { target: detailsEditor; function onVisibleChanged() { window.reportControlState() } }
    Connections { target: aboutDialog; function onVisibleChanged() { window.reportControlState() } }

    onClosing: function(close) {
        if (!controller.canClose) {
            close.accepted = false
            window.requestQuit()
        }
    }

    GeometryEditor {
        id: geometryEditor
        objectName: "geometryEditor"
        backend: controller
        theme: window.theme
        onLeaveCancelled: window.cancelQuit()
    }
    PanelDialog {
        id: quitWork
        objectName: "quitWorkDialog"
        theme: window.theme
        anchors.centerIn: parent
        width: Math.min(500, window.width - 48)
        title: window.quitWaiting ? "Waiting to close…" : "Close Image Lab?"
        subtitle: controller.editor.exporting
            ? "An export is in progress. The window will close after it finishes and any unsaved edits are resolved."
            : controller.editorActive ? "The export has finished. Close the editor and resolve any remaining unsaved edits before quitting."
            : "Pause the queue and stop scanning, then close after the current work finishes. Waiting queue items will be kept."
        onRejected: window.cancelQuit()
        contentItem: RowLayout {
            Button { objectName: "cancelWindowQuit"; text: "Keep open"; onClicked: window.cancelQuit() }
            Button {
                objectName: "confirmWindowQuit"
                text: controller.editor.exporting ? "Wait and close" : controller.editorActive ? "Close editor and quit" : "Pause work and close"
                enabled: !window.quitWaiting
                onClicked: {
                    window.quitWaiting = true
                    controller.prepareWindowClose()
                    window.continueQuit()
                }
            }
        }
    }
    FolderPanel {
        id: folderDialog
        objectName: "folderDialog"
        anchors.centerIn: parent
        width: Math.min(680, window.width - 48)
        height: Math.min(600, window.height - 48)
        theme: window.theme
        backend: controller
    }
    AboutPanel {
        id: aboutDialog
        objectName: "aboutDialog"
        anchors.centerIn: parent
        width: Math.min(460, window.width - 48)
        theme: window.theme
    }
    PanelDialog {
        id: removeDialog
        objectName: "removeLibraryDialog"
        anchors.centerIn: parent
        width: Math.min(460, window.width - 48)
        theme: window.theme
        property var imageIds: []
        property string errorMessage: ""
        onOpened: cancelRemoval.forceActiveFocus()
        function review(ids) {
            imageIds = ids
            errorMessage = ""
            open()
        }
        title: imageIds.length === 1 ? "Remove image?" : "Remove " + imageIds.length + " images?"
        subtitle: "Original files stay on disk."
        contentItem: ColumnLayout {
            spacing: 16
            Label {
                Layout.fillWidth: true
                text: "This removes the selected images, their saved tags, edits, and analysis history from this library. Scanning their folder again will add them back without those details."
                color: window.ink
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                visible: text.length > 0
                text: removeDialog.errorMessage
                color: window.theme.error
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item { Layout.fillWidth: true }
                PanelButton {
                    id: cancelRemoval
                    objectName: "cancelLibraryRemoval"
                    theme: window.theme
                    text: "Cancel"
                    onClicked: removeDialog.close()
                }
                PanelButton {
                    objectName: "confirmLibraryRemoval"
                    theme: window.theme
                    text: "Remove from library"
                    enabled: !controller.busy && removeDialog.imageIds.length > 0
                    onClicked: {
                        var result = controller.removeImages(removeDialog.imageIds)
                        if (result.ok) {
                            if (removeDialog.imageIds.indexOf(imageViewer.imageId) !== -1) imageViewer.close()
                            removeDialog.close()
                        } else removeDialog.errorMessage = result.error
                    }
                }
            }
        }
    }
    Timer { id: searchDelay; interval: 220; onTriggered: controller.search(searchField.text) }
    ButtonGroup { id: libraryFilters; exclusive: true }
    component GalleryAction: Button {
        font.pixelSize: 12
        horizontalPadding: 8
        implicitWidth: implicitContentWidth + 16
        implicitHeight: 32
    }
    Dialog {
        id: regenerateDialog
        objectName: "regenerateDialog"
        anchors.centerIn: parent; modal: true
        title: "Replace generated tags?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { text: "Regenerate " + controller.checkedCount + " selected images.\nExisting AI results are replaced only when analysis succeeds. Your saved corrections are kept."; color: window.ink }
        onAccepted: controller.regenerateSelected()
    }
    Dialog {
        id: stopBatchDialog
        objectName: "clearQueueDialog"
        anchors.centerIn: parent; modal: true
        title: "Clear waiting images?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { text: "The current image will finish. Queued images will be canceled.\nCompleted results are kept."; color: window.ink }
        onAccepted: controller.stopBatch()
    }

    Dialog {
        id: namingDialog
        objectName: "namingDialog"
        anchors.centerIn: parent
        width: Math.min(560, window.width - 48)
        modal: true
        title: "Name this image"
        footer: DialogButtonBox {
            onRejected: namingDialog.close()
            Button {
                objectName: "renameSuggestedFile"
                text: "Rename file…"
                DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
                enabled: controller.canRename && suggestedName.text.length > 0 && suggestedName.text !== namingDialog.sourceName
                onClicked: {
                    confirmRename.proposedName = suggestedName.text
                    confirmRename.open()
                }
                ToolTip.text: controller.canRename ? "Review the old and new filenames before renaming" : "Wait for active work to finish and remove this image from the queue"
                ToolTip.visible: hovered
            }
            Button {
                text: "Close"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "copySuggestedFilename"
                text: namingDialog.copied ? "Copied" : "Copy name"
                DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
                enabled: suggestedName.text.trim().length > 0
                visible: namingDialog.suggestions.length > 0
                onClicked: {
                    controller.copySuggestedName(suggestedName.text.trim())
                    namingDialog.copied = true
                }
            }
        }
        property var suggestions: []
        property string sourceName: ""
        property string sourcePath: ""
        property int sourceId: -1
        property string renameError: ""
        property bool copied: false
        onOpened: {
            sourceName = window.item.name || ""
            sourcePath = window.item.path || ""
            sourceId = window.item.imageId || -1
            renameError = ""
            suggestions = controller.suggestNames()
            suggestedName.text = suggestions.length ? suggestions[0].name : ""
            copied = false
        }
        contentItem: ScrollView {
            id: namingScroll
            implicitHeight: Math.min(namingContent.implicitHeight, window.height - 200)
            contentWidth: availableWidth
            ColumnLayout {
                id: namingContent
                width: namingScroll.availableWidth
                spacing: 12
                Label { Layout.fillWidth: true; text: namingDialog.sourceName; color: window.ink; wrapMode: Text.WrapAnywhere }
                Label {
                    Layout.fillWidth: true
                    text: "Built from saved tags and description. Copy a name, or rename the original file after confirmation."
                    color: window.muted; wrapMode: Text.Wrap
                }
                Repeater {
                    model: namingDialog.suggestions
                    delegate: RadioButton {
                        required property int index
                        required property var modelData
                        objectName: "filenameOption" + index
                        Layout.fillWidth: true
                        text: modelData.style + " · " + modelData.name
                        checked: suggestedName.text === modelData.name
                        autoExclusive: false
                        implicitHeight: Math.max(36, implicitContentHeight + 8)
                        onClicked: suggestedName.text = modelData.name
                        contentItem: Label {
                            text: parent.text
                            leftPadding: parent.indicator.width + parent.spacing
                            color: window.ink; wrapMode: Text.WrapAnywhere
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: namingDialog.suggestions.length ? "Pick or edit a name. Keep the original extension." : "Not enough saved description or tags yet. Generate tags first."
                    color: window.muted; wrapMode: Text.Wrap
                }
                TextField {
                    id: suggestedName
                    objectName: "suggestedFilename"
                    Layout.fillWidth: true
                    visible: namingDialog.suggestions.length > 0
                    selectByMouse: true
                    Accessible.name: "Suggested filename"
                    onTextChanged: {
                        namingDialog.copied = false
                        namingDialog.renameError = ""
                    }
                }
            }
        }
    }

    Dialog {
        id: confirmRename
        objectName: "confirmRenameDialog"
        anchors.centerIn: parent
        width: Math.min(560, window.width - 48)
        modal: true
        title: "Rename the original file?"
        property string proposedName: ""
        footer: DialogButtonBox {
            onRejected: confirmRename.close()
            Button {
                text: "Cancel"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "confirmRenameFile"
                text: "Rename file"
                DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
                enabled: controller.canRename
                onClicked: {
                    var result = controller.renameImage(namingDialog.sourceId, namingDialog.sourcePath, confirmRename.proposedName)
                    confirmRename.close()
                    if (result.ok) {
                        namingDialog.close()
                    } else {
                        namingDialog.renameError = result.error
                        renameFailure.alternative = result.alternative || ""
                        renameFailure.open()
                    }
                }
            }
        }
        Label {
            width: parent.width
            text: "Current name\n" + namingDialog.sourceName + "\n\nNew name\n" + confirmRename.proposedName + "\n\nThe file stays in the same folder. Saved tags are preserved. Existing files will not be replaced."
            color: window.ink; wrapMode: Text.WrapAnywhere
        }
    }
    Dialog {
        id: renameFailure
        objectName: "renameFailureDialog"
        anchors.centerIn: parent
        width: Math.min(560, window.width - 48)
        modal: true
        title: alternative ? "That name is taken" : "Could not rename file"
        property string alternative: ""
        footer: DialogButtonBox {
            onRejected: renameFailure.close()
            Button {
                text: "Choose another"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "useAlternateFilename"
                text: "Use this name…"
                visible: !!renameFailure.alternative
                DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
                onClicked: {
                    suggestedName.text = renameFailure.alternative
                    confirmRename.proposedName = renameFailure.alternative
                    renameFailure.close()
                    confirmRename.open()
                }
            }
        }
        ColumnLayout {
            width: parent.width
            spacing: 12
            Label { Layout.fillWidth: true; text: namingDialog.renameError; color: window.theme.error; wrapMode: Text.Wrap }
            Label {
                Layout.fillWidth: true
                visible: !!renameFailure.alternative
                text: "Available alternative\n" + renameFailure.alternative
                color: window.ink; wrapMode: Text.WrapAnywhere
            }
            Label {
                Layout.fillWidth: true
                visible: !!renameFailure.alternative
                text: "You’ll confirm this name before renaming. Availability is checked again when you confirm."
                color: window.muted; wrapMode: Text.Wrap
            }
        }
    }

    ImageViewer {
        id: imageViewer
        objectName: "imageViewer"
        parent: Overlay.overlay
        backend: controller
        theme: window.theme
        onClosed: grid.forceActiveFocus()
    }
    Menu {
        id: imageContextMenu
        objectName: "imageContextMenu"
        property int targetImageId: -1
        MenuItem {
            objectName: "openImageMenuAction"
            text: "Open"
            onTriggered: imageViewer.openImage(imageContextMenu.targetImageId)
        }
        MenuSeparator {}
        MenuItem {
            objectName: "removeImageMenuAction"
            text: "Remove from library…"
            enabled: controller.canRename && window.item.imageId === imageContextMenu.targetImageId
            onTriggered: removeDialog.review([imageContextMenu.targetImageId])
        }
    }

    SettingsPanel {
        id: settingsPanel
        objectName: "settingsPanel"
        anchors.centerIn: parent
        width: Math.min(520, window.width - 48)
        maximumHeight: window.height - 48
        backend: controller
        theme: window.theme
    }

    DetailsEditor {
        id: detailsEditor
        objectName: "detailsEditor"
        anchors.centerIn: parent
        width: Math.min(1000, window.width - 48)
        maximumHeight: window.height - 48
        backend: controller
        theme: window.theme
    }

    QueuePanel {
        id: queuePanel
        objectName: "queuePanel"
        parent: Overlay.overlay
        width: window.width; height: Math.min(500, window.height * 0.65)
        backend: controller
        theme: window.theme
        onClearRequested: stopBatchDialog.open()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 96
            color: window.color
            RowLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 24
                ColumnLayout {
                    spacing: 2
                    Label { text: "IMAGE LAB"; font.pixelSize: 24; font.weight: Font.DemiBold; font.letterSpacing: 2; color: window.ink }
                    Label { text: "Collect, organize, rediscover."; color: window.muted }
                }
                Item { Layout.fillWidth: true }
                Button { text: "Choose folder"; implicitHeight: 38; enabled: controller.canImport; onClicked: folderDialog.open() }
                ToolButton {
                    id: appMenuButton
                    objectName: "appMenuButton"
                    text: "☰"
                    implicitWidth: 40; implicitHeight: 40
                    font.pixelSize: 22
                    Accessible.name: "App menu"
                    ToolTip.text: "App menu"
                    ToolTip.visible: hovered && !appMenu.visible
                    onClicked: appMenu.open()
                    Menu {
                        id: appMenu
                        objectName: "appMenu"
                        width: 220
                        x: appMenuButton.width - width
                        y: appMenuButton.height + 6
                        MenuItem {
                            objectName: "appMenuChooseFolder"
                            text: "Choose folder…"
                            enabled: controller.canImport
                            onTriggered: folderDialog.open()
                        }
                        MenuItem {
                            objectName: "appMenuViewQueue"
                            text: "View queue"
                            onTriggered: queuePanel.open()
                        }
                        MenuSeparator {}
                        MenuItem {
                            objectName: "appMenuSettings"
                            text: "Settings…"
                            onTriggered: settingsPanel.open()
                        }
                        MenuItem {
                            objectName: "appMenuAbout"
                            text: "About Image Lab"
                            onTriggered: aboutDialog.open()
                        }
                        MenuItem {
                            objectName: "appMenuQuit"
                            text: "Quit"
                            onTriggered: window.close()
                        }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.line }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 0
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.margins: window.height < 700 ? 12 : 20
                spacing: window.height < 700 ? 8 : 16
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 16
                    TextField {
                        id: searchField
                        objectName: "catalogSearch"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 280
                        implicitHeight: 46
                        font.pixelSize: 16
                        leftPadding: 14
                        rightPadding: clearSearch.visible ? clearSearch.width + 14 : 14
                        placeholderText: "Search files or generated tags"
                        placeholderTextColor: window.muted
                        color: window.ink
                        background: Rectangle {
                            color: window.panel
                            border.color: searchField.activeFocus ? window.accent : window.line
                            border.width: searchField.activeFocus ? 2 : 1
                            radius: 3
                        }
                        selectByMouse: true
                        onTextChanged: searchDelay.restart()
                        Accessible.name: "Search catalog"
                        ToolButton {
                            id: clearSearch
                            objectName: "clearCatalogSearch"
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            width: 34; height: 34
                            visible: searchField.text.length > 0
                            text: "×"
                            font.pixelSize: 22
                            Accessible.name: "Clear search"
                            ToolTip.text: "Clear search"
                            ToolTip.visible: hovered
                            onClicked: {
                                searchField.clear()
                                searchDelay.stop()
                                controller.search("")
                                searchField.forceActiveFocus()
                            }
                        }
                    }
                    Label { text: controller.total + " images"; color: window.muted }
                }
                RowLayout {
                    id: filterRow
                    Layout.fillWidth: true; spacing: 6
                    Repeater {
                        model: [
                            { key: "all", label: "All images", hint: "Every image matching this search" },
                            { key: "needs_tags", label: "Needs tags", hint: "Images without saved tags, including unsuccessful attempts" },
                            { key: "tagged", label: "Tagged", hint: "Images with saved tags" },
                            { key: "failed", label: "Failed", hint: "Images whose latest analysis failed; previous tags may still be saved" }
                        ]
                        Button {
                            id: filterButton
                            required property var modelData
                            objectName: "filter-" + modelData.key
                            Layout.fillWidth: true; Layout.preferredWidth: 1
                            Layout.minimumWidth: 0
                            implicitHeight: 48
                            checkable: true
                            checked: controller.libraryFilter === modelData.key
                            ButtonGroup.group: libraryFilters
                            onClicked: {
                                if (searchDelay.running) {
                                    searchDelay.stop()
                                    controller.search(searchField.text)
                                }
                                controller.setLibraryFilter(modelData.key)
                            }
                            background: Rectangle {
                                color: filterButton.checked ? window.theme.selection : window.panel
                                border.color: filterButton.checked || filterButton.activeFocus ? window.accent : window.line
                                radius: 3
                            }
                            contentItem: Column {
                                spacing: 2
                                Label {
                                    width: parent.width; text: filterButton.modelData.label
                                    horizontalAlignment: Text.AlignHCenter
                                    color: filterButton.checked ? window.theme.selectionText : window.ink
                                    font.pixelSize: 12; elide: Text.ElideRight
                                }
                                Label {
                                    width: parent.width
                                    text: controller.filterCounts[filterButton.modelData.key] || 0
                                    horizontalAlignment: Text.AlignHCenter
                                    color: filterButton.checked ? window.theme.selectionText : window.muted; font.pixelSize: 11; font.family: "monospace"
                                }
                            }
                            Accessible.name: modelData.label + ", " + (controller.filterCounts[modelData.key] || 0) + " images"
                            ToolTip.text: modelData.hint
                            ToolTip.visible: hovered
                        }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    GalleryAction { text: "Select all"; enabled: controller.total > 0 && !searchDelay.running; onClicked: controller.selectMatches() }
                    GalleryAction { text: "Clear"; enabled: controller.checkedCount > 0; onClicked: controller.clearChecked() }
                    GalleryAction { objectName: "generateSelected"; text: "Generate selected (" + controller.checkedCount + ")"; enabled: controller.canQueue && controller.checkedCount > 0 && !searchDelay.running; onClicked: controller.generateSelected() }
                    GalleryAction { objectName: "generateMissing"; text: "Generate missing"; enabled: controller.canQueue && controller.total > 0 && !searchDelay.running; onClicked: controller.generateMissing() }
                    GalleryAction { text: "Regenerate…"; enabled: controller.canQueue && controller.checkedCount > 0 && !searchDelay.running; onClicked: regenerateDialog.open() }
                    GalleryAction {
                        objectName: "removeSelectedImages"
                        text: "Remove selected…"
                        enabled: !controller.busy && controller.checkedCount > 0 && !searchDelay.running
                        onClicked: removeDialog.review(controller.checkedImageIds())
                        ToolTip.visible: hovered
                        ToolTip.text: "Remove selected images from the library, not from disk"
                    }
                }
                GridView {
                    id: grid
                    objectName: "contactSheet"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true
                    model: gallery
                    cellWidth: width / Math.max(2, Math.floor(width / 240))
                    cellHeight: cellWidth * 0.64 + 46
                    cacheBuffer: 200
                    keyNavigationEnabled: true
                    activeFocusOnTab: true
                    Keys.onSpacePressed: { if (currentItem) controller.toggleChecked(currentItem.imageId) }
                    Keys.onReturnPressed: { if (currentItem) imageViewer.openImage(currentItem.imageId) }
                    Keys.onEnterPressed: { if (currentItem) imageViewer.openImage(currentItem.imageId) }
                    highlightFollowsCurrentItem: true
                    onCurrentIndexChanged: {
                        if (currentItem) controller.select(currentItem.imageId)
                    }
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Item {
                        id: tile
                        required property int index
                        required property int imageId
                        required property string name
                        required property string thumbnail
                        required property string preview
                        required property bool isGif
                        required property int pixelWidth
                        required property int pixelHeight
                        required property string dimensions
                        required property bool analyzed
                        required property bool checked
                        width: grid.cellWidth; height: grid.cellHeight
                        Rectangle {
                            anchors.fill: parent; anchors.rightMargin: 12; anchors.bottomMargin: 12
                            color: window.panel
                            border.width: window.item.imageId === tile.imageId ? 2 : 1
                            border.color: window.item.imageId === tile.imageId || tile.checked ? window.accent : window.line
                            Image {
                                id: tileThumbnail
                                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                anchors.margins: 6
                                height: parent.height - 48
                                source: tile.thumbnail
                                sourceSize.width: 512; sourceSize.height: 512
                                asynchronous: true; cache: false
                                fillMode: Image.PreserveAspectFit
                            }
                            GifPreview {
                                objectName: "tileGif" + tile.imageId
                                anchors.fill: tileThumbnail
                                imageSource: tile.preview
                                active: tile.isGif && controller.settings.animateHoveredGifs && tileMouse.containsMouse && !imageViewer.visible
                                        && tile.y + tile.height > grid.contentY && tile.y < grid.contentY + grid.height
                                pixelWidth: tile.pixelWidth; pixelHeight: tile.pixelHeight
                                maximumWidth: 512; maximumHeight: 512
                            }
                            Column {
                                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                                anchors.margins: 10; spacing: 2
                                Label { width: parent.width; text: tile.name; elide: Text.ElideMiddle; color: window.ink; font.pixelSize: 12 }
                                Label { text: tile.dimensions + (tile.isGif ? "   ·   GIF" : "") + (tile.analyzed ? "   ·   tagged" : ""); color: tile.analyzed ? window.accent : window.muted; font.pixelSize: 10; font.family: "monospace" }
                            }
                            MouseArea {
                                id: tileMouse
                                hoverEnabled: true
                                objectName: "imageTileMouse" + tile.imageId
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                onClicked: function(mouse) {
                                    grid.currentIndex = tile.index
                                    grid.forceActiveFocus()
                                    controller.select(tile.imageId)
                                    if (mouse.button === Qt.RightButton) {
                                        imageContextMenu.targetImageId = tile.imageId
                                        imageContextMenu.popup(tile, mouse.x, mouse.y)
                                    } else if (mouse.modifiers & Qt.ControlModifier) {
                                        controller.toggleChecked(tile.imageId)
                                    }
                                }
                                onDoubleClicked: function(mouse) {
                                    if (mouse.button === Qt.LeftButton && !(mouse.modifiers & Qt.ControlModifier)) {
                                        grid.currentIndex = tile.index
                                        controller.select(tile.imageId)
                                        imageViewer.openImage(tile.imageId)
                                    }
                                }
                            }
                        }
                        CheckBox {
                            anchors.top: parent.top; anchors.left: parent.left
                            anchors.margins: 8
                            checked: tile.checked
                            onClicked: controller.toggleChecked(tile.imageId)
                            Accessible.name: "Include " + tile.name + " in batch"
                            ToolTip.text: "Include in batch"; ToolTip.visible: hovered
                        }
                        Accessible.role: Accessible.ListItem
                        Accessible.name: tile.name + ", " + tile.dimensions
                        Accessible.onPressAction: controller.select(tile.imageId)
                    }
                    Column {
                        anchors.centerIn: parent; width: Math.min(parent.width - 40, 400); spacing: 14
                        visible: controller.total === 0
                        Label { width: parent.width; text: searchField.text || controller.libraryFilter !== "all" ? "No matching images" : "Start with a small folder"; font.pixelSize: 25; wrapMode: Text.Wrap; color: window.ink; horizontalAlignment: Text.AlignHCenter }
                        Label { width: parent.width; text: searchField.text || controller.libraryFilter !== "all" ? "Try another filter or search. Queued work is unchanged." : "Choose a folder, pick an image, then let the local model describe it. Scanning leaves originals untouched."; wrapMode: Text.Wrap; color: window.muted; horizontalAlignment: Text.AlignHCenter }
                    }
                }
            }
            Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: window.line }
            Rectangle {
                Layout.preferredWidth: Math.min(390, window.width * 0.34)
                Layout.fillHeight: true
                color: window.panel
                ScrollView {
                    anchors.fill: parent; anchors.margins: 22
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 18
                        Label { text: "IMAGE NOTES"; color: window.accent; font.family: "monospace"; font.pixelSize: 12; font.letterSpacing: 1 }
                        Label { Layout.fillWidth: true; text: window.item.name || "Pick an image"; color: window.ink; font.pixelSize: 21; font.weight: Font.Medium; wrapMode: Text.WrapAnywhere }
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 205
                            color: window.theme.preview
                            Image {
                                anchors.fill: parent; anchors.margins: 6
                                source: window.item.isGif && controller.settings.autoplaySidebarGifs ? "" : window.item.preview || ""
                                sourceSize.width: 1000; sourceSize.height: 650
                                asynchronous: true; cache: false; autoTransform: true
                                fillMode: Image.PreserveAspectFit
                            }
                            GifPreview {
                                objectName: "sidebarGif"
                                anchors.fill: parent; anchors.margins: 6
                                imageSource: window.item.preview || ""
                                active: !!window.item.isGif && controller.settings.autoplaySidebarGifs && !imageViewer.visible
                                pixelWidth: window.item.pixelWidth || 1
                                pixelHeight: window.item.pixelHeight || 1
                                maximumWidth: 1000; maximumHeight: 650
                            }
                        }
                        Label { Layout.fillWidth: true; text: window.item.dimensions ? window.item.dimensions + (window.item.isGif ? " · GIF" : "") : "Your catalog stays on this computer."; color: window.muted }
                        Button {
                            Layout.fillWidth: true
                            implicitHeight: 40
                            objectName: "generateTags"
                            text: controller.selectedState === "queued" ? "Queued"
                                  : controller.selectedState === "running" ? "Analyzing…"
                                  : window.item.analyzed ? "Generate tags again" : "Generate tags"
                            enabled: !!window.item.imageId && controller.canQueue && controller.selectedState !== "queued" && controller.selectedState !== "running"
                            onClicked: controller.analyze()
                        }
                        Button {
                            objectName: "suggestNames"
                            Layout.fillWidth: true
                            text: "Suggest names"
                            enabled: !!window.item.analyzed
                            onClicked: namingDialog.open()
                            ToolTip.text: enabled ? "Suggest filenames, then copy or rename after confirmation" : "Generate tags first to suggest filenames"
                            ToolTip.visible: hovered
                        }
                        Button {
                            objectName: "editImageDetails"
                            Layout.fillWidth: true
                            text: window.item.userEdited ? "Edit details · edited" : "Edit details"
                            enabled: controller.canEditDetails
                            onClicked: detailsEditor.open()
                            ToolTip.text: "Edit saved text and tags. Finish active work and remove this image from the queue first."
                            ToolTip.visible: hovered
                        }
                        Button {
                            objectName: "removeLibraryImage"
                            Layout.fillWidth: true
                            text: "Remove from library…"
                            enabled: controller.canRename
                            onClicked: removeDialog.review([window.item.imageId])
                            ToolTip.visible: hovered
                            ToolTip.text: "Keep the original file on disk. Finish active work and remove this image from the queue first."
                        }
                        Label {
                            objectName: "imageAnalysisState"
                            Layout.fillWidth: true
                            text: controller.selectedState === "queued" ? "Queued · see the queue for progress"
                                  : controller.selectedState === "running" ? "Analyzing · you can keep browsing"
                                  : controller.selectedState === "failed" ? "Analysis failed · retry from the queue"
                                  : window.item.analyzed ? "Analysis complete · review the results below"
                                  : controller.selectedState === "canceled" ? "Removed from queue" : "Not analyzed"
                            color: controller.selectedState === "failed" ? window.theme.error : window.accent
                            wrapMode: Text.Wrap; font.pixelSize: 12
                        }
                        Label { Layout.fillWidth: true; text: window.item.userEdited ? "AI-generated · with your saved corrections" : "qwen3-vl:4b · local inference\nPredictions, not verified facts"; color: window.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
                        Label { Layout.fillWidth: true; visible: !!window.item.error; text: window.item.error || ""; color: window.theme.error; wrapMode: Text.WrapAnywhere }
                        Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                        Label { Layout.fillWidth: true; text: window.item.caption || "No description yet. Generate tags to inspect what the model sees."; textFormat: Text.PlainText; color: window.ink; wrapMode: Text.Wrap; font.pixelSize: 16; lineHeight: 1.2 }
                        Label { text: window.item.medium || ""; textFormat: Text.PlainText; color: window.accent; visible: !!window.item.analyzed }
                        Flow {
                            Layout.fillWidth: true; spacing: 6
                            Repeater {
                                model: window.item.tags || []
                                Rectangle {
                                    required property string modelData
                                    width: Math.min(tagLabel.implicitWidth + 18, 290); height: 28
                                    color: window.theme.selection; radius: 4
                                    Label { id: tagLabel; anchors.centerIn: parent; width: parent.width - 18; text: parent.modelData; textFormat: Text.PlainText; color: window.theme.selectionText; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                            }
                        }
                        Label { Layout.fillWidth: true; visible: !!window.item.analyzed; text: "Composition   " + (window.item.composition || "—") + "\nMood   " + (window.item.mood || "—"); textFormat: Text.PlainText; color: window.muted; wrapMode: Text.Wrap; lineHeight: 1.4 }
                        Label { Layout.fillWidth: true; visible: !!window.item.analyzed; text: "Writing detected: " + (window.item.textPresent ? "yes" : "no") + "\nWatermark predicted: " + (window.item.watermarkPresent ? "yes" : "no") + "\nAnalyzed in " + (window.item.elapsed || "—") + "s"; color: window.muted; wrapMode: Text.Wrap; lineHeight: 1.4 }
                        Label { Layout.fillWidth: true; text: window.item.path || ""; color: window.muted; font.pixelSize: 10; wrapMode: Text.WrapAnywhere }
                    }
                }
            }
        }
        BatchProgress {
            objectName: "queueBar"
            Layout.fillWidth: true
            theme: window.theme
            batch: controller.batch
            busy: controller.busy
            submitting: controller.submitting
            progress: controller.queueProgress
            onPauseRequested: controller.pauseBatch()
            onResumeRequested: controller.resumeBatch()
            onDetailsRequested: queuePanel.open()
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
        RowLayout {
            Layout.fillWidth: true; Layout.margins: 14; spacing: 12
            BusyIndicator { running: controller.busy; opacity: running ? 1 : 0; Layout.preferredWidth: 22; Layout.preferredHeight: 22 }
            Label { Layout.fillWidth: true; text: controller.status; color: window.muted; elide: Text.ElideRight; Accessible.name: text }
            Button { visible: controller.scanning; text: "Stop scan"; onClicked: controller.stopScan(); ToolTip.text: "Stops folder scanning. Inference finishes its current request."; ToolTip.visible: hovered }
            Label {
                objectName: "selectionStatus"
                text: controller.checkedCount > 0 ? controller.checkedCount + " selected" : "Ctrl-click or Space to select"
                color: window.muted; font.pixelSize: 11
                Accessible.name: text
            }
        }
    }
}
