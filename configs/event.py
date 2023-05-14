import os
from typing import List, Dict, Any
from web3 import Web3
from web3.types import LogReceipt
from eth_abi import decode
from configs.web3_liq import Web3Liquidation
from configs.utils import query_events_loop, json_write_to_file, json_file_load
from configs.config import P_ALIAS

FILE_RECORD = "users/cmarket_entered.json"
EVENT_ABI = {
    "0x3ab23ab0d51cccc0c3085aec51f99228625aa1a922b3a8ca89a26b0f2027a1a5": {
        "name": "MarketEntered",
        "index_topic": [],
        "data": ["address", "address"]
    },
    "0xe699a64c18b07ac5b7301aa273f36a2287239eb9501d81950672794afba29a0d": {
        "name": "MarketExited",
        "index_topic": [],
        "data": ["address", "address"]
    }
}

class State(object):
    def __init__(self, events: Dict, addres: List) -> None:
        self.storage: Dict = {}
        self.events = events
        self.addres = addres 
    
    def gen_topics(self) -> List:
        return list(self.events.keys())

    def gen_events_filter(self):
        filt = {
            "address": self.addres,
            "topics": [
                self.gen_topics()
            ]
        }
        return filt

    def update(self, log: LogReceipt) -> Dict:
        if log.get('removed', False):
            return []

        topic = log['topics'][0].hex()
        obj = self.events.get(topic, None)
        if obj is None:
            return []

        try:
            data = bytes.fromhex(log['data'][2:])
            args_data = decode(obj['data'], data)  # todo: optimization
        except Exception as e:
            raise Exception(f'update failed: {{"error": {e}, "log":{log}}}')

        return self.write_state_with_return(obj['name'], log['topics'], args_data)

    def write_state_with_return(self, event_name, topics, args):
        pass


class MarkEnterState(State):
    def __init__(self, events: Dict) -> None:
        super().__init__(events)

    def write_state_with_return(self, event_name, topics, args) -> Dict:
        ctoken = args[0]
        user = args[1]

        res = {}
        res[user] = {}
        
        if event_name == "MarketEntered":
            res[user][ctoken] = 1

        if event_name == "MarketExited":
            res[user][ctoken] = -1     
    
        return res
        

class EventState(object):
    def __init__(self, state: Any, last_update) -> None:
        self.last_update = last_update
        self.state: State = state

    def update(self, log: LogReceipt) -> Dict:
        self.state.update(log)


def sync_new_events(w3_liq: Web3Liquidation, states: State):
    w3 = w3_liq.w3
    # block_number = states.last_update + 10000
    block_number = w3.eth.get_block_number()
    filt = states.gen_events_filter() 

    query_events_loop(w3, states, filt, block_number)


def generate_event_signature(event_name: str, param_types: List) -> str:
    # Create the event's function signature
    function_signature = f"{event_name}({','.join(param_types)})"
    
    # Calculate the keccak-256 hash of the signature
    event_hash = Web3.keccak(text=function_signature)
    
    # Return the hash as a hexadecimal string
    return event_hash.hex()


def gen_event_sig():
    # 0x3ab23ab0d51cccc0c3085aec51f99228625aa1a922b3a8ca89a26b0f2027a1a5
    # event_name = "MarketEntered"
    # param_types = ["address", "address"]

    # 0xe699a64c18b07ac5b7301aa273f36a2287239eb9501d81950672794afba29a0d
    # event_name = "MarketExited"
    # param_types = ["address", "address"]
    
    # 0x002e68ab1600fc5e7290e2ceaa79e2f86b4dbaca84a48421e167e0b40409218a
    event_name = "MintVAI"
    param_types = ["address", "uint256"]

    # 0x1db858e6f7e1a0d5e92c10c6507d42b3dabfe0a4867fe90c5a14d9963662ef7e
    # event_name = "RepayVAI"
    # param_types = ["address", "address", "uint256"]
    event_signature = generate_event_signature(event_name, param_types)
    print(event_signature)


def event_state_load(path: str, file: str, events: Dict, event_addres):
    try:
        data_load = json_file_load(path + os.sep + file)
        state = State(events, event_addres)
        state.storage = data_load['data']
        last_update = data_load['lastUpdate']
    except:
        state = State(events, event_addres)
        last_update = P_ALIAS['init_block_number']

    return EventState(state, last_update)


def main():
    web3_liq = Web3Liquidation('http2')
    current_file = os.path.abspath(__file__)
    current_path = os.path.dirname(current_file)
    record_file = FILE_RECORD

    event_addres = ["0xfD36E2c2a6789Db23113685031d7F16329158384"]
    event_state = event_state_load(current_path, record_file, EVENT_ABI, event_addres)
    sync_new_events(web3_liq, event_state)

    json_write_to_file({
        "data": event_state.state.storage,
        "lastUpdate": event_state.last_update,
    }, current_path, record_file)


if __name__ == '__main__':
    main()
    # gen_event_sig()
