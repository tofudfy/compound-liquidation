import json
import time
import asyncio
import multiprocessing
from web3 import Web3
from hexbytes import HexBytes
from websockets import connect
from typing import List

from types_liq import LogReceiptLight, converter
from configs.protocol import Web3CompoundVenues
from configs.web3_liq import Web3Liquidation
from configs.config import RESERVES, URL, P_ALIAS, CONNECTION, NETWORK
from configs.signals import Signals, AggregatorInfos, complete_ctokens_price_info
from configs.block import BlockInfos
from configs.comet import CometConfigs, init_comet_configs
from configs.users import HighProfitSates, backtesting_states, reload_states
from configs.tokens import CtokenConfigs, new_ctokens_infos
from configs.protocol import complete_ctokens_configs_info
from configs.router import RouterV2, ABIUniV2, init_router_pools
from configs.vai import VaiState
from compound import liquidation_simulation, signal_calculate_health_factor, signal_simulate_health_factor, start_multi_process, DESIRED_PROFIT_SCALE, HF_THRESHOLD
from utils import FakeLogger, state_diff_venus_price, subscribe_event_light, send_msg_tenderly
from transaction import create_type0_tx, init_accounts

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


def liquidate_from_proxy_test(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, block_num):
    # call ctoken.sol liquidateBorrow directly
    # tx_liq = ctoken_sc.functions.liquidateBorrow(*params).build_transaction({'gas': 8000000, 'gasPrice': gas_price, 'from': account.address})
 
     # call through deletgate 0x0870793286aaDA55D39CE7f82fb2766e8004cF43
    proxy_addr = "0x0870793286aaDA55D39CE7f82fb2766e8004cF43"
    proxy_sc = w3_liq.gen_proxy_liquidator(proxy_addr)
    params_new = [to_addr] + params

    if sig_hash != "":
        state_diff, gas_price, account_addr = state_diff_venus_price(w3_liq, sig_hash, to_addr, params, proxy_addr=proxy_addr)
    else:
        state_diff = {}
        account_addr = "0x314CB7E388B4491B21bB703813eC961D9Df64e0a"
        gas_price = 3000000000
    tx_liq = proxy_sc.functions.liquidateBorrow(*params_new).build_transaction({'gas': 8000000, 'gasPrice': gas_price, 'from': account_addr})

    # send eth_call to node directly
    # params_call = [tx_liq, hex(block_num), state_diff]
    # data=json.dumps({
    #     "method": "eth_call",
    #     "params": params_call,
    #     "id": 1,
    #     "jsonrpc": "2.0"
    # })
    # print(data)
    # return send_msg(url, data)

    # send simulation to tenderly
    return send_msg_tenderly(tx_liq, state_diff, block_num)


async def cal_users_states_test():
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
    block_num = 28235342 - 1
    user = "0x1245C05e36BEd43b69348E57F0A639130d0D98C6"
    sig_hash = ""

    comet = w3_liq.gen_comptroller()
    res = comet.functions.getAccountLiquidity(user).call(block_identifier=block_num)
    print(res)

    # reserves = w3_liq.query_markets_list(block_num)
    reserves = RESERVES
    states = backtesting_states(w3_liq, user, reserves, block_num)

    reserves_trim = list(states.users_states[user].reserves.keys())

    comet = init_comet_configs(w3_liq, reserves_trim, block_num)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_trim, block_num)
    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_trim)

    # states override
    # states.ctokens["0x86aC3974e2BD0d60825230fa6F355fF11409df5c"].price.price_current = 3420672730000000000
    # states.users_states[user].reserves['0xB248a295732e0225acd3337607cc01068e3b9c10'].col_amount = 16809956189565

    ctx = multiprocessing.get_context('spawn')
    core = 3  # cpu_count()
    multi_pool = ctx.Pool(processes=core)

    # health factor simulate before liquidation
    # res = calculate_health_factor([user, states.users_states[user].reserves, states.users_states[user].vai_repay], states.ctokens, comet)
    # print(res[0], res[1].__dict__)

    targets = [[user, states.users_states[user].reserves, states.users_states[user].vai_repay]]
    map_func = signal_calculate_health_factor
    args_par = (states.ctokens, comet) 
    results = start_multi_process(multi_pool, targets, map_func, args_par)
    res = results[0]
    print(res[0], res[1].__dict__)

    # router init should after ctoken configs init
    routers = RouterV2(ABIUniV2('pancakge_v2'))
    init_router_pools(routers, reserves_trim, states.ctokens, "latest")

    # liquidation simulate
    collaterals, debt = liquidation_simulation(states.users_states[user].reserves, states.ctokens, comet, routers.pools)
    liquidation_params = [user, int(collaterals[0][3] * 0.995), collaterals[0][1]]
    to_addr = debt[1]
    seized = collaterals[0][2]
    revenue = collaterals[0][0] / 10**18
    print(liquidation_params, revenue, seized)

    accounts = init_accounts(w3_liq)
    ws_main = None
    sig = {"hash": sig_hash, 'gas_price': 3000000000}
    logger=FakeLogger()
    # tasks = signal_simulate_health_factor([res], states.ctokens, comet, routers, block_num, ws_main, accounts, sig_recv=sig, logger=logger)

    # targets = [res]
    # map_func = signal_simulate_health_factor
    # args_par = (states.ctokens, comet, block_num, routers.pools, accounts, sig, logger)
    # args = (targets,) + args_par
    # coroutines = map_func(*args)
    # tasks = start_multi_process(multi_pool, targets, map_func, args_par)
    # await asyncio.gather(*tasks)
    multi_pool.terminate()
    multi_pool.join()

    # onchain replay
    res = liquidate_from_proxy_test(w3_liq, sig_hash, to_addr, liquidation_params, block_num)
    print(res)


def liquidate_from_flash_loan_test():
    asyncio.run(liquidate_from_flash_loan_init())


async def liquidate_from_flash_loan_init():
    w3_liq = Web3CompoundVenues('http')
    w3_liq_temp =  Web3CompoundVenues() 
    sig_hash = "0xee0456236d2ee7b4e8203dc8dc66def401215e79f101e314ae156e12d7b7d243"
    to_addr = "0x95c78222B3D6e262426483D42CfA53685A67Ab9D"
    params = ['0xd11fbe979bc85f3c9350571528f50ff6c236cc5c', 171677746208046042403, '0x86aC3974e2BD0d60825230fa6F355fF11409df5c']
    block_num = 27497446

    user = Web3.toChecksumAddress(params[0])
    comet = w3_liq.gen_comptroller()
    res = comet.functions.getAccountLiquidity(user).call(block_identifier=block_num-1)
    print(res) 

    debt_ctoken = to_addr
    col_ctoken = params[2]
    reserves = [debt_ctoken, col_ctoken] # w3_liq.query_markets_list()
    ctokens = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens, w3_liq_temp, reserves)    
    routers = RouterV2(ABIUniV2('pancakge_v2'))
    init_router_pools(routers, reserves, ctokens)
    tx = liquidate_from_flash_loan(to_addr, params, routers, ctokens)

    # send transaction to chain directly
    # async with connect(URL['light']['url'],
    #         extra_headers={'auth': URL['light']['auth']}) as ws:
    #     coroutines = sign_sending_tx_to_tasks(ws, "", tx, FakeLogger())
    #     tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    #     await asyncio.gather(*tasks)
    
    # simulation transaction on tenderly
    state_diff, gas_price, account_addr = state_diff_venus_price(w3_liq, sig_hash, to_addr, params, account_addr="0x4153aEf7bf3c7833b82B8F2909b590DdcF6f8c15")
    tx['gasPrice'] = gas_price
    tx['chainId'] = 56
    tx['from'] = account_addr
    send_msg_tenderly(tx, state_diff, block_num)

    await asyncio.sleep(0.001)


def liquidate_from_flash_loan(to_addr, params, rout: RouterV2, ctk: CtokenConfigs):
    debt_ctoken = to_addr
    col_ctoken = params[2]
    token0 = ctk[col_ctoken].configs.underlying
    token1 = ctk[debt_ctoken].configs.underlying
    
    # if token0 is collateral, zero for one is align with is_token0
    key, zero_for_one = rout.gen_pool_key(token0, token1)
    if not zero_for_one:
        temp = token1
        token1 = token0
        token0 = temp

    pool = rout.pools.get(key, None)
    pool_addr = pool.pool_addr

    gas_fee = 5000000000 
    tx = create_type0_tx(gas_fee, gas=2000000)
    print(zero_for_one, params[1], pool_addr, token0, token1, params[0], to_addr, params[2])

    # varied based on the contract deployed
    intput = "0x18de0524"
    intput += hex(zero_for_one)[2:].zfill(64)  # zero_for_one
    intput += hex(params[1])[2:].zfill(64) # repayAmount 
    # intput += hex(-params[1] & (2**256-1))[2:] # repayAmount
    intput += pool_addr.lower()[2:].zfill(64)  # pair
    intput += token0.lower()[2:].zfill(64)     # token0
    intput += token1.lower()[2:].zfill(64)     # token1
    intput += params[0].lower()[2:].zfill(64)  # borrower
    intput += to_addr.lower()[2:].zfill(64)    # debt_ctoken
    intput += params[2].lower()[2:].zfill(64)  # col_ctoken
    print(intput)

    tx['data'] = intput
    tx['to'] = P_ALIAS['contract']
    print(tx)

    return tx


# the address need to be List type
def light_node_sub_test():
    event_vai_repay = VaiState()
    asyncio.run(subscribe_event_light(event_vai_repay.gen_events_filter(), None, None, "light_event_vai_sub"))


def users_reload_test():
    w3_liq = Web3CompoundVenues()
    reserves = RESERVES 
    states = reload_states(RESERVES)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves)
    target_users = ["0x8d655aaaa0ec224b17972df385e25325b9103332",  "0x1f6d66ba924ebf554883cf84d482394013ed294b"]

    for usr in target_users:
        states.update_debt(usr)

    states = HighProfitSates(states, DESIRED_PROFIT_SCALE)

    for usr in target_users:
        res = states.users_states.get(usr, None)
        if res is None:
            continue

        print(usr, res.health_factor.debt_volume)


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
    asyncio.run(cal_users_states_test())
    # liquidate_from_flash_loan_test()
    # users_trimming_test()
    # light_node_sub_test()
    # users_reload_test()
