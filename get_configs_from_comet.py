
from tronpy.abi import trx_abi
from web3 import Web3
from configuration import (
    log_v2, provider, cerc20_interface, get_reserves
)

collateral_factor = {}
liquidation_incentive = 0

COMPOUND_V3_CONFIGS_FILTER_TEMP = """
{
    "address": "",
    "topics": [
        [
            "0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5",
            "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316"
        ],
        []
    ]
}
"""

"""
NewCollateralFactor(cToken, oldCollateralFactorMantissa, newCollateralFactorMantissa)
[topic0] 

NewLiquidationIncentive(oldLiquidationIncentiveMantissa, newLiquidationIncentiveMantissa)
[topic0] 
"""
EVENT_ABI = {
    "0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5": {
        "name": "NewCollateralFactor",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    },
    "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316": {
        "name": "NewLiquidationIncentive",
        "index_topic": [],
        "data": ["uint256", "uint256"]
    }
}


def comet_configs_init():
    # global liquidation_incentive
    w3 = Web3(provider)

    reserves = get_reserves()
    for token_addr in reserves:
        token_contract = w3.eth.contract(address=token_addr, abi=cerc20_interface['abi'])
        collateral_factor[token_addr] = token_contract.functions.reserveFactorMantissa().call()

    log_v2.debug("comet configs init: {}".format(collateral_factor))
    # todo: getStorageAt?
    # liquidation_incentive = 0


def comet_configs_log_parser_wrap(logs):
    num_list = []
    for log in logs:
        log_parser(log)
        if len(num_list) == 0:
            num_list.append(log['blockNumber'])

        if log['blockNumber'] != num_list[-1]:
            num_list.append(log['blockNumber'])

    log_v2.info("comet configs updated, block number: {}".format(num_list))


def log_parser(log):
    if log['removed']:
        log_v2.info("log is removed {}".format(log))
        return

    topic = log['topics'][0].hex()
    obj = EVENT_ABI.get(topic, None)
    if obj is None:
        log_v2.error("unexpected topics in get users: {}".format(log))
        return

    try:
        data = bytes.fromhex(log['data'][2:])
        args_data = trx_abi.decode(obj['data'], data)
    except Exception as e:
        log_v2.error(e)
        return

    if obj['name'] == 'NewCollateralFactor':
        new = args_data[2]
        reserve = '0x' + trx_abi.encode_single("address", args_data[0]).hex()[24:]
        collateral_factor[reserve] = new
        log_v2.debug("new collateral factor of reserve {} updated: {}".format(reserve, collateral_factor))
    
    if obj['name'] == 'NewLiquidationIncentive':
        global liquidation_incentive
        new = args_data[1]
        liquidation_incentive = new
        log_v2.debug("new liquidation inventive updated: {}".format(users_raw['liq_incentive']))


def get_collateral_factor(reserve):
    return collateral_factor[reserve]


def get_liquidation_incentive():
    return liquidation_incentive


if __name__ == '__main__':
    print(Web3.sha3(text="NewLiquidationIncentive(uint256,uint256)").hex())
    print(Web3.sha3(text="NewCollateralFactor(address,uint256,uint256)").hex())
    print(Web3.sha3(text="ReservesReduced(address,uint256,uint256)").hex())
