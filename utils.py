import asyncio
import json
from websockets import connect

from configs.config import CONNECTION, NETWORK, INTVL
from configs.web3_liq import Web3Liquidation

async def polling_full(w3_liq: Web3Liquidation, filt, callback):
    while True:
        w3 = w3_liq.w3
        event_filter = w3.eth.filter(filt)
        while True:
            try:
                events = event_filter.get_new_entries()
            except Exception as e:
                await asyncio.sleep(2)
                # logger.error("In users: {}".format(e))
                break

            if len(events) != 0:
                callback(events)
            # logger.error("In users: {}".format(e))
            await asyncio.sleep(INTVL)


class WSconnect(object):
    def __init__(self, url: str, headers=None) -> None:
        self.url = url
        self.headers = headers


async def subscribe_event_light(filt, callback):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'receipts',
        'event_filter': filt
    })
    ws = WSconnect(CONNECTION[NETWORK]['light']['url'], {'auth': CONNECTION[NETWORK]['light']['auth']})
    subscribe_to_node(ws, sub_infos, callback)


async def subscribe_tx_light(filt, callback):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'txpool',
        'tx_filters': filt
    })
    ws = WSconnect(CONNECTION[NETWORK]['light']['url'], {'auth': CONNECTION[NETWORK]['light']['auth']})
    subscribe_to_node(ws, sub_infos, callback)


async def subscribe_to_node(ws: WSconnect, sub_infos: str, callback):
    async with connect(ws.url, ping_interval=None, extra_headers=ws.headers) as ws:
        await ws.send(sub_infos)

        subscription_response = await ws.recv()
        print(subscription_response)

        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=None)
            except:
                break

            response = json.loads(response)
            callback(response)
