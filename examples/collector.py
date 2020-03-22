"""Find and show 10 working HTTP(S) proxies."""

import asyncio
import json
import pathlib
import traceback
from contextlib import closing
from datetime import datetime
from queue import Queue
from threading import Thread, Lock
import logging.config
import requests

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
            'class': 'logging.FileHandler',
            'filename': 'logs/proxybroker_%s.log' % datetime.now().strftime("%d%m%y_%H%M%S"),
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
            'handlers': ['file_handler'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'proxied_requests': {
            'handlers': ['file_handler'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'requests': {
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

proxies2 = []
async def show(proxies):
    while True:
        try:
            proxy = await proxies.get()
            if proxy is None:
                log.info('Proxy search complete found: %s' % len(proxies2))
                break
            # log.info('Found proxy: %s (%s)' % (proxy, self.proxies.qsize()))
            proxy._runtimes = proxy._runtimes[:1]
            proxies2.append(proxy)
        except:
            traceback.print_exc()

lock = Lock()
TRIES = 3
THREADS = 100
name = 'results_{}'.format(datetime.now().strftime('%y_%m_%d__%H_%M_%S'))

for i in range(3):
    with closing(asyncio.new_event_loop()) as loop:
        asyncio.set_event_loop(loop)

        queue = asyncio.Queue()
        broker = proxybroker.Broker(queue)
        #random.seed()
        #random.shuffle(broker._providers)
        tasks = asyncio.gather(broker.find(types=[('HTTP', ('Anonymous', 'High'))],
                                           limit=100,
                                           # data=[('189.127.106.16', '53897')],
                                           check=True),
                               show(queue))
        loop.run_until_complete(tasks)
        broker.show_stats(verbose=True)
        with open(name, 'a') as fp:
            for proxy in proxies2:
                fp.write('{}\n'.format(proxy))
            fp.write('\n')
            fp.flush()

        loop.stop()
print('Finish')