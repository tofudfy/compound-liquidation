from typing import Dict

from web3.types import LogReceipt
from configs.event import EventState, State
from configs.config import P_ALIAS
from configs.web3_liq import Web3Liquidation
from configs.utils import query_events_loop

EVENT_ABI = {   
    "0x002e68ab1600fc5e7290e2ceaa79e2f86b4dbaca84a48421e167e0b40409218a": {
        "name": "MintVAI",
        "index_topic": [],
        "data": ["address", "uint256"]
    },
    "0x1db858e6f7e1a0d5e92c10c6507d42b3dabfe0a4867fe90c5a14d9963662ef7e": {
        "name": "RepayVAI",
        "index_topic": [],
        "data": ["address", "address", "uint256"]
    }
}


class VaiState(State):
    def __init__(self) -> None:
        super().__init__(EVENT_ABI, [P_ALIAS['vai']])

    def write_state_with_return(self, event_name, topics, args) -> Dict:
        res = {}
        if event_name == "MintVAI":
            user = args[0]
            res[user] = 1

        if event_name == "RepayVAI":
            user = args[1]
            res[user] = 1

        return res

    def update(self, log: LogReceipt):
        return super().update(log)


def gen_events_filter_test():
    event_vai_repay = VaiState()
    filt = event_vai_repay.gen_events_filter()
    print(filt)


# example: https://bscscan.com/tx/0xbf7685e661742695595772ebc746880786f5d7e53078984f81abed4b2bbbb5b9
def test():
    w3_liq = Web3Liquidation('http2')

    # init_block_num = 2471745  # https://bscscan.com/tx/0xc4e9998b98921a1d799a9881afd28d01224f0370b632b250ccd649781a310c64
    init_block_num = 27798960
    sta = EventState(VaiState(), init_block_num)

    # target_block_num = w3_liq.w3.eth.get_block_number()
    target_block_num = 27798961
    query_events_loop(w3_liq.w3, sta, sta.state.gen_events_filter(), target_block_num)


if __name__ == '__main__':
   # gen_events_filter_test()
   test()
