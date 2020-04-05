"""Find and show 10 working HTTP(S) proxies."""

import asyncio
import json
import os
import pathlib
import time
from _signal import SIGINT, SIGTERM
from asyncio import CancelledError
from contextlib import closing, contextmanager, suppress
from datetime import datetime
import logging.config
import logging.handlers

from aiofile import AIOFile, Writer

import proxybroker
import logging

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
            'filename': 'logs/proxybroker_%s.log' % datetime.now().strftime("%d%m%y_%H%M%S"),
            'maxBytes': 1024*1024*200,
            'backupCount': 5,
            'formatter': 'verbose',
            'mode': 'w',
            'encoding': 'utf8',
        },
        'console_handler': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'proxybroker': {
            'handlers': ['file_handler', 'console_handler'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'chardet': {
            'handlers': ['file_handler', 'console_handler'],
            'level': 'INFO',
            'propagate': False,
        },
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

@contextmanager
def context(verbose=True, message='', **kwargs):
    kwargs_str = ' '.join(map(lambda i: f'{i[0]}={i[1]}', kwargs.items()))
    if verbose:
        log.info(f'{message} {kwargs_str}')
    try:
        yield None
        if verbose:
            log.info(f'Finished {message} {kwargs_str}')
    except Exception as e:
        log.exception(f'Exception while {message} {kwargs_str}')


queue = asyncio.Queue()
broker = proxybroker.Broker(queue, max_conn=1000)


def collect():
    async def show(queue):
        with context(verbose=True, message='getting proxies in show'):
            temp_file_name = 'data.json.tmp'
            file_name = 'data.json'
            async with AIOFile(temp_file_name, 'w') as tmp_f, AIOFile(file_name, 'a') as f:
                tmp_fp_eriter = Writer(tmp_f)
                fp_writer = Writer(f)
                while True:
                    proxy = await queue.get()
                    if proxy is None:
                        break
                    data = json.dumps(proxy.as_json())
                    await tmp_fp_eriter(f'{data}\n')
                    await tmp_f.fsync()
                    await fp_writer(f'{data}\n')
                    await f.fsync()
            log.info(f'Finished writing results. Renaming {temp_file_name} to {file_name}')
            os.rename(temp_file_name, file_name)

    broker._providers = broker._providers[:2]
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    tasks = asyncio.gather(broker.find(types=['HTTP', 'HTTPS'],  # [('HTTP', ('Anonymous', 'High'))]
                                       limit=0,
                                       check=True),
                           show(queue))
    with suppress(CancelledError):
        loop.run_until_complete(tasks)


if __name__ == '__main__':
    # from dowser.utils import launch_memory_usage_server
    # launch_memory_usage_server()

    collect()