import os
from typing import Dict
from web3 import Web3
from web3.types import LogReceipt
from configs.event import EventState, State, generate_event_signature
from configs.utils import query_events_loop
from configs.config import ADDRESS_ZERO
from analysis_utils import unix_to_readable, unix_time, unix_to_readable, write_file, convert_tar_to_pattern, is_hex_string, line_json_parser

"""
event Unwrap(uint256 amount, uint256 chainId);
event Swap(address token, uint256 amount);
event Mint(address to,uint256 amount,address feeAddress,uint256 feeAmount,bytes32 originTxId);
"""
EVENT_ABI = {
    "0x37a06799a3500428a773d00284aa706101f5ad94dae9ec37e1c3773aa54c3304": {
        "name": "Unwrap",
        "index_topic": [],
        "data": ['uint256','uint256']
    },
    "0x562c219552544ec4c9d7a8eb850f80ea152973e315372bf4999fe7c953ea004f": {
        "name": "Swap",
        "index_topic": [],
        "data": ['address','uint256']
    },
    "0x918d77674bb88eaf75afb307c9723ea6037706de68d6fc07dd0c6cba423a5250": {
        "name": "Mint",
        "index_topic": [],
        "data":  ['address','uint256','address','uint256','bytes32']
    },
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef": {
        "name": "Transfer",
        "index_topic": ["address", "address"],
        "data":  ['uint256']     
    }
}

CONTRACTS = ["0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB"]  # WETH.e on Avalanche
PREFIX = "./"


class WethState(State):
    def __init__(self) -> None:
        super().__init__(EVENT_ABI, CONTRACTS)

    def write_state_with_return(self, event_name, topics, args) -> str:
        res = ""
        if event_name == "Transfer":
            sender = '0x' + topics[1].hex()[26:]
            receiver = '0x' + topics[2].hex()[26:] 
            res = f'Transfer: {{"sender":"{sender}", "receiver":"{receiver}", "token":"{"WETH.e"}", "amount":{args[0]}}}'
        elif event_name == "Unwrap":
            res = f'Unwrap: {{"sender":"{""}", "receiver":"{""}", "token":"{"WETH.e"}", "amount":{args[0]}, "chainId":{args[1]}}}'
        elif event_name == "Swap":
            res = f'Swap: {{"sender":"{""}", "receiver":"{""}", "token":"{args[0]}", "amount":{args[1]}}}'
        elif event_name == "Mint": 
            to, amount, fee_addr, fee_amount, data = args
            res = f'Mint: {{"sender":"{ADDRESS_ZERO}", "receiver":"{to}", "token":"{"WETH.e"}", "amount":{amount}, "eth_tx":"{data.hex()}", "relayer":"{fee_addr}", "incentive":{fee_amount}}}'

        return res

    def update(self, log: LogReceipt) -> Dict:
        res = super().update(log)
        res = res[:-1] + f'{{, "hash":"{log["transactionHash"].hex()}", "height":{log["blockNumber"]}}}'[1:]
        print(res)


def read_and_parse_from_folder(path, match_file, targets_line, log_filter):
    res = {}
    files = os.listdir(path)
    files.sort()
    for file in files:
        f = path + file
        if os.path.isdir(f):
            continue

        if not match_file in file:
            continue

        print("read file ", f)
        res = read_and_parse(f, targets_line, log_filter)

    return res


def read_and_parse(file, targets, log_filter):
    f = open(file)
    iter_f = iter(f)

    patterns = convert_tar_to_pattern(targets)

    res = {}
    for line in iter_f:
        for i in range(len(targets)):
            if line.find(targets[i]) > -1:
                # patch
                s = line.find("}. Log infos: {")
                e = s + 15 + 74
                line = line[:s] + ", " + line[e:]

                sender, receiver, amount, blocknum = log_filter(line, patterns[i])

                if sender == ADDRESS_ZERO:
                    res[blocknum] = res.get(blocknum, 0) + amount
                
                if receiver == ADDRESS_ZERO:
                    res[blocknum] = res.get(blocknum, 0) - amount
    
    return res
                

def parser(line, p):
    res_js = line_json_parser(line, p)

    sender = res_js['sender']
    receiver = res_js['receiver']
    amount = res_js['amount']/10**18
    blocknum = res_js['height'] 

    return sender, receiver, amount, blocknum


def analysis():
    res = read_and_parse_from_folder(PREFIX, "weth.log", ["Transfer: "], parser)
    print(res)


def main():
    urls = [
        "https://avalanche-mainnet.infura.io/v3/261ab88ba59c46b6b030d7633cadb732",
        "https://wandering-twilight-theorem.avalanche-mainnet.discover.quiknode.pro/ca96ea41895cba180799d0ba7502d083f10adc5c/",
        "https://avalanche-mainnet.infura.io/v3/093ab6c6601f45a399e5e1100cc42125"
    ]

    # init_block_num = 2749895  # https://snowtrace.io/tx/0x08032322438a227b61a7eb7bc35159a89409ab0483c13e8454467fcbdf35e5e1
    # target_block_num = w3.eth.get_block_number()
    init_block_num = 7644398  # Dec-01-2021 12:00:01 AM +UTC
    target_block_num = 15437116 # Jun-01-2022 12:00:00 AM +UTC
    sta = EventState(WethState(), init_block_num)

    for url in urls:
        provider = Web3.HTTPProvider(url)
        w3 = Web3(provider)
        try:
            query_events_loop(w3, sta, sta.state.gen_events_filter(), target_block_num)
        except Exception as e:
            print(f'{url} Error: {e}')
            continue


if __name__ == '__main__':
    '''
    event_signature = generate_event_signature("Unwrap", ['uint256','uint256'])
    print(event_signature)

    event_signature = generate_event_signature("Swap", ['address','uint256'])
    print(event_signature)

    event_signature = generate_event_signature("Mint", ['address','uint256','address','uint256','bytes32'])
    print(event_signature)
    '''

    main()
    # analysis()
 