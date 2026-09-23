import QtQuick

AnimatedImage {
    property url imageSource
    property bool active: false
    property bool pauseRequested: false
    onPauseRequestedChanged: paused = pauseRequested
    onStatusChanged: {
        if (status === Image.Ready) {
            // Loading a new QMovie resets its pause state; apply after startup.
            Qt.callLater(function() { if (active && status === Image.Ready) paused = pauseRequested })
        }
    }
    property int pixelWidth: 1
    property int pixelHeight: 1
    property int maximumWidth: 512
    property int maximumHeight: 512
    readonly property real previewScale: Math.min(1, maximumWidth / Math.max(1, pixelWidth), maximumHeight / Math.max(1, pixelHeight))
    // QMovie scales to the exact requested size, unlike still Image decoding.
    sourceSize.width: Math.max(1, Math.round(pixelWidth * previewScale))
    sourceSize.height: Math.max(1, Math.round(pixelHeight * previewScale))
    source: active ? imageSource : ""
    visible: active
    playing: active
    asynchronous: true
    // Avoid retaining every decoded frame of large/long GIFs.
    cache: false
    autoTransform: true
    fillMode: Image.PreserveAspectFit
}
