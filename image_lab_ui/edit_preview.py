"""Tagged Qt preview bridge, not an editor UI or a worker scheduler.

Call begin/publish/clear on the owning Qt thread. Run render_source and the public
measurement API off that thread. Only validated, bounded preview results belong
here; full-resolution export pixels never enter this provider.
"""
from threading import Lock
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QThread, Signal
from PySide6.QtGui import QColorSpace, QImage
from PySide6.QtQuick import QQuickImageProvider

from .editor_measurements import validate_source_measurements
from .edit_process import WorkerImage
from .edit_protocol import SourceSnapshot, validate_color_options
from .edit_recipe import EditRecipe


def preview_qimage(frame):
    """Detach raw bytes and tag known sRGB once; never parse a source ICC in Qt."""
    if (not isinstance(frame, WorkerImage) or not frame.is_preview
            or max(frame.size.width, frame.size.height) > 2048 or frame.color is None
            or frame.mode not in ('RGB', 'RGBA')):
        raise ValueError('A validated bounded editor preview is required.')
    channels = 4 if frame.mode == 'RGBA' else 3
    if len(frame.pixels) != frame.size.width * frame.size.height * channels:
        raise ValueError('Invalid preview raster length.')
    color = frame.color
    validate_color_options(color.policy, color.assume_srgb)
    managed = color.policy == 'srgb-v1'
    if ((managed and (color.output_color_space != 'srgb' or color.status not in ('converted', 'declared_srgb', 'assumed_srgb')))
            or (not managed and (color.status != 'unmanaged' or color.output_color_space is not None))):
        raise ValueError('Invalid preview interpretation.')
    format_ = QImage.Format.Format_RGBA8888 if channels == 4 else QImage.Format.Format_RGB888
    image = QImage(frame.pixels, frame.size.width, frame.size.height,
                   frame.size.width * channels, format_).copy()
    if image.isNull():
        raise ValueError('Qt could not allocate a preview.')
    # Pixels are already converted/interpreted. Setting a tag is not another
    # conversion; do not apply the original ICC to these pixels a second time.
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb) if managed else QColorSpace())
    return image


def validate_original_measurements(frame, recipe, result):
    """Source/policy alignment only, not exact sampled colors or edited statistics."""
    source = frame.source
    if frame.recipe != recipe or recipe != EditRecipe.original(source.oriented_size.width, source.oriented_size.height):
        raise ValueError('Original measurements cannot describe an edited recipe.')
    return validate_source_measurements(source, frame.color, result)


class EditorImageProvider(QQuickImageProvider):
    """One retained frame, with unique URLs and no source-path loading."""
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = Lock()
        self._token = ''
        self._image = QImage()

    def replace(self, token='', image=None):
        with self._lock:
            self._token = token
            self._image = QImage(image) if image is not None else QImage()

    def requestImage(self, id, size, requestedSize):
        # Ignore requestedSize: QML may scale the bounded raster, never request
        # a fresh/full decode. Return an implicitly-shared detached Qt handle.
        with self._lock:
            image = QImage(self._image) if id == self._token else QImage()
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


class EditorPreview(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.provider = EditorImageProvider()
        self._expected = None
        self._generation = -1
        self._token = ''
        self._url = ''
        self._frame = None

    @Property(str, notify=changed)
    def url(self):
        return self._url

    def _owning_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Publish editor previews on their owning Qt thread.')

    def clear(self):
        self._owning_thread()
        self._expected = None
        self._frame = None
        self._url = ''
        self.provider.replace()
        self.changed.emit()

    def begin(self, source, recipe, *, request_id, generation, color_policy='legacy-v1', assume_srgb=False):
        self._owning_thread()
        validate_color_options(color_policy, assume_srgb)
        if (not isinstance(source, SourceSnapshot) or not isinstance(recipe, EditRecipe)
                or source.oriented_size != recipe.source_size
                or type(generation) is not int or generation <= self._generation
                or type(request_id) is not str or not 1 <= len(request_id) <= 128):
            raise ValueError('Invalid preview request identity or generation.')
        self.clear()
        self._generation = generation
        self._token = uuid4().hex
        self._expected = (source, recipe, request_id, generation, color_policy, assume_srgb)

    def publish(self, frame):
        self._owning_thread()
        if self._expected is None or self._frame is not None:
            return False
        source, recipe, request_id, generation, policy, assumption = self._expected
        if (frame.source != source or frame.recipe != recipe
                or frame.request_id != request_id or frame.generation != generation
                or frame.output_size != recipe.result_size or frame.color is None
                or frame.color.policy != policy or frame.color.assume_srgb != assumption):
            return False
        image = preview_qimage(frame)
        self.provider.replace(self._token, image)
        self._frame = frame
        self._url = 'image://editor-preview/' + self._token
        self.changed.emit()
        return True

    def matching_original_measurements(self, result):
        self._owning_thread()
        if self._frame is None or self._expected is None:
            raise ValueError('No current preview.')
        return validate_original_measurements(self._frame, self._expected[1], result)
