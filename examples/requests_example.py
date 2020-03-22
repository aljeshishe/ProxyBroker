import threading
import time
from datetime import datetime

from proxybroker import requests

import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s.%(msecs)03d|%(levelname)-4.4s|%(thread)-6.6s|%(funcName)-10.10s|%(message)s',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler('log_{}.log'.format(datetime.now().strftime('%y_%m_%d__%H_%M_%S')))])


threading.Thread._old_start = threading.Thread.start


def start(self):
    self._old_start()
    return self

threading.Thread.start = start


def f():
    while True:
        try:
            resp = requests.request('GET', 'http://avito.ru')
        except Exception as e:
            print(resp.status_code)
threads = [threading.Thread(target=f).start() for i in range(100)]
while True:
    time.sleep(1)