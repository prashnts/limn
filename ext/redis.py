
import redis
import json
from pydantic import BaseModel
from typing import Callable

db = redis.Redis(host='localhost', port=6379, db=0)

def publish(channel: str, action: str, payload: dict = {}):
    db.publish(channel, json.dumps({'_action': action, **payload}))

class PubSubMessage(BaseModel):
    action: str
    payload: dict | None

class UniqInstance(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        key = (cls, args, tuple(kwargs.items()))
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]


class PubSubManager(metaclass=UniqInstance):
    def __init__(self):
        self.pubsub = db.pubsub()
        self.pubsub.psubscribe(**{'limn.*': self.handle_message})
        self.pubsub.run_in_thread(sleep_time=0.1, daemon=True)
        self.subscribers = {}

    def handle_message(self, message):
        if not message or message['type'] != 'pmessage':
            return

        channel_name = message['channel'].decode()
        try:
            data = json.loads(message['data'].decode())
            action = data['_action']
            del data['_action']
            payload = data
            msg = PubSubMessage(action=action, payload=payload)
        except KeyError:
            return

        for channels, callback in self.subscribers.values():
            if channel_name in channels:
                try:
                    callback(channel_name, msg)
                except Exception as e:
                    print(f'[PubSub] Error in callback: {e}')

    def attach(self, uid: str, channels: tuple[str], callback: Callable):
        if uid not in self.subscribers:
            self.subscribers[uid] = (channels, callback)
        return self
