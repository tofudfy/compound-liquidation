import time
import json

# from tronpy.abi import trx_abi
from eth_abi import decode
from web3.types import LogReceipt
from typing import Dict, List

from configs.web3_liq import Web3Liquidation
from configs.config import P_ALIAS

COMPOUND_V3_CONFIGS_FILTER_TEMP = """
{
    "address": "",
    "topics": [
        [
            "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316",
            "0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5"
        ]
    ]
}
"""

# todo: emit MarketEntered(cToken, borrower);
"""
NewLiquidationIncentive(oldLiquidationIncentiveMantissa, newLiquidationIncentiveMantissa)
[topic0] 0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316

NewCollateralFactor(cToken, oldCollateralFactorMantissa, newCollateralFactorMantissa)
[topic0] 0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5
"""
EVENT_ABI = {
    "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316": {
        "name": "NewLiquidationIncentive",
        "index_topic": [],
        "data": ["uint256", "uint256"]
    },
    "0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5": {
        "name": "NewCollateralFactor",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    }
}


def gen_comet_filter():
    filt = json.loads(COMPOUND_V3_CONFIGS_FILTER_TEMP)
    filt['address'] = [P_ALIAS['comet']]
    return filt


class CometConfigs(object):
    def __init__(self, liq_incentive: int, closs_factor: int, ctokens_collateral_factor: Dict[str, int], last_update: int):
        self.liq_incentive = liq_incentive
        self.closs_factor = closs_factor
        self.ctokens_collateral_factor = ctokens_collateral_factor
        self.last_update = last_update

    def update(self, log: LogReceipt):
        if log.get('removed', False):
            return

        topic = log['topics'][0].hex()
        obj = EVENT_ABI.get(topic, None)
        if obj is None:
            return

        try:
            data = bytes.fromhex(log['data'][2:])
            args_data = decode(obj['data'], data)
        except Exception as e:
            raise Exception(f'comet update failed: {{"error": {e}, "log":{log}}}')

        if obj['name'] == 'NewLiquidationIncentive':
            new = args_data[1]
            self.liq_incentive = new
            self.last_update = log['blockNumber']

        if obj['name'] == 'NewCollateralFactor':
            new = args_data[2]
            reserve = args_data[0]
            self.ctokens_collateral_factor[reserve] = new
            self.last_update = log['blockNumber']


def init_comet_configs(w3_liq: Web3Liquidation, reserves: List, block_num: int):
    comptroller = w3_liq.gen_comptroller()
    liquidation_incentive = comptroller.functions.liquidationIncentiveMantissa().call()
    closs_factor = comptroller.functions.closeFactorMantissa().call()

    ctokens_cf = {}
    for ctoken_addr in reserves:
        res = comptroller.functions.markets(ctoken_addr).call()
        ctokens_cf[ctoken_addr] = res[1]

    return CometConfigs(liquidation_incentive, closs_factor, ctokens_cf, block_num)


if __name__ == '__main__':
    # print(Web3.sha3(text="NewLiquidationIncentive(uint256,uint256)").hex())
    # print(Web3.sha3(text="NewCollateralFactor(address,uint256,uint256)").hex())
    # print(Web3.sha3(text="ReservesReduced(address,uint256,uint256)").hex())

    w3_liq = Web3Liquidation('http')
    reserves = w3_liq.query_markets_list()
    init_comet_configs(w3_liq, reserves)
