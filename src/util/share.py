from src.util.logging import Logger
from src.data.config import *

__all__ = ('share', 'logger',)

share = {
    'server': None,
    'server_version': 1,
    'version': '1.16.4',
    'protocol': 754,
    'timeout': .15,
    'rsa': {
        'private': None,
        'public': None
    },
    'conf': SERVER_PROPERTIES,
    'favicon': FAVICON,
    'ses': None,
    'states': {},  # {remote: state_id}
    'comp_thresh': SERVER_PROPERTIES['comp_thresh']
}

logger = Logger()