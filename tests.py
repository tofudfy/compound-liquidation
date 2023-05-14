import json
import time
from web3 import Web3
from hexbytes import HexBytes

from types_liq import LogReceiptLight, converter
from configs.protocol import Web3CompoundVenues
from configs.config import RESERVES, URL
from configs.signals import Signals, AggregatorInfos, complete_ctokens_price_info
from configs.block import BlockInfos
from configs.comet import CometConfigs, init_comet_configs
from configs.users import HighProfitSates, backtesting_states, reload_states
from compound import calculate_health_factor, liquidation_simulation, users_trimming, complete_states_info, DESIRED_PROFIT_SCALE
from utils import state_diff_venus_price

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
    w3_liq = Web3CompoundVenues('http')
    # case1(failed: BNB interface): 0x9d7025de65be962a6e958eaf65cad32015254435a4c2df7454671d3c8a51031d
    # block_num = 26612079 - 1  # liquidation height
    # user = "0x46B07ac80D510ABa1600A5821D0FC8c26a655d7A"
    # sig_hash = "0x03e67e5689051cd4f7752a0bceb783609939b94d949b00cf52c7658a56e3dd74"

    # case2(failed: ETH market pause?) : 0xffac70d00d281dba6711cf3bd2cf8aa943fca4d83900bad88e9e044f4ccb1359
    # block_num = 26666330 - 1  # liquidation height
    # user = "0xd42B63493E0c7ab1879aDbc134E8a07Eaa999D3e"
    # sig_hash = "0x36f90f603bced0ed7d77de7ede87bae22e3b9c308aa197bf3d1fb6db123040f6"

    # case3(sucess): 0x9d7a7577949e8e67c390805fb0b225ad061be1b7bad4e8aef5e64982d830e531
    # block_num = 26633142 - 1  # liquidation height
    # user = "0x380d3a46d14A1C4383fE4EAaAAf60036729b377f"
    # sig_hash = "0xcc91742384aab7631e63959731cd1ffd9253d5a7f92214d1e6ae11f2a203abe5"  

    # case4(miss): 
    block_num = 27330993 - 1
    user = "0xeDaF30a3Bbf3A8B20d053AaD3B34450e6d5953B2"
    sig_hash = "0x5fc8cfc8c60823ac7865d85a8dcbabfe04f783d00eddd5e7053219b1fef29e1a"

    url = URL['http']

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
    res = calculate_health_factor(user, states.users_states[user].reserves, states.ctokens, comet, {})
    print(res[0], res[1].__dict__)

    # liquidation simulate
    collaterals, debt = liquidation_simulation(states.users_states[user].reserves, states.ctokens, comet)
    liquidation_params = [user, collaterals[0][3], collaterals[0][1]]
    to_addr = debt[1]
    seized = collaterals[0][2]
    revenue = collaterals[0][0] / 10**18
    print(liquidation_params, revenue, seized)

    # onchain replay
    res = state_diff_venus_price(w3_liq, url, sig_hash, to_addr, liquidation_params) 
    print(res)


'''
def users_trimming_test():
    tokens_addr = ["0x151B1e2635A717bcDc836ECd6FbB62B674FE3E1D"]
    reserves_init = RESERVES
    w3_liq = Web3Liquidation()
    states = reload_states(reserves_init)

    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_risks(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_init)
    complete_states_info(states)
    states = HighProfitSates(states, DESIRED_PROFIT_SCALE)

    users = states.users_filtering(tokens_addr)
    users_trim = users_trimming(users, states, int(time.time())+1200, True)
    print(users_trim)
'''


if __name__ == '__main__':
    # subscribe_test(subscribe_callback)
    cal_users_states_test()
    # users_trimming_test()