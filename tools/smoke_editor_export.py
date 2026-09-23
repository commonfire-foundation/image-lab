"""Extracted-wheel edit → managed inspection → encode/publish/import acceptance."""
import json
from pathlib import Path
import sys
import tempfile
from PIL import Image, ImageCms, ImageDraw, PngImagePlugin
from PySide6.QtCore import QObject, QEvent, QEventLoop, QMetaObject, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from image_lab_ui import app as module
from image_lab_ui.edit_process import render_source
from image_lab_ui.edit_recipe import EditRecipe


def wait(predicate):
    if predicate(): return
    loop=QEventLoop(); poll=QTimer(); end=QTimer()
    poll.setInterval(10); end.setSingleShot(True)
    poll.timeout.connect(lambda:loop.quit() if predicate() else None); end.timeout.connect(loop.quit)
    poll.start(); end.start(30000); loop.exec()
    poll.stop(); end.stop(); poll.timeout.disconnect(); end.timeout.disconnect()
    assert predicate(), 'Packaged export did not reach its expected state'


def main():
    root=Path.cwd().resolve(); output=Path(sys.argv[1]).resolve()
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    output.mkdir(exist_ok=True,parents=True)
    QQuickStyle.setStyle('Basic'); app=QGuiApplication([])
    with tempfile.TemporaryDirectory(dir=root) as temp:
        directory=Path(temp); path=directory/'geometry-source.png'
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        info=PngImagePlugin.PngInfo(); info.add_text('XML:com.adobe.xmp','private fixture metadata')
        exif=Image.Exif(); exif[315]='private fixture author'
        with Image.new('RGBA',(2600,1600),'#263744') as image:
            draw=ImageDraw.Draw(image)
            for x,color in enumerate(('#658b85','#cfa66b','#897c9a','#41657c')):
                draw.rectangle((x*650+12,12,(x+1)*650-12,1588),fill=color)
            draw.ellipse((200,200,1000,1000),fill=(230,217,180,128))
            draw.polygon(((1400,1300),(2400,1300),(1800,300)),fill=(37,58,66,0))
            image.save(path,icc_profile=profile,pnginfo=info,exif=exif)
        before=path.read_bytes(),path.stat().st_mtime_ns
        c=module.Controller(directory/'catalog',theme_paths=[directory/'no-theme'])
        engine=QQmlApplicationEngine(); warnings=[]; window=None; receipts=[]
        engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
        engine.addImageProvider('editor-preview',c.editor.preview.provider)
        engine.rootContext().setContextProperty('controller',c); engine.rootContext().setContextProperty('gallery',c.model)
        try:
            c.catalog.import_image(path); c.search('geometry'); image_id=c.catalog.rows()[0]['id']; c.select(image_id)
            engine.load(QUrl.fromLocalFile(str(Path(module.__file__).with_name('Main.qml'))))
            assert engine.rootObjects(),warnings
            window=engine.rootObjects()[0]
            def obj(name):
                found=window.findChild(QObject,name); assert found is not None,name; return found
            def invoke(name,signal='clicked'): assert QMetaObject.invokeMethod(obj(name),signal)
            def settle():
                frames=[]; callback=lambda:frames.append(True)
                window.frameSwapped.connect(callback); window.update(); wait(lambda:bool(frames)); window.frameSwapped.disconnect(callback)
            def click(name):
                settle()
                button=obj(name); assert button.property('enabled'),name
                QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,
                                 button.mapToScene(button.boundingRect().center()).toPoint())
            def capture(name):
                settle()
                shot=window.grabWindow(); assert not shot.isNull() and shot.save(str(output/name))
            window.setWidth(900); window.setHeight(600)
            c.uiAction.emit('viewer.open',image_id); wait(lambda:obj('imageViewer').property('visible'))
            click('openGeometryEditor'); wait(lambda:c.editor.state=='ready' and obj('geometryEditor').property('previewReady'))
            for name,value in (('cropLeft','100'),('cropTop','100'),('cropRight','2500'),('cropBottom','1500')):
                obj(name).setProperty('text',value); invoke(name,'textEdited')
            invoke('applyGeometryCrop'); invoke('rotateGeometry')
            wait(lambda:c.editor.state=='ready' and obj('geometryEditor').property('previewReady'))
            recipe=EditRecipe.from_dict(c.editor.recipe); assert recipe.result_size.as_list()==[1400,2400]
            full=render_source(c.editor._source,recipe,preview_longest=None,color_policy='srgb-v1')
            for width,height in ((900,600),(1280,820)):
                window.setWidth(width); window.setHeight(height)
                capture(f'editor-export-workbench-{width}.png')
                click('openEditorMeasurements'); wait(lambda:not c.editor.measurements['loading'])
                assert not c.editor.measurements['error'],c.editor.measurements
                assert c.editor.measurements['sourcePolicyAligned'] and not c.editor.measurements['colorAgreement']
                assert c.editor.measurements['revision']==c.editor.revision
                capture(f'editor-managed-measurements-{width}.png')
                QTest.keyClick(window,Qt.Key.Key_Escape); assert c.editorActive
                for index,suffix in enumerate(('png','jpg','webp')):
                    click('openExportCopy'); assert obj('exportGeometryDialog').property('visible')
                    obj('exportFilename').setProperty('text',f'geometry-copy-{width}.{suffix}')
                    combo=obj('exportFormat'); combo.forceActiveFocus()
                    for _ in range(index): QTest.keyClick(window,Qt.Key.Key_Down)
                    assert combo.property('currentIndex')==index
                    # Format activation maintains the extension while preserving the chosen stem.
                    if suffix=='jpg':
                        assert not obj('confirmExportCopy').property('enabled')
                        click('exportMatteConsent')
                    click('exportImport')
                    capture(f'editor-export-dialog-{width}-{suffix}.png')
                    button=obj('confirmExportCopy'); center=button.mapToScene(button.boundingRect().center())
                    assert 0<center.y()<window.height() and 0<center.x()<window.width()
                    click('confirmExportCopy'); wait(lambda:not c.editor.exporting)
                    receipt=c.editor.lastExport
                    assert receipt.get('published') and receipt.get('path_confirmed') and receipt.get('directory_synced'),(receipt,c.editor.error)
                    assert receipt['imported'] and not receipt['warnings'] and not receipt['import_error'],receipt
                    assert not c.editor.dirty and c.selected['imageId']==image_id and c.model.query=='geometry'
                    with Image.open(receipt['path']) as image:
                        image.load(); assert image.size==(1400,2400) and not image.getexif()
                        assert image.info.get('icc_profile') and not image.info.get('xmp') and not image.info.get('XML:com.adobe.xmp')
                        if suffix in ('png','webp'): assert image.convert('RGBA').tobytes()==full.full_resolution_pixels()
                        else: assert image.mode=='RGB'
                    receipts.append({key:receipt[key] for key in ('format','size','published','imported','directory_synced')})
                capture(f'editor-export-saved-{width}.png')
            assert c.catalog.count()==7
            assert (path.read_bytes(),path.stat().st_mtime_ns)==before
            click('closeGeometryEditor'); wait(lambda:not c.editorActive)
            assert not warnings,warnings
            print(json.dumps({'packaged_edit_export_import':True,'device_pixel_ratio':window.devicePixelRatio(),
                'original_unchanged':True,'managed_original_measurements':True,'qml_warnings':warnings,
                'encoded_srgb_and_lossless_pixel_acceptance':True,'monitor_hdr_certified':False,'copies':receipts}))
        finally:
            if c.editor.exporting:
                c.editor.cancelExport(); wait(lambda:not c.editor.exporting)
            c.editor.shutdown(discard=True,revision=c.editor.revision); wait(lambda:c.editor.state=='closed')
            if window: window.close()
            engine.deleteLater(); app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            c.viewerMetadata.shutdown(); c.viewerMeasurements.shutdown(); c.omarchy_palette.timer.stop(); c.catalog.close()
            c.deleteLater(); app.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__': main()
