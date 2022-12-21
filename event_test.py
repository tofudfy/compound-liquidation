import json
import asyncio

from web3 import Web3

from configuration import (
    provider,
    query_markets_list
)
from get_users_from_logs import (
    COMPOUND_V3_USERS_FILTER_TEMP,
    log_parser_wrap
)


async def users_subscribe_full(callback):
    filt = json.loads(COMPOUND_V3_USERS_FILTER_TEMP)
    filt['address'] = query_markets_list()

    while True:
        w3 = Web3(provider)
        event_filter = w3.eth.filter(filt)
        print(provider, filt)
        while True:
            try:
                events = event_filter.get_new_entries()
            except Exception as e:
                break

            if len(events) != 0:
                callback(events)
            await asyncio.sleep(24)


if __name__ == '__main__':
    asyncio.run(users_subscribe_full(log_parser_wrap))
