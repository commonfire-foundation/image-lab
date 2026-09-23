import QtQuick

// Coordinates are normalized to the painted image, never the letterbox or DPR.
Item {
    id: root
    property color accent: "white"
    property real pixelWidth: 1
    property real pixelHeight: 1
    property var bounds: [0, 0, 1, 1]
    property var seed: [0, 0, 1, 1]
    property bool dragging: false
    property string operation: ""
    property real startX: 0
    property real startY: 0
    readonly property bool changedSelection: bounds[0] !== 0 || bounds[1] !== 0 || bounds[2] !== 1 || bounds[3] !== 1
    readonly property real leftEdge: bounds[0] * width
    readonly property real topEdge: bounds[1] * height
    readonly property real rightEdge: bounds[2] * width
    readonly property real bottomEdge: bounds[3] * height
    Accessible.role: Accessible.Graphic
    Accessible.name: "Staged crop selection. Drag to select, corners resize, inside moves. Arrow keys move the selection; numeric crop fields are also available."

    function clamp(value, low, high) { return Math.max(low, Math.min(high, value)) }
    function abortGesture() {
        if (dragging) { bounds = seed.slice(); dragging = false }
    }
    function reset() { dragging = false; bounds = [0, 0, 1, 1] }
    function moveSelection(dx, dy, base) {
        dx = clamp(dx, -base[0], 1 - base[2]); dy = clamp(dy, -base[1], 1 - base[3])
        bounds = [base[0] + dx, base[1] + dy, base[2] + dx, base[3] + dy]
    }
    function cornerAt(x, y) {
        var points = [[leftEdge,topEdge,"nw"], [rightEdge,topEdge,"ne"], [leftEdge,bottomEdge,"sw"], [rightEdge,bottomEdge,"se"]]
        var best = 145, name = ""
        for (var i = 0; i < points.length; ++i) {
            var dx = x - points[i][0], dy = y - points[i][1], distance = dx*dx + dy*dy
            if (distance < best) { best = distance; name = points[i][2] }
        }
        return name
    }
    onWidthChanged: abortGesture()
    onHeightChanged: abortGesture()
    onEnabledChanged: if (!enabled) abortGesture()
    onVisibleChanged: if (!visible) abortGesture()
    Keys.onPressed: function(event) {
        if (!changedSelection || dragging) return
        var step = event.modifiers & Qt.ShiftModifier ? 10 : 1
        var dx = 0, dy = 0
        if (event.key === Qt.Key_Left) dx = -step / pixelWidth
        else if (event.key === Qt.Key_Right) dx = step / pixelWidth
        else if (event.key === Qt.Key_Up) dy = -step / pixelHeight
        else if (event.key === Qt.Key_Down) dy = step / pixelHeight
        else return
        moveSelection(dx, dy, bounds)
        event.accepted = true
    }
    Rectangle { x: 0; y: 0; width: root.width; height: root.topEdge; color: "#88000000" }
    Rectangle { x: 0; y: root.bottomEdge; width: root.width; height: Math.max(0, root.height-root.bottomEdge); color: "#88000000" }
    Rectangle { x: 0; y: root.topEdge; width: root.leftEdge; height: root.bottomEdge-root.topEdge; color: "#88000000" }
    Rectangle { x: root.rightEdge; y: root.topEdge; width: Math.max(0, root.width-root.rightEdge); height: root.bottomEdge-root.topEdge; color: "#88000000" }
    Rectangle {
        x: root.leftEdge; y: root.topEdge
        width: root.rightEdge-root.leftEdge; height: root.bottomEdge-root.topEdge
        color: "transparent"; border.width: 2; border.color: root.accent
    }
    Repeater {
        model: 4
        Rectangle {
            required property int index
            x: (index % 2 ? root.rightEdge : root.leftEdge) - 5
            y: (index >= 2 ? root.bottomEdge : root.topEdge) - 5
            width: 10; height: 10; color: root.accent; border.color: "#202020"
        }
    }
    MouseArea {
        id: pointer
        objectName: "cropPointer"
        anchors.fill: parent
        anchors.margins: -12
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        cursorShape: root.dragging && root.operation === "move" ? Qt.ClosedHandCursor : Qt.CrossCursor
        onPressed: function(mouse) {
            var p = root.mapFromItem(pointer, mouse.x, mouse.y)
            var corner = root.cornerAt(p.x, p.y)
            // Extend corner hit targets across the edge, but reject letterbox draws.
            if (!corner && (p.x < 0 || p.x > root.width || p.y < 0 || p.y > root.height)) { mouse.accepted = false; return }
            root.forceActiveFocus()
            root.seed = root.bounds.slice()
            root.startX = p.x; root.startY = p.y
            root.operation = corner
            if (!root.operation) {
                root.operation = root.changedSelection && p.x > root.leftEdge && p.x < root.rightEdge && p.y > root.topEdge && p.y < root.bottomEdge ? "move" : "draw"
            }
            root.dragging = true
        }
        onPositionChanged: function(mouse) {
            if (!root.dragging) return
            var p = root.mapFromItem(pointer, mouse.x, mouse.y)
            var x = root.clamp(p.x/root.width, 0, 1), y = root.clamp(p.y/root.height, 0, 1)
            var minW = 1 / root.pixelWidth, minH = 1 / root.pixelHeight
            var b = root.seed.slice()
            if (root.operation === "move") {
                root.moveSelection((p.x-root.startX)/root.width, (p.y-root.startY)/root.height, b)
                return
            }
            if (root.operation === "draw") {
                var sx = root.clamp(root.startX/root.width, 0, 1), sy = root.clamp(root.startY/root.height, 0, 1)
                if (Math.abs(x-sx) < minW || Math.abs(y-sy) < minH) return
                b = [Math.min(sx,x), Math.min(sy,y), Math.max(sx,x), Math.max(sy,y)]
            } else {
                if (root.operation.indexOf("w") !== -1) b[0] = root.clamp(x, 0, b[2]-minW)
                if (root.operation.indexOf("e") !== -1) b[2] = root.clamp(x, b[0]+minW, 1)
                if (root.operation.indexOf("n") !== -1) b[1] = root.clamp(y, 0, b[3]-minH)
                if (root.operation.indexOf("s") !== -1) b[3] = root.clamp(y, b[1]+minH, 1)
            }
            root.bounds = b
        }
        onReleased: function(mouse) {
            var p = root.mapFromItem(pointer, mouse.x, mouse.y)
            if (root.dragging && root.operation === "draw" && Math.hypot(p.x-root.startX, p.y-root.startY) < 3) root.bounds = root.seed.slice()
            root.dragging = false
        }
        onCanceled: root.abortGesture()
    }
}
