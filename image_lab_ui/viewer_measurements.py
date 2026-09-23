"""Latest-source/load-only measurements; no saved predictions or edited rasters."""
import os
import sys

from .measurement_services import validate_measurement_view
from .viewer_metadata import ViewerMetadata


class ViewerMeasurements(ViewerMetadata):
    def _validate_view(self, view):
        result = validate_measurement_view(view)
        if not result['error']:
            revision = result['source']['revision']
            if self._key is None or (revision[3], revision[2]) != (self._key[2], self._key[3]):
                raise ValueError('Measurement source revision does not match the requested load')
        return result

    def __init__(self, parent=None, *, worker_command=None, deadline_ms=35000):
        super().__init__(parent, worker_command=worker_command or (
            sys.executable, '-m', 'image_lab_ui.measurement_process', str(os.getpid())),
            deadline_ms=deadline_ms)

    def complete(self, generation, result):
        result = dict(result)
        if result.get('error'):
            result['error'] = result['error'].replace('Metadata', 'Measurement').replace('metadata', 'measurement')
            result['errorCode'] = result.get('errorCode', '').replace('metadata_', 'measurement_', 1)
        super().complete(generation, result)
