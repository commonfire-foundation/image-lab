"""Exercise actual Qt Quick wheel events, not only the configured style hint."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QPoint, QPointF, QUrl, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from image_lab_ui.app import configure_wheel_scrolling

ROOT = Path(__file__).resolve().parents[1]


class ScrollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_wheel_faster_in_grid_and_scroll_panel(self):
        previous = self.app.styleHints().wheelScrollLines()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        try:
            with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                qml = Path(directory) / 'scroll.qml'
                qml.write_text('''import QtQuick
import QtQuick.Controls
ApplicationWindow {
    width: 640; height: 400; visible: true
    GridView {
        objectName: "grid"; width: 320; height: 400
        cellWidth: 100; cellHeight: 100; model: 600
        delegate: Rectangle { width: 90; height: 90; color: "gray" }
    }
    ScrollView {
        id: panel; x: 320; width: 320; height: 400; contentWidth: availableWidth
        Component.onCompleted: contentItem.objectName = "panelFlick"
        Column { Repeater { model: 200; Label { text: "A scrollable row"; height: 40 } } }
    }
}''')
                engine.load(QUrl.fromLocalFile(str(qml)))
                self.assertTrue(engine.rootObjects(), warnings)
                window = engine.rootObjects()[0]
                QTest.qWait(100)
                def distance(item, x, lines):
                    self.app.styleHints().setWheelScrollLines(lines)
                    item.setProperty('contentY', 0)
                    QTest.qWait(50)
                    QTest.wheelEvent(window, QPointF(x,150), QPoint(0,-120))
                    QTest.qWait(450)
                    return item.property('contentY')
                for name, x in (('grid',150), ('panelFlick',450)):
                    with self.subTest(control=name):
                        item = window.findChild(QObject,name)
                        self.assertIsNotNone(item)
                        baseline = distance(item,x,3)
                        configure_wheel_scrolling(self.app)
                        configured = self.app.styleHints().wheelScrollLines()
                        self.assertEqual(configured,9)
                        faster = distance(item,x,configured)
                        self.assertGreater(baseline,0)
                        self.assertGreater(faster,baseline*2)
                        self.assertAlmostEqual(faster,baseline*3,delta=3)
                self.assertFalse(warnings,warnings)
                window.close()
        finally:
            self.app.styleHints().setWheelScrollLines(previous)
            engine.deleteLater()
            self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__ == '__main__': unittest.main()
