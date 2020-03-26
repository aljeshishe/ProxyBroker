"""Find and show 10 working HTTP(S) proxies."""

import asyncio
import json
import pathlib
import threading
import time
import traceback
from _signal import SIGINT, SIGTERM
from collections import deque
from contextlib import closing, contextmanager
from datetime import datetime
from queue import Queue
from threading import Thread, Lock
import logging.config


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
            'level': 'DEBUG',
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


class FifoQueue(Queue):

    def all(self):
        with self.mutex:
            return self.queue

    def enable_limit(self):
        with self.mutex:
            self.queue = deque(self.queue, maxlen=len(self.queue))

proxies = FifoQueue()


def collect():

    async def show(queue):
        global proxies
        with context(verbose=True, message='getting proxies in show'):
            while True:
                proxy = await queue.get()
                if proxy is None:
                    proxies.enable_limit()
                    break
                proxies.put(proxy)

    def shutdown():
        # loop.stop()
        for task in asyncio.all_tasks():
            task.cancel()

    while True:
        try:
            with closing(asyncio.new_event_loop()) as loop:
                asyncio.set_event_loop(loop)
                loop.add_signal_handler(SIGINT, shutdown)
                loop.add_signal_handler(SIGTERM, shutdown)

                queue = asyncio.Queue()
                broker = proxybroker.Broker(queue)
                #random.seed()
                #random.shuffle(broker._providers)
                tasks = asyncio.gather(broker.find(types=[('HTTP', ('Anonymous', 'High'))],
                                                   limit=300,
                                                   check=True),
                                       show(queue))
                loop.run_until_complete(tasks)
                broker.show_stats(verbose=True)
                loop.stop()
                time.sleep(3)
        except asyncio.exceptions.CancelledError:
            return
        except Exception:
            log.exception('Exception while finding proxies')


from bottle import route, run, response, ServerAdapter, Bottle


class MyWSGIRefServer(ServerAdapter):
    server = None

    def run(self, handler):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        if self.quiet:
            class QuietHandler(WSGIRequestHandler):
                def log_request(*args, **kw): pass
            self.options['handler_class'] = QuietHandler
        self.server = make_server(self.host, self.port, handler, **self.options)
        self.server.serve_forever()

    def stop(self):
        # self.server.server_close() <--- alternative but causes bad fd exception
        self.server.shutdown()

@route('/proxies')
def hello():
    global proxies
    response.headers['Content-Type'] = 'application/json'
    return json.dumps([dict(host=p.host, port=p.port, provider=p.provider, type=p.types) for p in proxies.all()])


log.info('Started')

app = Bottle()
server = MyWSGIRefServer(host='localhost', port=8080)

t = threading.Thread(target=lambda: app.run(server=server))
t.start()
collect()
server.stop()
t.join()
log.info('Finished')