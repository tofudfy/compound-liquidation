import csv
import time

from configs.web3_liq import Web3Liquidation
from scripts.analysis_competitors import BNB48
from scripts.analysis_utils import unix_to_readable

OUTPUT = './outputs/validators.csv'


# https://bscscan.com/address/0x5cc05fde1d231a840061c1a2d7e913cedc8eabaf#readContract
def validators_rotation_test():
    w3_liq = Web3Liquidation()

    block_start = 28780000
    block_end = block_start + 20000 

    with open(OUTPUT, 'w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["index", "time", "validator", "bnb48"])

        for block_num in range(block_start, block_end, 1):
            block = w3_liq.w3.eth.get_block(block_num)
            index = block['number']
            block_time = unix_to_readable(block['timestamp'])
            validator = block['miner']

            if validator in BNB48:
                is_bnb48 = True
            else:
                is_bnb48 = False

            csv_writer.writerow([index, block_time, validator, is_bnb48])
            time.sleep(0.1)


def get_validators_set():
    w3_liq = Web3Liquidation()
    block_num = 28791915
    block = w3_liq.w3.eth.get_block(block_num)
    print(block)
 

if __name__ == '__main__':
    # validators_rotation_test()
    get_validators_set()
