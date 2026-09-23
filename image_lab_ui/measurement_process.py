"""Isolated read-only measurement bridge; shares bounded inspection transport."""
from .metadata_process import main
from .measurement_services import measure_file

if __name__ == '__main__':
    raise SystemExit(main(measure_file))
