"""Find and show 10 working HTTP(S) proxies."""

import asyncio
import json
import traceback
from datetime import datetime
from queue import Queue
from threading import Thread, Lock

import requests

import proxybroker
import logging
log = logging.getLogger(__name__)

stream_handler = logging.StreamHandler()
file_handler = logging.FileHandler('log_{}.log'.format(datetime.now().strftime('%y_%m_%d__%H_%M_%S')))
logging.getLogger('proxybroker').addHandler(file_handler)
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s|%(levelname)-4.4s|%(thread)-6.6s|%(filename)-10.10s|%(funcName)-10.10s|%(message)s',
                    handlers=[stream_handler])


proxies2 = Queue()
async def show(proxies):
    while True:
        try:
            proxy = await proxies.get()
            if proxy is None:
                log.info('Proxy search complete found: %s' % proxies.qsize())
                break
            # log.info('Found proxy: %s (%s)' % (proxy, self.proxies.qsize()))
            proxy._runtimes = proxy._runtimes[:1]
            proxies2.put(proxy)
        except:
            traceback.print_exc()
urls = ['http://skyscanner.ru', 'http://avito.ru', 'https://github.com/',
    'http://skyscanner.com',         'http://httpbin.org/get?show_env',
        'http://azenv.net/', 'https://proxyjudge.info/',
        # 'http://www.proxyfire.net/fastenv', not responding
        'http://proxyjudge.us/azenv.php',
        'http://ip.spys.ru/', 'http://www.proxy-listen.de/azenv.php']
lock = Lock()
results = open('results_{}.json'.format(datetime.now().strftime('%y_%m_%d__%H_%M_%S')), 'w')
TRIES = 3
THREADS = 100

def f():
    while True:
        proxy = proxies2.get()
        print(f'processing {proxy}')
        if proxy is None:
            return
        for i in range(TRIES):
            for url in urls:
                print(f'processing {proxy} {url} {i}')
                try:
                    kwargs = {}
                    kwargs['proxies'] = dict(http='http://%s:%s' % (proxy.host, proxy.port),
                                             https='https://%s:%s' % (proxy.host, proxy.port))
                    kwargs['timeout'] = (10, 20)
                    kwargs['verify'] = False
                    response = requests.get(url=url, **kwargs)
                    if response.headers['content-type'] == 'application/json':
                        response.json()  # avoiding incorrect json even if 200
                    r = str(response.status_code)
                except Exception as e:
                    r = str(e)
                with lock:
                    results.write(json.dumps(dict(url=url, proxy='{}:{}'.format(proxy.host, proxy.port), result=r)))
                    results.write('\n')
                    results.flush()


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

queue = asyncio.Queue()
broker = proxybroker.Broker(queue)
#random.seed()
#random.shuffle(broker._providers)
tasks = asyncio.gather(broker.find(types=[('HTTP', ('Anonymous', 'High'))], limit=400, check=True), show(queue))
loop.run_until_complete(tasks)
running = False

threads = []
for i in range(THREADS):
    t = Thread(target=f)
    t.start()
    proxies2.put(None)
    threads.append(t)
print('Started')
[t.join() for t in threads]
print('Finish')