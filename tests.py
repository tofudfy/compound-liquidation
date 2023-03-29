import json
from web3 import Web3
from hexbytes import HexBytes

from types_liq import LogReceiptLight, converter
from configs.web3_liq import Web3Liquidation
from configs.config import RESERVES
from configs.signals import Signals, AggregatorInfos, complete_ctokens_price_info
from configs.block import BlockInfos
from configs.comet import CometConfigs, init_comet_configs
from configs.users import backtesting_states
from compound import calculate_health_factor, liquidation_simulation

SIGNAL_MESSAGE = {'type': '0x0', 'nonce': '0x133798a', 'gasPrice': '0x78ace58d37', 'maxPriorityFeePerGas': None, 'maxFeePerGas': None, 'gas': '0x7a120', 'value': '0x0', 'input': '', 'v': '0x135', 'r': '0xe2611d8e66e2886d4fe9a3ec66a42fa9f4d541c372cf138972f0483e4f04efd4', 's': '0x52d45d82218390ac665912ec9ee85a71636e411955c8b01a035792dfb7cffd3', 'to': '0xc6d82423c6f8b0c406c1c34aee8e988b14d5f685', 'hash': '0xd845e76f1f20ec68ff18190be6bb7186731f9a9ec6c52332d0b3ecc0362c3a69', 'from': '0x250abd1d4ebc8e70a4981677d5525f827660bde4'}


def subscribe_test(callback):
    response = """
    {
        "events":[
            {
                "address": "0x7fabdd617200c9cb4dcf3dd2c41273e60552068a",
                "topics": [
                    "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316"
                ],
                "txIndex":44,
                "data": "0x",
                "transactionHash": "0x"
            }
        ],
        "blockNumber": 234,
        "blockHash": "0x",
        "type": "events",
        "id": "123"
    }
    """
    resp = json.loads(response)
    callback(resp)


def subscribe_callback(response: LogReceiptLight):
    block_num = response['blockNumber']
    block_hash = response['blockHash']
    logs = converter(response)
    comet = CometConfigs(0, 0, {}, 0)

    for log in logs:
        comet.update(log)


def cal_users_states_test():
    w3_liq = Web3Liquidation('http')
    block_num = 16883307 - 1  # liquidation height
    user = "0x5094B1E462730711C2d5227D7d8fF9A6e67F50E2"

    comet = w3_liq.gen_comptroller()
    res = comet.functions.getAccountLiquidity(user).call(block_identifier=block_num)
    print(res)

    # reserves = w3_liq.query_markets_list(block_num)
    reserves = RESERVES
    states = backtesting_states(w3_liq, user, reserves, block_num)

    reserves_trim = list(states.users_states[user].reserves.keys())
    comet = init_comet_configs(w3_liq, reserves_trim)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_trim, block_num)

    # health factor simulate before liquidation
    calculate_health_factor(user, states.users_states[user].reserves, states.ctokens, comet)

    # liquidation simulate
    collaterals, debt = liquidation_simulation(states.users_states[user].reserves, states.ctokens, comet)
    liquidation_params = [collaterals[0][1], debt[1], user, collaterals[0][3], False]
    seized = collaterals[0][2]
    revenue = collaterals[0][0] / 10**18
    print(liquidation_params, revenue, seized)


if __name__ == '__main__':
    # subscribe_test(subscribe_callback)
    cal_users_states_test()
