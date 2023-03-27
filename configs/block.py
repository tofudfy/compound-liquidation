from web3.middleware import geth_poa_middleware
from web3.types import BlockData

from configs.config import INTVL
from configs.web3_liq import Web3Liquidation


class BlockInfos(object):
    def __init__(self, block_num: int, block_time: int, base_fee: int):
        self.block_num = block_num
        self.block_time = block_time
        self.base_fee = base_fee
        self.gas_price = 0

    def update_block(self, new_block_num: int, new_block_time: int):
        self.block_num = new_block_num
        self.block_time = new_block_time

    def update(self, block_num: int, block_time: int, base_fee: int, gas_price: int):
        self.block_num = block_num
        self.block_time = block_time
        self.base_fee = base_fee
        self.gas_price = gas_price

    # given `block_num` to simulate `block_time` locally
    def get_current_timestamp(self, current_block_num):
        if current_block_num == self.block_num:
            return self.block_time

        delt = current_block_num - self.block_num
        if delt > 10:
            pass

        return self.block_time + INTVL * delt

    # given `block_time` to simulate `block_num` locally
    def get_blocknum_by_timestamp(self, current_time):
        if current_time == self.block_time:
            return self.block_num

        return (current_time - self.block_time)//INTVL + self.block_num


def init_block_infos(w3_liq: Web3Liquidation) -> BlockInfos:
    w3 = w3_liq.w3
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    block: BlockData = w3.eth.get_block('latest')
    block_num = block['number']
    block_time = block['timestamp']
    base_fee = block['baseFeePerGas']
    return BlockInfos(block_num, block_time, base_fee)
