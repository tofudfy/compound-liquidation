import os
from web3 import Web3
from web3.middleware import geth_poa_middleware
from web3.types import TxReceipt, BlockData
from analysis_utils import line_json_parser, line_time_parser, convert_tar_to_pattern, unix_time_ms
from configs.config import load_provider

PREFIX = "./"


def read_and_parse_from_folder(path, match_file, target_line, log_filter):
    files= os.listdir(path)
    files.sort()

    res = []
    for file in files:
        f = path + file
        if os.path.isdir(f):
            continue

        if not match_file in file:
            continue
    
        print("read file ", f)
        res += read_and_parse(f, target_line, log_filter)

    return res


def read_and_parse(file, target, log_filter):
    f = open(file)
    iter_f = iter(f)

    targets = [
        target
    ]
    patterns = convert_tar_to_pattern(targets)

    res = []
    for line in iter_f:
        if line.find(targets[0]) > -1:
            block_num, hash, time_stamp = log_filter(line, patterns[0])
            res.append([hash, block_num, time_stamp])

    return res


def log_parser_pending_tx(line, p):
    res_js = line_json_parser(line, p)
    date = line_time_parser(line)

    block_num = res_js.get('height', 0)
    tx_hash = res_js['hash']
    return block_num, tx_hash, date


def analysis_onchain_plus1():
    w3 = Web3(load_provider('http_local'))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    results = read_and_parse_from_folder(PREFIX, "liquidation_bsc_compound", "new message received: ", log_parser_pending_tx)
    for r in results:
        try:
            tx_hash = r[0]
            tx_recpt: TxReceipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            print(f'get transaction "{tx_hash}" error: {e}')
            continue

        onchain_block_num = tx_recpt['blockNumber']
        onchain_status = tx_recpt['status']
        if not onchain_status:
            continue

        onchain_block: BlockData = w3.eth.get_block(tx_recpt['blockNumber'])
        onchain_block_time = onchain_block['timestamp']

        local_height = r[1]
        local_date = r[2]
        local_time = unix_time_ms(local_date)
        print(f'result:{{"txHash":"{tx_hash}", "date": {local_date}, "block_delay": {onchain_block_num-local_height}, "time_delay":{onchain_block_time-local_time}}}')


if __name__ == '__main__':
    analysis_onchain_plus1()
