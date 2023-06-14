import os
from typing import List, Dict, Any
from eth_abi import decode
from configs.web3_liq import Web3Liquidation
from configs.utils import json_write_to_file
from configs.config import P_ALIAS
from configs.event import State, generate_event_signature, sync_new_events, event_state_load

FILE_RECORD = "users/failover_activated.json"
EVENT_ABI = {
    "0xdd0f1f4e105bf96c7d8e2defcbbc958075661165b324633175ca26f08a11f4b4": {
        "name": "FailoverActivated",
        "index_topic": ["bytes32"],
        "data": []
    },
    "0x5a1062b4c89c41b46f5e2da710d564c88989bfe1b4e856dbdbc40c5c59a2ce4b": {
        "name": "FailoverDeactivated",
        "index_topic": ["bytes32"],
        "data": []
    },  
}


class FailoverActivatedState(State):
    def __init__(self, events: Dict) -> None:
        super().__init__(events)

    def write_state_with_return(self, event_name, topics, args) -> Dict:
        res = {}
        if event_name == "FailoverActivated":
            symbol_hash = topics[1].hex()
            res[symbol_hash] = 1

        if event_name == "FailoverDeactivated":
            symbol_hash = topics[1].hex()
            res[symbol_hash] = 0

        print(res)
        return res


def gen_event_sig():
    """
    https://etherscan.io/address/0x50ce56A3239671Ab62f185704Caedf626352741e#code
    event FailoverActivated(bytes32 indexed symbolHash);
    """
    # 0xdd0f1f4e105bf96c7d8e2defcbbc958075661165b324633175ca26f08a11f4b4
    # event_name = "FailoverActivated"
    # param_types = ["bytes32"]

    # 0x5a1062b4c89c41b46f5e2da710d564c88989bfe1b4e856dbdbc40c5c59a2ce4b
    event_name = "FailoverDeactivated"
    param_types = ["bytes32"]
    event_signature = generate_event_signature(event_name, param_types)
    print(event_signature)


def main():
    web3_liq = Web3Liquidation('http_local')
    current_file = os.path.abspath(__file__)
    current_path = os.path.dirname(current_file)
    record_file = FILE_RECORD

    event_addres = ["0x50ce56A3239671Ab62f185704Caedf626352741e"]
    event_state = event_state_load(current_path, record_file, EVENT_ABI, event_addres)
    try:
        sync_new_events(web3_liq, event_state)
    except:
        pass  # todo

    json_write_to_file({
        "data": event_state.state.storage,
        "lastUpdate": event_state.last_update,
    }, current_path, record_file)


if __name__ == '__main__':
    main()
    # gen_event_sig()
