try:
    from ._version import version as __version__
except ImportError:
    # Fallback for development without tags
    __version__ = "0.0.0.dev0"

from cellar_extractor.cellar import get_cellar
from cellar_extractor.cellar import get_cellar_extra
from cellar_extractor.cellar import get_nodes_and_edges_lists
from cellar_extractor.cellar import filter_subject_matter
from cellar_extractor.operative_extractions import FetchOperativePart
from cellar_extractor.operative_extractions import Writing
import logging

logging.basicConfig(level=logging.INFO)
