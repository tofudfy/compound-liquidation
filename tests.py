import json
import time
import asyncio
import multiprocessing
from web3 import Web3
from hexbytes import HexBytes
from websockets import connect
from typing import List, Dict

from types_light import LogReceiptLight, converter
from configs.protocol import Web3CompoundVenues, Web3CompoundV3
from configs.web3_liq import Web3Liquidation
from configs.config import RESERVES, URL, P_ALIAS, CONNECTION, NETWORK
from configs.signals import Signals, AggregatorInfos, complete_ctokens_price_info
from configs.block import BlockInfos
from configs.comet import CometConfigs, init_comet_configs
from configs.users import HighProfitSates, backtesting_states, reload_states, new_user_states, sync_states
from configs.tokens import CtokenConfigs, CtokenInfos, new_ctokens_infos
from configs.protocol import complete_ctokens_configs_info
from configs.router import init_router_pools, Routs, Pool, SwapV2, SwapV3, ABIUniV3, ABIUniV2, ROUTS_TOKENS
from configs.vai import VaiState
from transaction.send import init_send_type
from compound import SSL_CTX, LiqPair, liquidation_simulation, profit_simulation, signal_calculate_health_factor, signal_simulate_health_factor, start_multi_process, DESIRED_PROFIT_SCALE
from utils import TxFees, FakeLogger, FakePool, WSconnect, state_diff_aggr_price, subscribe_event_light, send_msg_tenderly, state_diff_uniswap_anchor_price, subscribe_header_full
from tx import create_type0_tx, init_accounts
from bots import BSCVenusPancakeV2


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


async def cal_users_states_test():
    provider = 'http4'
    w3_liq = Web3CompoundVenues(provider) 
    # w3_liq = Web3CompoundV3('http2')

    # case4(miss): 
    block_num = 29218112 - 1
    user = "0xea16c182CE54e663EFd64d1c26214Da6Efd382Ea"
    sig_hash = "0x9c9dafb6acf2c9bb7bd42aea253db9634447b0ee92c66f9e2fa61c00c1a4e11c"

    # Step1: find short fall
    comet = w3_liq.gen_comptroller()
    res = comet.functions.getAccountLiquidity(user).call(block_identifier=block_num)
    print(res)

    # Step2: fetch reserves of users onchain
    # reserves = w3_liq.query_markets_list(block_num)
    reserves = RESERVES
    states = backtesting_states(w3_liq, user, reserves, block_num)
    reserves_trim = list(states.users_states[user].reserves.keys())

    # patch for routers
    for ctoken in ["0xA07c5b74C9B40447a954e1466938b865b6BBea36", "0x95c78222B3D6e262426483D42CfA53685A67Ab9D"]: # ["0x39AA39c021dfbaE8faC545936693aC917d5E7563", "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5"]:
        if ctoken not in reserves_trim: 
            reserves_trim.append(ctoken)

    # Step3: fetch other necessary infos onchain
    comet = init_comet_configs(w3_liq, reserves_trim, block_num)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_trim, block_num)
    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_trim)

    # states override
    # must added, or the seize token caculated in liquidation_simulation may be inaccurate
    states.ctokens["0x882C173bC7Ff3b7786CA16dfeD3DFFfb9Ee7847B"].price.price_current = 26603536412480000000000
    # states.users_states[user].reserves['0xB248a295732e0225acd3337607cc01068e3b9c10'].col_amount = 16809956189565

    # Step4: Init multiprocessing
    ctx = multiprocessing.get_context('spawn')
    core = 3  # cpu_count()
    # multi_pool = ctx.Pool(processes=core)
    multi_pool = FakePool()

    # Step5.1: calculate single hf
    # health factor simulate before liquidation
    # res = calculate_health_factor([user, states.users_states[user].reserves, states.users_states[user].vai_repay], states.ctokens, comet)
    # print(res[0], res[1].__dict__)

    # Step5.2: calculate multiple hf
    targets = [
        [user, states.users_states[user].reserves, states.users_states[user].vai_repay]
    ]
    map_func = signal_calculate_health_factor
    args_par = (states.ctokens, comet) 
    results = start_multi_process(multi_pool, targets, map_func, args_par)
    res = results[0]
    print(res[0], res[1].__dict__)

    # Step6: fetch router infos onchain 
    # router init should after ctoken configs init
    routers = SwapV2(ABIUniV2('pancakge_v2'), 25, provider_type=provider)
    # routers = SwapV3(ABIUniV3())
    init_router_pools(routers, reserves_trim, states.ctokens, "latest")

    # Step7.1: calculate liquidations of single user
    # (1) liquidation simulate
    liq_pairs = liquidation_simulation(states.users_states[user].reserves, states.ctokens, comet)
    key = next(iter(liq_pairs))
    liq_pair: LiqPair = liq_pairs[key][0]
    revenue_appr = liq_pair.profit
    to_addr = liq_pair.debt_ctoken
    seized = liq_pair.seize_tokens
    liquidation_params = [user, liq_pair.repay_amount, liq_pair.col_ctoken]
    print("Before routs: ", liquidation_params, to_addr, revenue_appr, seized)

    # Step7.1: calculate liquidations of single user
    # (2) liquidation simulate with routers
    pair_with_routs = profit_simulation(states.ctokens, liq_pairs, routers.pools, routers.swap_simulation)
    if pair_with_routs is not None:
        liq_pair: LiqPair = pair_with_routs[0]
        revenue = liq_pair.profit
        to_addr = liq_pair.debt_ctoken
        seized = liq_pair.seize_tokens
        liquidation_params = [user, liq_pair.repay_amount, liq_pair.col_ctoken]
        print("After routs: ", liquidation_params, to_addr, revenue, seized)

        routs: Routs = pair_with_routs[1]
        for path in routs.paths:
            print(path.__dict__)
    else:
        routs = None

    # Step7.2: calculate liquidations of multiple users
    accounts = init_accounts(w3_liq)
    ws_main = None
    sig = {"hash": sig_hash, 'gas_price': 3000000000}
    logger=FakeLogger()

    send_type = init_send_type(NETWORK)
    block_infos = BlockInfos(block_num, None, 0)

    targets = [res]
    map_func = signal_simulate_health_factor
    args_par = (states.ctokens, comet, block_infos, routers.pools, routers.swap_simulation, accounts, sig, send_type, logger)
    args = (targets,) + args_par
    coroutines = map_func(*args)
    # tasks = start_multi_process(multi_pool, targets, map_func, args_par)
    # await asyncio.gather(*tasks)

    multi_pool.terminate()
    multi_pool.join()

    # onchain replay
    # res = liquidate_from_proxy_test(w3_liq, sig_hash, to_addr, liquidation_params, block_num)
    # res = liquidate_directly_test(w3_liq, states.ctokens, accounts[0].get_address(), sig_hash, to_addr, liquidation_params, block_num)
    res = liquidate_from_contract_test(w3_liq, sig_hash, to_addr, liquidation_params, block_num, routs)
    print(res)


def simulate_user_liq():
    # w3_liq = Web3CompoundVenues('http')
    w3_liq = Web3CompoundV3('http2')

    # liquidation: https://etherscan.io/tx/0x910d4e523b032aa0c8cdb5586b68f1c98c987fef02faebcb5d452ea9d6d1c9a0
    # sig_hash = "0x04201d2ee13eb0d5b10d3f6eb13b4abf338eb859918ecc2982bd242dccc19e03"
    # to_addr = "0x39AA39c021dfbaE8faC545936693aC917d5E7563"
    # liquidation_params = ['0xfB50928e5E618a3dfaE92e7c7e7818a5F80C4BC2', 525668833775, '0xccF4429DB6322D5C611ee964527D42E5d685DD6a']
    # block_num = 17246031
    # block_num -= 1

    sig_hash = "0xc95059a6ea5b154f761b6521a436322b7ad4bbdf7cbc63f54db4ef12adec3093"
    to_addr = "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5"
    liquidation_params = ['0x40b46A4d61cDf850C1C28320D02f7Ee0696DCb67', 1675794191902549963, '0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407']
    block_num = 17415379

    reserves = [to_addr, liquidation_params[2], '0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407']
    ctk = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctk, w3_liq, reserves)

    account_addr = "0x73AF3bcf944a6559933396c1577B257e2054D935"  # account with sufficient ETH balance
    # "0xA1D3d71279cB6E4f0a6C1eF5e7fE282a087bCaf0"

    # onchain replay
    # res = liquidate_from_proxy_test(w3_liq, sig_hash, to_addr, liquidation_params, block_num)
    # res = liquidate_from_contract_test(w3_liq, sig_hash, to_addr, liquidation_params, block_num)
    res = liquidate_directly_test(w3_liq, ctk, account_addr, sig_hash, to_addr, liquidation_params, block_num)
    print(res)


def liquidate_from_proxy_test(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, block_num):
    # call ctoken.sol liquidateBorrow directly
    # tx_liq = ctoken_sc.functions.liquidateBorrow(*params).build_transaction({'gas': 8000000, 'gasPrice': gas_price, 'from': account.address})
 
     # call through deletgate 0x0870793286aaDA55D39CE7f82fb2766e8004cF43
    proxy_addr = "0x0870793286aaDA55D39CE7f82fb2766e8004cF43"
    proxy_sc = w3_liq.gen_proxy_liquidator(proxy_addr)
    params_new = [to_addr] + params

    if sig_hash != "":
        state_diff, fees, account_addr = state_diff_aggr_price(w3_liq, sig_hash, to_addr, params, proxy_addr=proxy_addr)
        gas_price = fees.gas_price
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


def liquidate_from_contract_test(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, block_num, rout=None):
    # todo: make correction
    tx = liquidate_from_flash_loan(to_addr, params, rout)

    # send transaction to chain directly
    # async with connect(URL['light']['url'],
    #         extra_headers={'auth': URL['light']['auth']}) as ws:
    #     coroutines = sign_sending_tx_to_tasks(ws, "", tx, FakeLogger())
    #     tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    #     await asyncio.gather(*tasks)
    
    # simulation transaction on tenderly
    state_diff, fees, account_addr = state_diff_aggr_price(w3_liq, sig_hash, to_addr, params, account_addr="0x4153aEf7bf3c7833b82B8F2909b590DdcF6f8c15")

    tx['gasPrice'] = fees.gas_price
    tx['maxPriorityFeePerGas'] = fees.mev
    tx['maxFeePerGas'] = fees.max_fee
    tx['chainId'] = 56
    tx['from'] = account_addr
    return send_msg_tenderly(tx, state_diff, block_num)


def liquidate_directly_test(w3_liq: Web3Liquidation, ctk: Dict[str, CtokenInfos], account_addr: str, sig_hash: str, to_addr: str, params: List, block_num):
    # simulation transaction on tenderly
    if sig_hash != "":
        # state_diff, sig_fees, account_addr = state_diff_aggr_price(w3_liq, sig_hash, to_addr, params, account_addr="0xA1D3d71279cB6E4f0a6C1eF5e7fE282a087bCaf0")
        state_diff, sig_fees, account_addr = state_diff_uniswap_anchor_price(w3_liq, sig_hash, to_addr, params, ctk, account_addr=account_addr, proxy_addr=to_addr)
    else:
        state_diff = {}
        sig_fees = TxFees(
            gas_price=3000000000,
            mev=0,
            max_fee=6000000000,
        )         

    send_type = init_send_type(NETWORK)
    mev = 0.1

    tx, _ = send_type.map_sig(sig_fees.gas_price, (sig_fees.max_fee - sig_fees.mev)/2, mev, gas=3000000)
    tx['chainId'] = 1
    tx['from'] = account_addr

    if to_addr == "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5":
        liq_sc = w3_liq.gen_ctokens_native(to_addr)
        tx['value'] = params[1]
        params = [params[0], params[2]]
        tx_nex = liq_sc.functions.liquidateBorrow(*params).build_transaction(tx)
    else:
        liq_sc = w3_liq.gen_ctokens(to_addr)
        tx_nex = liq_sc.functions.liquidateBorrow(*params).build_transaction(tx)
    print(tx_nex)

    return send_msg_tenderly(tx_nex, state_diff, block_num)
    

# RoutsCompV2
def liquidate_from_flash_loan(to_addr, params, rout: Routs):
    gas_fee = 5000000000 
    tx, _ = create_type0_tx(gas_fee, 0, 0, gas=3000000)

    bot = BSCVenusPancakeV2()
    intput = bot.gen(params[0], to_addr, params[2], rout.paths)
    print(intput)

    tx['data'] = intput
    tx['to'] = P_ALIAS['contract']

    return tx


# the address need to be List type
def light_node_sub_test():
    event_vai_repay = VaiState()
    asyncio.run(subscribe_event_light(event_vai_repay.gen_events_filter(), None, None, "light_event_vai_sub"))


def head_sub_callback(message):
    # copy from compound.py def on_message
    if 'params' in message and 'result' in message['params']:
        result = message['params']['result']

        validator = Web3.toChecksumAddress(result['miner'])
        block_number = int(result['number'], 16)
        block_timestamp = int(result['timestamp'], 16)
        base_fee = result['baseFeePerGas']
        if base_fee == "None" or base_fee is None:
            base_fee = 0
        else:
            base_fee = int(base_fee, 16)


def full_node_head_sub_test():
    ws_full = WSconnect(CONNECTION[NETWORK]['ws_ym'], ssl=SSL_CTX)
    logger = FakeLogger()
    
    asyncio.run(subscribe_header_full(ws_full, head_sub_callback, logger))


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


def update_user_at_height_test():
    block_num = 17380801
    block_num -= 1
    w3_liq = Web3Liquidation()

    states = new_user_states(block_num)
    reserves_init = RESERVES
    delay = w3_liq.w3.eth.get_block_number() - block_num - 1

    sync_states(states, w3_liq, reserves_init, delay)


def get_log_test():
    w3_liq = Web3CompoundVenues()
    from_block = 17270719
    to_block = 17272718 
    
    # filt = {'fromBlock': hex(from_block), 'toBlock': hex(to_block)}
    filt = {'address': ['0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E', '0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643', '0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5', '0x158079Ee67Fce2f58472A96584A73C7Ab9AC95c1', '0x39AA39c021dfbaE8faC545936693aC917d5E7563', '0xf650C3d88D12dB855b8bf7D11Be6C55A4e07dCC9', '0xC11b1268C1A384e55C48c2391d8d480264A3A7F4', '0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407', '0xF5DCe57282A584D2746FaF1593d3121Fcac444dC', '0x35A18000230DA775CAc24873d00Ff85BccdeD550', '0x70e36f6BF80a52b3B46b3aF8e106CC0ed743E8e4', '0xccF4429DB6322D5C611ee964527D42E5d685DD6a', '0x12392F67bdf24faE0AF363c24aC620a2f67DAd86', '0xFAce851a4921ce59e912d19329929CE6da6EB0c7', '0x95b4eF2869eBD94BEb4eEE400a99824BF5DC325b', '0x4B0181102A0112A2ef11AbEE5563bb4a3176c9d7', '0xe65cdB6479BaC1e22340E4E755fAE7E509EcD06c', '0x80a2AE356fc9ef4305676f7a3E2Ed04e12C33946', '0x041171993284df560249B57358F931D9eB7b925D', '0x7713DD9Ca933848F6819F38B8352D9A15EA73F67'], 'topics': [['0x1a2a22cb034d26d1854bdc6666a5b91fe25efbbb5dcad3b0355478d6f5c362a1', '0x13ed6866d4e1ee6da46f845c46d7e54120883d75c5ea9a2dacc1c4ca8984ab80', '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef', '0x875352fb3fadeb8c0be7cbbe8ff761b308fa7033470cd0287f02f3436fd76cb9', '0x4dec04e750ca11537cabcd8a9eab06494de08da3735bc8871cd41250e190bc04', '0xa91e67c5ea634cd43a12c5a482724b03de01e85ca68702a53d0c2f45cb7c1dc5', '0x3bad0c59cf2f06e7314077049f48a93578cd16f5ef92329f1dab1420a99c177e', '0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5']], 'fromBlock': hex(from_block), 'toBlock': hex(to_block)}

    try:
        logs = w3_liq.w3.eth.get_logs(filt)
        print(logs)
    except Exception as e:
        print(f"get logs failed at {from_block}: {e}")


def get_raw_transaction_test(txhash):
    w3_liq = Web3Liquidation()
    res = w3_liq.w3.eth.get_raw_transaction(txhash)
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
    # category 1: liquidation simulation
    asyncio.run(cal_users_states_test())
    # simulate_user_liq()

    # category 2: node subsription 
    # subscribe_test(subscribe_callback)
    # light_node_sub_test()
    # full_node_head_sub_test()

    # category 3: reload users from local files
    # users_reload_test()
    # users_trimming_test()

    # category 4: Web3 python testing 
    # update_user_at_height_test()
    # get_log_test()
    # get_raw_transaction_test('0x35f9064abc88e48edf6cd42613ebf0717cb443e27b7cb1756740c03ca18ffe4f')
