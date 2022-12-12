
from tronpy.abi import trx_abi
from web3 import Web3
from configuration import (
    COMPOUND_ALIAS, log_v2, comptroller,
    json_file_load
)

COMET_CONFIGS_PATH_RECORD = COMPOUND_ALIAS['comet_configs_file']
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

collateral_factor_full = json_file_load(COMET_CONFIGS_PATH_RECORD)
collateral_factor = collateral_factor_full['reserves'] 
liquidation_incentive = 0


def comet_configs_init():
    global liquidation_incentive
    liquidation_incentive = comptroller.functions.liquidationIncentiveMantissa().call()
    log_v2.debug("comet configs init: {{\"liquidationIncentive\": {}, \"reserveFactor\": {}}}".
                format(liquidation_incentive, collateral_factor))


def comet_configs_log_parser_wrap(logs):
    num_list = []
    for log in logs:
        comet_log_parser(log)
        if len(num_list) == 0:
            num_list.append(log['blockNumber'])

        if log['blockNumber'] != num_list[-1]:
            num_list.append(log['blockNumber'])

    log_v2.info("comet configs updated, block number: {}".format(num_list))


def comet_log_parser(log):
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
        log_v2.debug("new collateral factor of reserve {} updated: {}, height: {}".format(reserve, collateral_factor[reserve], log['blockNumber']))
    
    if obj['name'] == 'NewLiquidationIncentive':
        global liquidation_incentive
        new = args_data[1]
        liquidation_incentive = new
        log_v2.debug("new liquidation inventive updated: {}, height: {}".format(liquidation_incentive, log['blockNumber']))


def get_collateral_factor(reserve):
    return collateral_factor[reserve]


def get_collateral_lastupdate():
    return collateral_factor_full['last_update']


def get_collateral_factor_dict():
    return collateral_factor_full


def get_liquidation_incentive():
    return liquidation_incentive


if __name__ == '__main__':
    # print(Web3.sha3(text="NewLiquidationIncentive(uint256,uint256)").hex())
    # print(Web3.sha3(text="NewCollateralFactor(address,uint256,uint256)").hex())
    # print(Web3.sha3(text="ReservesReduced(address,uint256,uint256)").hex())

    comet_configs_init()
    print(get_collateral_factor_dict())
