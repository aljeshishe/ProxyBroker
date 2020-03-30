import json
import logging
import logging.config
import logging.handlers
import pathlib
import threading
from datetime import datetime

from bottle import route, run, response, ServerAdapter, Bottle, app


@route('/')
def hello():
    with open('data.json') as fp:
        response.headers['Content-Type'] = 'application/json'
        lines = ','.join([line.strip() for line in fp])
        return f'[{lines}]'


log_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s.%(msecs)03d|%(levelname)-4.4s|%(thread)-6.6s|%(module)-6.6s|%(funcName)-10.10s|%(message)s',
            'datefmt': '%Y/%m/%d %H:%M:%S',
        },
    },
    'handlers': {
        'file_handler': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/server%s.log' % datetime.now().strftime("%d%m%y_%H%M%S"),
            'maxBytes': 1024*1024*200,
            'backupCount': 5,
            'formatter': 'verbose',
            'mode': 'w',
            'encoding': 'utf8',
        },
        'console_handler': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'urllib3': {
            'handlers': ['file_handler', 'console_handler'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['file_handler', 'console_handler'],
        'level': 'DEBUG',
        'propagate': False,
    }
}
pathlib.Path('logs').mkdir(parents=True, exist_ok=True)
logging.config.dictConfig(log_config)
log = logging.getLogger(__name__)

log.info('Started')
run(host='0.0.0.0', port=8080, debug=True)
log.info('Finished')
