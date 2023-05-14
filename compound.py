import asyncio
import time
import os
import io
import timeit
import threading
import queue
import multiprocessing
import traceback
import uuid
import secrets
import cProfile
import pstats
import logging
import json
import signal
import sys
import blxr_rlp

from logger import Logger
from web3 import Web3
from web3.types import TxReceipt
from websockets import connect
from multiprocessing import cpu_count, TimeoutError
from errors import MyError
from typing import Dict, List, Tuple

from bxcommon.utils import convert
from bxcommon.messages.eth.serializers.transaction import Transaction, DynamicFeeTransaction

from liquidations import Web3LiqListening, LiquidationCall, gen_liquidation_filter
from transaction import AccCompound, create_type0_tx, create_type2_tx, sign_sending_tx_to_tasks, send_tx_task, start_new_subscribe, init_accounts, create_self_transfer
from bnb48 import Bnb48
from utils import WSconnect, FakePool, polling_full, subscribe_to_node, subscribe_tx_light, subscribe_event_light
from types_liq import LogReceiptLight, converter
from configs.config import CONNECTION, NETWORK, P_ALIAS, LIQUDATION_LOG_LEVEL, EXP_SCALE, ADDRESS_ZERO, INTVL
from configs.protocol import Web3CompoundVenues, complete_ctokens_configs_info, complete_ctokens_risks, query_exchange_rate
from configs.users import UserStates, States, HighProfitSates, HealthFactor, gen_states_filter, reload_states, sync_states, reload_and_extend_states
from configs.comet import CometConfigs, gen_comet_filter, init_comet_configs
from configs.tokens import CompReserve, CtokenInfos
from configs.signals import init_signals, gen_signals_filter, complete_ctokens_price_info, price_scale, price_scale_inverse
from configs.block import init_block_infos
from configs.router import init_router_pools, gen_pool_key, Pool, RouterV2, ABIUniV3, ABIUniV2
from configs.vai import VaiState

LOG_DIRECTORY = "./"  # "/data/fydeng/"
DESIRED_PROFIT_SCALE = 7 * EXP_SCALE  # in USD
HF_THRESHOLD = 1


def on_message(message: Dict):
    """
    {
        "jsonrpc":"2.0",
        "method":"eth_subscription",
        "params":{
            "subscription":"0xf90a0ec9a38afd0d218326fce71eb39e",
            "result":{
                "parentHash":"0xf9a8232c1a458008aed3fe3154b4fb00657042991331bdc75bd8918fe2b7b824",
                "sha3Uncles":"0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347",
                "miner":"0xd1d6bf74282782b0b3eb1413c901d6ecf02e8e28",
                "stateRoot":"0x896de6bb9d1527737a499938c5f42224887baea89d2f0bb174d73aa282638b1a",
                "transactionsRoot":"0x96caff88bbef45c8b770f9522df7d6ba9f6cb46875e9d1a340f6c09c79658a3d",
                "receiptsRoot":"0x03bc4602f5405c69e931a52f52398aea0b78cd269eea5534fe99d0588c4624e4",
                "logsBloom":"0x7fffeb7fdff7f7fbd9beb9efacd9df70effef7fcbffbbff3ffff7ff77bfdff77fffcffeadf7fff9faff7ed69fe42eff9fdc6fcbdf7ea55fffb7fff4fff77fbadadcfffdb9b7d73dcfdeffbdd3beffff57d7fdfffdfd5bedeef6fcf75f6f7ffdd81ff9ee73efed7fdb7edffde33dfdf6bfefbb0fdfb9faffbbfc7b5fffedfdff77ffebeb53dddefff57fffe7bab7fffd37477fdbd3f23af99f5ff4fcff7f3feb777fd77ff7ffff1fdeff6af7dbfff2fddf4bfffabd6dfaf7dfbfffbfdef67fefb77fffffbdfedffbfeffaffffe4fff9d5effd797e3dfdf4d9dfff9fdffeaff9ebf7f9d64bf775f72bfd7f33af3f7ff5befd9cdf3fffdbbffec9faedef9fd7a97f",
                "difficulty":"0x2",
                "number":"0x19c7609",
                "gasLimit":"0x836fb9c",
                "gasUsed":"0x144f19f",
                "timestamp":"0x642af2ad",
                "extraData":"0xd883010114846765746888676f312e32302e31856c696e75780000005b7663b5b88cd3c33813d5fdb753af70cab4499dd7552059f6db138c13cb7b7b8b0580115bc5c43e03408e7f363abaf4ac101d1dd15a983a03ec53a5a54a4aa18f073ddc00",
                "mixHash":"0x0000000000000000000000000000000000000000000000000000000000000000",
                "nonce":"0x0000000000000000",
                "baseFeePerGas":"None",
                "hash":"0x72596f19c19145788d1742e9cb7bb71b85182c933d6784353a0345358f18bb22"
            }
        }
    }
    """
    if 'params' in message and 'result' in message['params']:
        result = message['params']['result']

        block_number = int(result['number'], 16)
        block_timestamp = int(result['timestamp'], 16)
        base_fee = 0
        # todo: base_fee = int(result['baseFeePerGas'], 16)

        gas_price = w3_liq.w3.eth.gas_price

        # task 1: Update the local block number, timestamp, and base fee
        block_infos.update(block_number, block_timestamp, base_fee, gas_price)
        logger.info(f'onchain infos updated: {{"block_infos": {block_infos.__dict__}}}') 

        # task 2: Update one of the exchange rate every block
        index = block_number % len(reserves_init)
        token_addr = reserves_init[index]
        states.ctokens[token_addr].risks.exchange_rate = query_exchange_rate(w3_liq, token_addr)
        logger.info(f'reserve exchange rate updated: {{"ctoken": "{token_addr}", "ex_rate": {states.ctokens[token_addr].risks.exchange_rate}}}') 

        # task 3: timeout the staled price
        for reserve in reserves_init:
            states.ctokens[reserve].price.revert()

        # task 4: update account nonce to in case the local value is wrong
        for acc in accounts:
            acc.nonce = w3_liq.w3.eth.get_transaction_count(acc.get_address())


async def get_chain_infos_full():
    counter = 0
    json_rpc = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["newHeads"]}
    # reconnect when websocket is unstable
    while True:
        counter += 1
        json_rpc['id'] = counter
        json_rpc_str = json.dumps(json_rpc)
        ws = WSconnect(CONNECTION[NETWORK]['ws_local'])

        await subscribe_to_node(ws, json_rpc_str, on_message, logger, "full_newHeads_sub")

        if counter >= 5:
            raise Exception("subscribe new headers to full nodes too many times")
        else:
            logger.info("try to re-subscribe to full node")


async def get_pending_callback(message):
    txs = message['Txs']
    for tx in txs:
        t = tx['Tx']
        t['from'] = tx['From']
        await pt_prof_wrap(t)


async def get_pending_transactions_light(callback):
    counter = 0
    while True:
        counter += 1
        try:
            async with connect(CONNECTION[NETWORK]['light']['url'], ping_interval=None,
                            extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
                await ws.send(
                    json.dumps({
                        'm': 'subscribe',
                        'p': 'txpool',
                        'tx_filters': signals.signals_event_filter_light
                    }))
                subscription_response = await ws.recv()
                logger.info(subscription_response.strip())

                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=3600)
                        start = timeit.default_timer()
                        logger.debug("pending tx listening in control")
                    except asyncio.TimeoutError:
                        logger.error("ws Timeout error: no signal")
                        continue

                    message = json.loads(message)
                    txs = message['Txs']

                    # one signal at a time
                    for tx in txs:
                        t = tx['Tx']
                        t['from'] = tx['From']
                        await callback(t)
                    stop = timeit.default_timer() 
                    logger.debug(f'pending tx listening out of control: {{"total_time": {stop-start}}}')

        except Exception as e:
            logger.error(f"unable to connect to light node: {e}")

        if counter >= 3:
            raise Exception("connect to light nodes too many times")
        else:
            logger.info("try to reconnect to light node")


# execute when other asyncios are idel
async def liquidation_idel(callback):
    prev_block = 0
    while True:
        start = timeit.default_timer()
        logger.debug("liquidation idel in control")
        try:
            prev_block = await callback(prev_block)
            
            stop = timeit.default_timer()
            logger.debug(f'liquidation idel out of control: {{"total_time": {stop-start}, "height": {prev_block}}}')
            await asyncio.sleep(0.2)

        except Exception as e:
            raise Exception(f"error in continues liquidation: {e}")


def get_data_from_queue(q: queue.Queue):
    try:
        res = q.get(False)
    except queue.Empty:
        res = []

    return res


def write_data_from_queue(q: queue.Queue, data):
    try:
        q.put(data, block=False)
    except Exception as e:
        logger.error(f"write pending queue error: {e}")


def users_trimming_wrap(users, current_time, is_signal=True):
    return users_trimming(users, states, current_time, is_signal)


def users_trimming(users, sta: States, current_time, is_signal):
    intvl = 0.01        # length of the tick
    intvl_time = 120    # 2 mins update freq per tick

    # T_delta: the hf>1.1 is not likely under 1.0 within 20 mins
    # we have T_delta > T_aggr 
    base = 0 
    left = 0.1    
    right = - 0.1

    users_filtered = []
    for usr in users:
        hf_infos = sta.users_states[usr].health_factor
        hf_norm = hf_infos.value / HF_THRESHOLD - 1
        
        last_update = hf_infos.last_update
        # reduce lenght of users by last time update
        if last_update + min(abs(hf_norm)//intvl*intvl_time, 86400) > current_time:
            continue

        if is_signal and left > hf_norm > base:
            users_filtered.append((hf_norm, usr))
        elif not is_signal and (hf_norm >= left or base >= hf_norm >= right or hf_norm == -1):
            users_filtered.append(usr)
        else:
            continue

    if is_signal:
        users_filtered_sorted = sorted(users_filtered)
        users_sorted = []
        for data in users_filtered_sorted:
            users_sorted.append(data[1])
    else:
        users_sorted = users_filtered

    return users_sorted


def print_health_factor(results: List[Tuple[str, HealthFactor, Dict]], label="idel"):
    """
    reduce the print in hf calculation
    """
    for res in results:
        (usr, new_health_factor, _) = res
        health_factor = new_health_factor.value
        sum_borrow_plus_effects = new_health_factor.debt_volume
        sum_collateral = sum_borrow_plus_effects * health_factor
        if health_factor > 1:
            liquidity = sum_collateral - sum_borrow_plus_effects 
            short_fall = 0 
        else:
            liquidity = 0
            short_fall = sum_borrow_plus_effects - sum_collateral         
        logger.debug(f'hf calculation result: {{"user": "{usr}", "accountLiquidity": {[0, liquidity, short_fall]}, "healthFactor": {health_factor}, "sumCollateral": {sum_collateral}, "sumBorrow": {sum_borrow_plus_effects}, "label":"{label}"}}')        


async def liquidation_idle_callback(prev_block):
    block_num = block_infos.block_num

    # task 1: listen to the users by block, to generate top-of-block
    users = get_data_from_queue(users_continue)
    if len(users) != 0:   
        logger.info(f"calculate top-of-block liq start at {block_num} + 2")
        # todo: users = deduplication(results)
        users_with_args = gen_users_with_args(users)
        results = execution_select(signal_calculate_health_factor, "hf", users_with_args, args=(states.ctokens, comet))

        coroutines = signal_simulate_health_factor(results, states.ctokens, comet, block_infos.block_num, routers.pools, accounts, None, logger)
        await send_transactions(ws_main, coroutines)
        write_health_factor(results)
        print_health_factor(results)
        return prev_block

    # task 2: finish the hf calculation of the remaining users
    users = get_data_from_queue(users_pending)
    if len(users) != 0:
        logger.info(f"calculate pending users start at {block_num} + 2, length {len(users)}")

        users_with_args = gen_users_with_args(users)
        results = execution_select(signal_calculate_health_factor, "hf", users_with_args, args=(states.ctokens, comet)) 

        if signal_recv.get("recv_height", 0) == block_num:
            sig = signal_recv
            is_sig = True
        else:
            sig = None
            is_sig = False
        coroutines = signal_simulate_health_factor(results, states.ctokens, comet, block_infos.block_num, routers.pools, accounts, sig, logger)
        await send_transactions(ws_main, coroutines, is_sig=is_sig)
        write_health_factor(results)
        print_health_factor(results)
        return prev_block
    
    # task3: update infos periodically
    if block_num <= prev_block:
        return prev_block

    """
    trigger every 1 mins
    switch 1: update hf of users periodically
    T_users: 1 mins * intervals a round
    switch 3: update list of users whose hf is within [1.0, 1.1]
    T_aggr: 1 mins * len(aggr) a round
    we have T_aggr > T_users 
    """
    num = 60 // INTVL
    switch = block_num%num
    index = block_num
    if switch == 1:
        users = states.get_users_sampling(index, 10)
        users_trim = users_trimming_wrap(users, int(time.time()), is_signal=False)
        logger.info(f"calculate sample users start at {block_num} + 1, length {len(users_trim)}")

        users_trim_with_args = gen_users_with_args(users_trim)
        args = (states.ctokens, comet)
        results = execution_select(signal_calculate_health_factor, "hf", users_trim_with_args, args=args) 

        write_health_factor(results)
        print_health_factor(results)
    elif switch == 3:
        tokens_addr, aggr = signals.get_tokens_from_aggr_index(index)
        users = states.users_filtering(tokens_addr)  # todo: optimization
        users_trim = users_trimming_wrap(users, int(time.time())+1200) 
        users_pre_filtered[aggr] = users_trim
        logger.info(f'calculate pre users filtering: {{"tokens": {tokens_addr}, "length": {len(users_trim)}}}')
    return block_num


def users_subscribe_callback(response: LogReceiptLight):
    block_num = response['blockNumber']
    block_hash = response['blockHash']
    logs = converter(response)

    # if not continues
    # new_block = w3_liq.w3.eth.get_block(block_hash)
    # parent_hash_str = '0x' + new_block['parentHash'].hex()
    # if states.block_hash != parent_hash_str:
    #     pass

    if block_num < states.last_update:
        logger.info(f'logs out of date: {{"block_num":{block_num}, "logs":{logs}}}')
        return

    users = {}
    for log in logs:
        temp = states.update(log)
        users.update(temp)
    states.last_update = block_num
    states.block_hash = block_hash
    logger.info(f'users in local cache updated: {{"users": {users}, "block_num": {block_num}}}')
    users_lst = list(users.keys())

    # recalculate users hf after updating
    users_with_args = gen_users_with_args(users_lst)
    args = (states.ctokens, comet)
    results = execution_select(signal_calculate_health_factor, "hf", users_with_args, args=args)

    # get users not in range [0, 0.1] before updating
    users_target = users_trimming_wrap(users_lst, int(time.time())+86400, is_signal=False)
    write_health_factor(results)
    print_health_factor(results)

    # add users in range [0, 0.1] after updating to pre filtered list
    users_filtered = users_trimming_wrap(users_target, int(time.time())+86400)
    new_added = {}
    for usr in users_filtered:
        new_added[usr] = []
        start = timeit.default_timer()
        hf = states.users_states[usr].health_factor.value 
        for ctoken_addr in states.users_states[usr].reserves.keys():
            # debug: vUST has no price source
            aggr = signals.token_signal_map.get(ctoken_addr, None)
            if aggr is None:
                continue

            users_pre_filt = users_pre_filtered[aggr]
            if usr in users_pre_filt:
                continue
            
            index = 0
            for i in range(len(users_pre_filt)):
                usr_pre_filt = users_pre_filt[i]
                hf_compare = states.users_states[usr_pre_filt].health_factor.value  
                if hf < hf_compare:
                    index = i
                    break

            users_pre_filt.insert(index, usr)
            new_added[usr].append(aggr)
            print(f'user add to pre filtered: {{"aggregator":{aggr}, "user": "{usr}", "index": {index}, "block_num":{block_num}}}')
        end = timeit.default_timer()
        logger.info(f'user add to pre filtered: {{"users": {new_added}, "time":{end-start}}}')

    # update users getAssetsIn
    # todo: the reason why update getAssetsIn when the balacne of user changed? 
    for usr in users_lst:
        reload_and_extend_states(w3_liq, states, usr)

    # plug in
    if states.plug_in is None:
        return

    start = timeit.default_timer()
    for usr, _ in states.plug_in.storage.items():
        vai_repay = w3_liq.query_user_vai_repay(usr)
        # todo: how to sync the vai repay of users that are not in the high profit category?
        if states.users_states.get(usr, None) is None:
            continue 
        states.users_states[usr].vai_repay = vai_repay
    end = timeit.default_timer()
    logger.debug(f'users vai repay updated: {{"users": {states.plug_in.storage}, "total_time":{end-start}}}')
    states.plug_in.storage.clear()


def comet_subscribe_callback(response: LogReceiptLight):
    block_num = response['blockNumber']
    # block_hash = response['blockHash']
    logs = converter(response)

    if block_num < comet.last_update:
        logger.info(f'logs out of date: {{"block_num":{block_num}, "logs":{logs}}}')
        return

    for log in logs:
        comet.update(log)
    comet.last_update = block_num
    logger.info(f'comet in local cache updated: {{"block_num": {block_num}}}')


def signals_subscribe_callback(response: LogReceiptLight):
    logs = converter(response)
    for log in logs:
        # we need the key of signal_token_map be lower case 
        contract_addr = log['address']
        aggr_infos = signals.signal_token_map[contract_addr.lower()]
        for token_info in aggr_infos:
            ctoken_addr = token_info.token
            decimals = states.ctokens[ctoken_addr].configs.underlying_decimals
            feed_decimals = token_info.price_decimals
            states.ctokens[ctoken_addr].price.comfirm(log, decimals, feed_decimals)
            logger.info(f'signals price confirmed: {{"ctoken": "{ctoken_addr}", "price": {states.ctokens[ctoken_addr].price.__dict__}}}')


async def users_polling_full(callback):
    filt = gen_states_filter(reserves_init)
    logger.debug("the user filter is {}".format(filt))
    polling_full(w3_liq, filt, callback)


async def comet_configs_polling_full(callback):
    filt = gen_comet_filter()
    logger.debug("the comet configs filter is {}".format(filt))
    polling_full(w3_liq, filt, callback)


def liquidations_subscribe_callback(response: LogReceiptLight):
    logs = converter(response)
    for log in logs:
        liq_onchain.update(log)


def vai_repay_subscribe_callback(response: LogReceiptLight):
    start = timeit.default_timer()
    logs = converter(response)
    res = {}
    for log in logs:
        temp = event_vai_repay.update(log)
        if temp is not None:
            res.update(temp)

    for usr, _ in res.items():
        vai_repay = w3_liq.query_user_vai_repay(usr)
        # todo: how to sync the vai repay of users that are not in the high profit category?
        if states.users_states.get(usr, None) is None:
            continue 
        states.users_states[usr].vai_repay = vai_repay
    end = timeit.default_timer()
    logger.debug(f'users vai repay updated: {{"users": {res}, "total_time":{end-start}}}')


def process_receipts(receipts: list):
    global send_lock
    global send_counter
    for receipt in receipts:
        logger.info(f'received receipt: {receipt}')

        if int(receipt['status'], 16) == 0:
            send_counter += 1

        if send_counter >= 5:
            send_lock = True
            logger.info(f'sending disabled')


async def tx_send_and_tracking_subscribe(callback, logger):
    global ws_main
    async with connect(CONNECTION[NETWORK]['light']['url'],
                extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
        
        ws_main = ws
        # 收交易回执与发交易的ws了解请用同一个
        try:
            s1 = start_new_subscribe(ws, callback, logger)
            await s1
        except Exception as e:
            logger.error(f"tracking subscribe error: {e}")


def signal_calculate_health_factor(targets, ctk: Dict[str, CtokenInfos], comet: CometConfigs) -> List[Tuple[str, HealthFactor, Dict[str, CompReserve]]]:
    res = []
    for usr_with_args in targets:
        res.append(calculate_health_factor(usr_with_args, ctk, comet))

    return res


def gen_users_with_args(users: List) -> List:
    res = []
    for usr in users:
        res.append([usr, states.users_states[usr].reserves, states.users_states[usr].vai_repay])
    return res


def calculate_health_factor(usr_with_args: List, ctk: Dict[str, CtokenInfos], comet: CometConfigs) -> Tuple[str, HealthFactor, Dict[str, CompReserve]]:
    sum_collateral = 0
    sum_borrow_plus_effects = 0

    usr = usr_with_args[0] 
    reserves: Dict[str, CompReserve] = usr_with_args[1]
    vai_repay = usr_with_args[2] 

    for token_addr, reserve in reserves.items():
        collateral_balance = reserve.col_amount
        is_col_liq = reserve.is_col_liq
        debt_balance = reserve.debt_amount
        interest_index = reserve.debt_interest

        price = ctk[token_addr].price.price_current

        collateral_factor = comet.ctokens_collateral_factor[token_addr]
        exchange_rate = ctk[token_addr].risks.exchange_rate
        if is_col_liq and collateral_factor > 0 and collateral_balance > 0:
            sum_collateral += ((collateral_factor * exchange_rate // EXP_SCALE) * price // EXP_SCALE) * collateral_balance // EXP_SCALE

        if debt_balance > 0:
            # debug only
            if interest_index == 0:
                print(f'ERROR: invalid interest_index: {{"user":"{usr}", "reserve":"{token_addr}", "data":{reserve}}}')
                continue
            borrow_index = ctk[token_addr].risks.borrow_index
            debt_balance = debt_balance * borrow_index // interest_index
            sum_borrow_plus_effects += debt_balance * price // EXP_SCALE

        # print(f'{{"user": "{usr}", "reserve": "{token_addr}", "price": {price}, "ctokenBalance": {collateral_balance}, "borrowBalance": {debt_balance}, "exchangeRate": {exchange_rate}, "collateralFactor": {collateral_factor}}}')

    # for venus protocol only, set as 0 for other protocol
    sum_borrow_plus_effects += vai_repay

    if sum_borrow_plus_effects <= 0:
        return usr, HealthFactor(0, sum_borrow_plus_effects, int(time.time())), reserves 
    else:
        health_factor = sum_collateral / sum_borrow_plus_effects
        short_fall = sum_borrow_plus_effects - sum_collateral
        liquidity = 0
        if short_fall < 0:
            short_fall = 0
            liquidity = sum_collateral - sum_borrow_plus_effects

        # logger.debug(f'hf calculation result: {{"user": "{usr}", "accountLiquidity": {[0, liquidity, short_fall]}, "healthFactor": {health_factor}, "sumCollateral": {sum_collateral}, "sumBorrow": {sum_borrow_plus_effects}}}')
        # print(f'hf calculation result: {{"user": "{usr}", "accountLiquidity": {[0, liquidity, short_fall]}, "healthFactor": {health_factor}, "sumCollateral": {sum_collateral}, "sumBorrow": {sum_borrow_plus_effects}}}')

        return usr, HealthFactor(health_factor, sum_borrow_plus_effects, int(time.time())), reserves


def mul_scalar_truncate(ratio, repay_amount):
    return ratio * repay_amount // EXP_SCALE


def mul_scalar_truncate_reverse(ratio, seize_amount):
    return seize_amount * EXP_SCALE // ratio 


def liquidation_simulation(reserves: Dict[str, CompReserve], ctk: Dict[str, CtokenInfos], com: CometConfigs, pools: Dict[str, Pool]):
    debts = []
    for ctoken_addr, data in reserves.items():
        debt_balance = data.debt_amount
        interest_index = data.debt_interest
        borrow_index = ctk[ctoken_addr].risks.borrow_index

        if debt_balance > 0:
            debt_balance = debt_balance * borrow_index // interest_index
            debt_max = mul_scalar_truncate(com.closs_factor, debt_balance)
            debt_price = ctk[ctoken_addr].price.price_current
            debt_normalize = debt_price * debt_max // EXP_SCALE
            debts.append(
                (debt_normalize, ctoken_addr, debt_max)
            )

    # normally can not happened
    if len(debts) == 0:
        return [], []

    debts = sorted(debts, reverse=True)
    target_debt = debts[0]
    debt_ctoken = target_debt[1]
    actual_repay_amount = target_debt[2]
    debt_price = ctk[debt_ctoken].price.price_current

    collaterals = []
    for ctoken_addr, data in reserves.items():
        
        # todo: consider the router impact
        token0 = ctk[ctoken_addr].configs.underlying
        token1 = ctk[debt_ctoken].configs.underlying
        debt_token_index = 1

        key, zero_for_one = gen_pool_key(token0, token1)
        if not zero_for_one:
            debt_token_index = 0

        pool = pools.get(key, None)
        if pool is None:
            continue

        collateral_balance = data.col_amount
        if collateral_balance > 0:
            price = ctk[ctoken_addr].price.price_current
            exchange_rate = ctk[ctoken_addr].risks.exchange_rate
            numerator = com.liq_incentive * debt_price // EXP_SCALE
            denominator = price * exchange_rate // EXP_SCALE
            ratio = numerator * EXP_SCALE // denominator
            seize_tokens = mul_scalar_truncate(ratio, actual_repay_amount)

            # todo
            # different from onchain logic, we need to rejust the actual_repay_amount 
            if collateral_balance < seize_tokens:
                seize_tokens = collateral_balance
                rejust_repay_amount = mul_scalar_truncate_reverse(ratio, seize_tokens) 
            else:
                rejust_repay_amount = actual_repay_amount

            # todo: consider the router impact
            if rejust_repay_amount > pool.liquidity[debt_token_index]:
                continue

            # refer to getHypotheticalAccountLiquidityInternal
            # profit_apprx = (seize_tokens * exchange_rate // EXP_SCALE * price - rejust_repay_amount * debt_price) // EXP_SCALE

            # uniswap v2 without fee consideration
            x = pool.liquidity[debt_token_index] 
            y = pool.liquidity[1-debt_token_index]
            swap_tokens = y * rejust_repay_amount * 10000 // ((x - rejust_repay_amount) * 9975) + 1
            profit_apprx = (seize_tokens * exchange_rate // EXP_SCALE - int(swap_tokens)) * price // EXP_SCALE 

            collaterals.append((profit_apprx, ctoken_addr, seize_tokens, rejust_repay_amount))

    collaterals = sorted(collaterals, reverse=True)
    return collaterals, target_debt


def liquidation_init(usr_addr: str, reserves: Dict[str, CompReserve], ctokens: Dict[str, CtokenInfos], comet: CometConfigs, pools: Dict[str, Pool]):
    collaterals, debt = liquidation_simulation(reserves, ctokens, comet, pools)
    if len(debt) == 0:
        return "", [] 

    if len(collaterals) == 0:
        return "", [] 

    to_addr = debt[1]
    return to_addr, collaterals[0]


def generate_unique_id(length=16):
    return secrets.token_hex(length)


def signal_simulate_health_factor(results: List[Tuple[str, HealthFactor, Dict]], ctk: Dict[str, CtokenInfos], comet: CometConfigs, block_num: int, pools: Dict[str, Pool], acc: List[AccCompound], sig_recv, logger):
    tasks = []

    for res in results:
        (usr, new_health_factor, reserves) = res
        if 1 > new_health_factor.value/HF_THRESHOLD > 0:
            to_addr, collateral_infos = liquidation_init(usr, reserves, ctk, comet, pools)
            if len(collateral_infos) == 0:
                logger.debug(f'liquidation skipped: {{"user":"{usr}"}}')
                continue

            revenue = collateral_infos[0]
            # borrower, repay_amount, col_addr
            liquidation_params = [usr, collateral_infos[3], collateral_infos[1]]
            seized_amount = collateral_infos[2]
            
            # index = uuid.uuid1().hex
            index = generate_unique_id()
            if sig_recv is not None:
                sig_hash = sig_recv['hash']
            else:
                sig_hash = ""

            if revenue < DESIRED_PROFIT_SCALE:
                logger.info(f'liquidation abandoned: {{"index":"{index}", "user":"{usr}", "revenue":{revenue/10**18}, "block_num":{block_num}, "params":{liquidation_params}, "to_addr": "{to_addr}", "gainedAmount": {seized_amount}, "signal":"{sig_hash}"}}')
                continue

            if liquidation_params is not None:
                logger.info(f'liquidation start: {{"index":"{index}", "user":"{usr}", "revenue":{revenue/10**18}, "block_num":{block_num}, "params":{liquidation_params}, "to_addr": "{to_addr}", "gainedAmount": {seized_amount}, "signal":"{sig_hash}"}}')

                tasks += liquidation_start(index, ctk, pools, to_addr, liquidation_params, revenue, acc, sig_recv, logger)

    return tasks


def liquidation_start(index, ctk, pools, to_addr, params, revenue, acc, sig_recv, logger):
    return liquidate_from_flash_loan(index, ctk, pools, to_addr, params, revenue, acc, sig_recv, logger)


def free_user_liquidated(args):
    user = args[0]
    debt = args[1]
    debt_to_cover = args[2]
    users_to_liquidate[user][debt].pop() 


def is_user_liquidated(args):
    user = args[0]
    debt = args[1]
    debt_to_cover = args[2]

    if users_to_liquidate.get(user) is None:
        return False, None
    elif users_to_liquidate[user].get(debt) is None:
        return False, None
    else:
        res = users_to_liquidate[user][debt]
        if res is None:
            return False, None

        prev_debt_to_cover = res[0]
        prev_index = res[1]
        if abs(debt_to_cover/prev_debt_to_cover-1) < 0.1:
            return True, prev_index
        else:
            users_to_liquidate[user][debt] = [debt_to_cover, prev_index]
            return False, None
        

def set_user_liquidated(index, args):
    user = args[0]
    debt = args[1]
    debt_to_cover = args[2]

    if users_to_liquidate.get(user) is None:
        users_to_liquidate[user] = {}
    
    users_to_liquidate[user][debt] = [debt_to_cover, index]


def liquidate_from_flash_loan(index, ctk: Dict[str, CtokenInfos], pools: Dict[str, Pool], to_addr, params, revenue, acc, sig_recv, logger):
    # todo: liquidated when an invalid signal is given
    res, prev_index = is_user_liquidated([params[0], to_addr, params[1]])
    if res:
        logger.debug(f'user is liquidated: {{"index":"{prev_index}", "revenue": {revenue}, "params":{params}}}')    
        return []

    debt_ctoken = to_addr
    col_ctoken = params[2]
    token0 = ctk[col_ctoken].configs.underlying
    token1 = ctk[debt_ctoken].configs.underlying
    debt_token_index = 1

    # if token0 is collateral, zero for one is align with is_token0
    key, zero_for_one = gen_pool_key(token0, token1)
    if not zero_for_one:
        debt_token_index = 0
        temp = token1
        token1 = token0
        token0 = temp

    pool = pools.get(key, None)
    if pool is None:
        logger.debug(f'user debt cannot be swapped: {{"index":"{index}", "pair":{[token0, token1]}, "revenue": {revenue}, "params":{params}}}')    
        return []
    
    fee = pool.fee
    pool_addr = pool.pool_addr

    repay_amount = params[1]
    if repay_amount > pool.liquidity[debt_token_index]:
        logger.debug(f'invalid liquidity:{{"index":"{index}", "pool": {pool.__dict__}, "repay_amount": {repay_amount}}}')
        return []

    # continue listening to user, if he can be continues liquidated
    # todo: move the continues liquidation to smart contract?
    # write_continues_users_queue_v2(params[2], current_time)

    # todo: base_fee = block_infos.base_fee
    base_fee = 0
    if NETWORK == "Polygon":
        estimate_gas = 500000
        if sig_recv is not None:
            if sig_recv.get('tx_type', "") == '0x0':
                gas_fee = sig_recv['gas_price']
                tx = create_type0_tx(gas_fee, gas=1200000)
            else:
                pass
            logger.debug(f'signal founded: {{"index":"{index}", "signal_info":{sig_recv}}}')
        else:
            mev = 0 # todo: query_priotity_fee(current_time)
            gas_fee = base_fee + mev
            tx = create_type2_tx(base_fee, mev, gas=estimate_gas)
            logger.debug(f'signal already onchain: {{"index":"{index}"}}')

        try:
            matic_usd_aggr = ""
            res = signals.get_tokens_from_aggr(matic_usd_aggr)
            ctoken_addr = res[0][0].token
            price = states.ctokens[ctoken_addr].price.price_current / 10**18  # todo
        except:
            price = 0
        cost = gas_fee / 10**18 * estimate_gas
        cost_in_protocol_base = cost * price
    elif NETWORK == "BSC":
        estimate_gas = 1100000
        # the balance of user should larger than gas_price * gas_limit. e.g. 5000000000 * 2500000 / 10**18 = 0.0125 
        gas_limit = 3000000
        if sig_recv is not None:
            gas_fee = sig_recv['gas_price']
            # logger.debug(f'signal founded: {{"index":"{index}", "signal_info":{sig_recv}}}')
        else:
            mev = 3000000000 # todo: query_priotity_fee(current_time)
            gas_fee = base_fee + mev
            # logger.debug(f'signal already onchain: {{"index":"{index}"}}')

        tx = create_type0_tx(gas_fee, gas=gas_limit)

        '''
        try:
            bnb_usd_aggr = "0x137924D7C36816E0DcAF016eB617Cc2C92C05782"
            res, _ = signals.get_tokens_from_aggr(bnb_usd_aggr)
            ctoken_addr = res[0].token
            token_decimals = states.ctokens[ctoken_addr].configs.underlying_decimals
            price = states.ctokens[ctoken_addr].price.price_current
            price_decimals = res[0].price_decimals
            price = price_scale_inverse(price, token_decimals, price_decimals) / 10**price_decimals * EXP_SCALE
        except:
            price = 0
        cost = gas_fee / 10**18 * estimate_gas
        cost_in_protocol_base = cost * price
        '''
        cost_in_protocol_base = 0.007 * 330 * gas_fee / 5000000000 * 10**18
    elif NETWORK == "Ethereum":
        estimate_gas = 1500000
        mev = 0.9 * (revenue / estimate_gas * 10**18  - base_fee)         
        gas_fee = base_fee + mev
        tx = create_type2_tx(base_fee, mev, gas=estimate_gas)
        cost = gas_fee / 10**18 * estimate_gas
        cost_in_protocol_base = cost 

    profit = revenue - cost_in_protocol_base 
    if profit < 0:
        logger.info(f'gas fee larger than revenue: {{"index":"{index}", "gas": {gas_fee}, "price":{price}, "revenue":{revenue}}}')
        return []

    # varied based on the contract deployed
    intput = "0x18de0524"
    intput += hex(zero_for_one)[2:].zfill(64)  # zero_for_one 
    intput += hex(params[1])[2:].zfill(64)     # repayAmount 
    intput += pool_addr.lower()[2:].zfill(64)  # pair
    intput += token0.lower()[2:].zfill(64)     # token0
    intput += token1.lower()[2:].zfill(64)     # token1
    intput += params[0].lower()[2:].zfill(64)  # borrower
    intput += to_addr.lower()[2:].zfill(64)    # debt_ctoken
    intput += params[2].lower()[2:].zfill(64)  # col_ctoken

    tx['data'] = bytes.fromhex(intput[2:])
    tx['to'] = bytes.fromhex(P_ALIAS['contract'][2:])

    # todo: move to other place
    # if send_lock:
    #     return []
    
    set_user_liquidated(index, [params[0], to_addr, params[1]])
    return sign_sending_tx_to_tasks(index, tx, profit, acc)


def users_filtering_wrap(tokens_addr):
    users = states.users_filtering(tokens_addr)
    logger.debug("from token {} filtered {} users".format(tokens_addr, len(users)))
    return users


def write_health_factor(results: List[Tuple[str, HealthFactor, Dict]]):
    # logger.debug('write health factor start')
    for res in results:
        (usr, new_health_factor, _) = res
        states.users_states[usr].health_factor = new_health_factor


def calculate_health_factor_fake_inverse(health_factor_after, delta):
    if delta < 0:
        f_delta = 1 + delta
    else:
        f_delta = 1/(1 + delta)

    return health_factor_after / f_delta


def find_hf_users(users, delta_max):
    thres = calculate_health_factor_fake_inverse(HF_THRESHOLD, delta_max)

    filtered_users = []
    for usr in users:
        hf = states.users_states[usr].health_factor.value
        if hf < thres:
            filtered_users.append(usr)
        
        if hf > 1.01:
            break

    return filtered_users


def find_hf_users_index_by_seq(users, delta_max):
    thres = calculate_health_factor_fake_inverse(HF_THRESHOLD, delta_max)

    filtered_users = []
    for i in range(len(users)):
        usr = users[i]
        hf = states.users_states[usr].health_factor.value
        if hf < thres:
            filtered_users.append(usr)
        
        if hf > 1.01:
            break

    return filtered_users


def find_hf_users_index_by_binary(sorted_users, delta_max):
    left = 0
    right = len(sorted_users) - 1
    thres = calculate_health_factor_fake_inverse(HF_THRESHOLD, delta_max)
    while left < right-1:
        index = round((left + right)/2)
        hf = states.users_states[sorted_users[index]].health_factor.value
        if hf < thres:
            left = index
        else:
            right = index

    hf_right = states.users_states[sorted_users[right]].health_factor.value
    hf_left = states.users_states[sorted_users[left]].health_factor.value
    if hf_right < thres:
        index = right + 1
    elif hf_left > thres:
        index = left
    else:
        index = left + 1

    return index


def start_multi_process_wrap(targets, map_func, args_par) -> List:
    # todo: disable the multi processing (1/3)
    return start_multi_process(multi_pool, targets, map_func, args_par)


def start_multi_process(p, targets, map_func, args_par, timeout=None) -> List:
    results = []
    nonce_counter = 0
    for tar in targets:
        args = ([tar], ) + args_par
        # logger.debug(f'multi process inputs:{{"function":{map_func}, "args":{args}}}')
        results.append(p.apply_async(map_func, args=args))
        nonce_counter += 1

    res = []
    for r in results:
        try:
            res += r.get(timeout)
        except TimeoutError:
            logger.error(f"TimeoutError: The operation for target {tar} timed out.")

    return res


# deorecated
def start_multi_process_old(p, targets, target_num, map_func, args_par) -> List[Tuple[str, HealthFactor]]:
    invl = len(targets)//target_num

    results = []
    for i in range(target_num):
        if i == target_num-1:
            args = (targets[invl*i:],) + args_par
        else:
            args = (targets[invl*i:invl*(i+1)],) + args_par
        results.append(p.apply_async(map_func, args=args))

    res = []
    for r in results:
        res += r.get(False)

    return res


def execution_select(map_func, name_func, lst: List, args=(), is_sig=False) -> List[Tuple[str, HealthFactor]]:
    # start = timeit.default_timer()
    # todo: disable the multi processing (2/3)
    if False and is_sig:
        results = start_multi_process_wrap(lst, map_func, args)
    else:
        new_args = (lst,) + args
        results = map_func(*new_args)
    # stop = timeit.default_timer()
    # logger.debug(f'{name_func} calculation finish: {{"process": {len(lst)}, "time": {stop-start}}}')
    return results
    

def complete_states_info(sta: States):
    users = list(sta.users_states.keys())
    # users = users_trimming(users, states, int(time.time()), False)

    users_with_args = gen_users_with_args(users)
    args = (states.ctokens, comet)
    results = execution_select(signal_calculate_health_factor, "hf", users_with_args, args=args)
    
    write_health_factor(results)
    return results


async def pt_prof_wrap(message):
    pr = cProfile.Profile()
    pr.enable()
    sig = await pt(message)
    pr.disable()

    # print the cprofile if the time cost is larger than 500 ms
    if sig > 0:
        pr.dump_stats("./temp/profile" + message["hash"][:8] + f"_{str(round(1000*sig, 1))}_" + ".out")

    # with open("profile" + message["hash"][:8] + ".out", "w") as file:
    #     stats = pstats.Stats(pr, stream=file).sort_stats("cumtime")
    #     stats.print_stats()


async def pt(message):
    start = timeit.default_timer()
    logger.debug(f'new message received: {{"hash":"{message["hash"]}", "height":{block_infos.block_num}}}')

    # signal verify and parsing
    try:
        res, aggr = signals.tx_filter_and_parsing(message, block_infos.gas_price)
        logger.info(f'source has new prices update: {{"num": {len(res)}, "infos":{res}, "hash":"{message["hash"]}"}}')
    except Exception as e:
        logger.info(f'source message invalid: {{"error":{e}, "msg":{message}}}')
        return 0

    # record necessary infos of pending transaction
    if message['type'] == '0x2':
        transaction = DynamicFeeTransaction.from_json_with_validation(message)
        raw_transaction = blxr_rlp.decode_lazy(blxr_rlp.encode(transaction)).hex()
        gas_fee = 0
        priority_fee = int(message['maxPriorityFeePerGas'], 16)
    else:
        transaction = Transaction.from_json_with_validation(message)
        raw_transaction = '0x' + convert.bytes_to_hex(blxr_rlp.encode(transaction))
        gas_fee = int(message['gasPrice'], 16)
        priority_fee = 0

    # set_signal_tx(raw_transaction, current_time)
    signal_recv["hash"] = message['hash']
    signal_recv["recv_height"] = block_infos.block_num
    signal_recv["tx_type"] = message['type']
    signal_recv["gas_price"] = gas_fee
    signal_recv["priority_fee"] = priority_fee
    signal_recv['raw_tx'] = raw_transaction 
    # logger.debug(f'source info recorded: {signal_recv}')

    # update local price cache
    tokens_addr = []
    delta_max = 0
    for r in res:
        token_addr = r[0] # Web3.toChecksumAddress(r[0])
        price = r[1]
        feed_decimals = r[2]
        decimals = states.ctokens[token_addr].configs.underlying_decimals

        # take venus protocol as an example
        # there are two types of price source, details in https://bscscan.com/address/0x7fabdd617200c9cb4dcf3dd2c41273e60552068a#code
        # 1: getChainlinkPrice(getFeed(symbol)) including "vBNB", "VAI" and token.symbol()
        # 2: prices[address(vToken)] (e.g. "XVS") or prices[address(token)] which is setted manually and query by assetPrices() API
        # for liquidation only vTokens are considered, thus "VAI" and "XVS" is ignored
        # Although "vBNB" are not scaled (so do "VAI" and  "XVS"), there is no different if it is passed to the price_scale function
        # currently no vToken are setted manually (tyep 2), see details in signals.py -> prices_setted_manually_test()
        new_price = int(price_scale(price, decimals, feed_decimals))

        old_price = states.ctokens[token_addr].price.price_current
        new_delta = new_price / old_price - 1
        if abs(new_delta) > abs(delta_max):
            delta_max = new_delta

        states.ctokens[token_addr].price.update(new_price, int(time.time()))
        
        tokens_addr.append(token_addr)
        # logger.debug(f'price update locally: {{"token":"{token_addr}", "price": {states.ctokens[token_addr].price.__dict__}}}')
    # logger.debug(f'price delta: {{"delta_max": {delta_max}}}')

    # filter users list based on token address
    # s = timeit.default_timer()
    # users = users_filtering_wrap(tokens_addr)
    # sorted_users = find_closet_hf_users(users, delta_max)
    users = users_pre_filtered.get(aggr, [])
    if len(users) == 0:
        return 0

    # index = find_closet_hf_users_index(users, delta_max)
    index = 10  # if len(users) < index, will not cause error
    sorted_users = users[0:index]
    # e = timeit.default_timer()
    # logger.debug(f'users filtered: {{"process": {len(sorted_users)}, "time": {e-s}}}') 
    
    # temp patch
    # if len(sorted_users) == 0:
    #     sorted_users = find_closet_hf_users(users, delta_max)

    # calculate users health factor
    # s = timeit.default_timer()
    sorted_users_with_args = gen_users_with_args(sorted_users)
    results = execution_select(signal_calculate_health_factor, "hf", sorted_users_with_args, args=(states.ctokens, comet,), is_sig=True)
    coroutines = execution_select(signal_simulate_health_factor, "liq", results, args=(states.ctokens, comet, block_infos.block_num, routers.pools, accounts, signal_recv, logger,), is_sig=True)
    await send_transactions(ws_main, coroutines, is_sig=True)
    e = timeit.default_timer()
    sig = e-start
    logger.debug(f'hf liquidation finish: {{"process": {len(coroutines)}, "time": {e-start}}}')

    # s = timeit.default_timer()
    write_health_factor(results)
    # e = timeit.default_timer()
    # logger.debug(f'hf cache finish: {{"process": {len(results)}, "time": {e-s}}}')
    
    print_send_transactions(coroutines)
    print_health_factor(results, "on_sig")
    write_data_from_queue(users_pending, users[index:])
    stop = timeit.default_timer()
    logger.debug(f'message handling finish: {{"total_time":{stop-start}}}')
    
    if len(coroutines):
        return sig
    else:
        return 0


def get_block_time(block_num):
    return block_infos.get_current_timestamp(block_num)


def get_reserves_value(token_addr, amount, is_col=False):
    token_addr = Web3.toChecksumAddress(token_addr)
    price = states.ctokens[token_addr].price.price_current
    if is_col:
        ex_rate = states.ctokens[token_addr].risks.exchange_rate 
        return amount * ex_rate // EXP_SCALE * price // EXP_SCALE 
    else:
        return  amount * price // EXP_SCALE


async def main():
    tasks = [
        asyncio.create_task(subscribe_event_light(states.gen_states_filter(reserves_init), users_subscribe_callback, logger, "light_users_sub")),
        asyncio.create_task(subscribe_event_light(gen_comet_filter(), comet_subscribe_callback, logger, "light_comet_sub")),
        asyncio.create_task(subscribe_event_light(gen_signals_filter(signals), signals_subscribe_callback, logger, "light_price_sub")),
        asyncio.create_task(get_chain_infos_full()),
        # asyncio.create_task(subscribe_tx_light(signals.signals_event_filter_light, get_pending_callback, logger, "light_pendSig_sub")),
        asyncio.create_task(get_pending_transactions_light(pt_prof_wrap)),
        asyncio.create_task(liquidation_idel(liquidation_idle_callback)),
        asyncio.create_task(subscribe_event_light(gen_liquidation_filter(reserves_init), liquidations_subscribe_callback, logger, "light_liquidations_sub")),
        # asyncio.create_task(subscribe_event_light(gen_events_filter([P_ALIAS['vai']], event_vai_repay.gen_topics()), vai_repay_subscribe_callback, logger, "light_event_vai_sub")),
        asyncio.create_task(tx_send_and_tracking_subscribe(process_receipts, logger))
    ]

    await asyncio.gather(*tasks)


async def send_transactions_ws(ws, results):
    tasks = []
    for res in results:
        signed_tx_raw = res[1]
        tasks.append(asyncio.create_task(send_tx_task(signed_tx_raw, ws)))

    await asyncio.gather(*tasks)


async def send_transactions(ws, results, is_sig=False):
    global send_lock
    if len(results) == 0:
        return

    if is_sig:
        txs = [
            signal_recv['raw_tx']
        ]
    else:
        txs = []

    dedup = {}
    profits = 0
    for res in results:
        index = res[0]
        signed_tx_raw = res[1]
        profit = res[2]

        txs.append(signed_tx_raw.hex())

        if dedup.get(index, None) is None:
            dedup[index] = 1
            profits += profit
    
    bnb_cost = 0.8 * profits / 320
    if bnb_cost > 0.06:
       bnb_cost = 0.06 
    
    mev_gas_price = bnb_cost / 21000
    if mev_gas_price < bnb_gas_price or send_lock:
        logger.info(f'bnb48 send skipped: {{"gas_price": {mev_gas_price}, "bundles": {txs}, "is_lock":{send_lock}}}')
    else:
        txs = [create_self_transfer(mev_gas_price, bnb48.acc)] + txs
        error_code = bnb48.send_puissant(txs, int(time.time())+4)
        if error_code == 0:
            logger.info(f'bnb48 send success: {{"gas_price": {mev_gas_price}, "bundles": {txs}, "signals":{signal_recv}}}')
        elif error_code in [-4804, -32000]:
            logger.error(f'bnb48 send error: {{"code": {error_code}, "gas_price": {mev_gas_price}, "bundles": {txs}}}') 
        else:
            send_lock = True
            logger.error(f'bnb48 send fails: {{"code": {error_code}, "gas_price": {mev_gas_price}, "bundles": {txs}}}')

    await asyncio.sleep(0.001)


def print_send_transactions(results):
    for res in results:
        index = res[0]
        signed_tx_raw = res[1]
        hash = Web3.keccak(signed_tx_raw)
        logger.info(f'send transaction: {{"index":"{index}", "hash":"{hash.hex()}"}}')


async def pre_set(results):
    async with connect(CONNECTION[NETWORK]['light']['url'],
        extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:

        coroutines = execution_select(signal_simulate_health_factor, "liq", results, (states.ctokens, comet, block_infos.block_num, routers.pools, accounts, None, logger,))
        await send_transactions_ws(ws, coroutines)


def handle_sigterm(signum, frame):
    print("Received SIGTERM, closing pool...")
    multi_pool.terminate()
    multi_pool.join()
    sys.exit(1)


if __name__ == '__main__':
    log_infos = P_ALIAS['log_file']['liq']
    logger = Logger(log_file_name=LOG_DIRECTORY + log_infos[0], log_level=LIQUDATION_LOG_LEVEL, logger_name=log_infos[1]).get_log()
    logger.info("Init starts")
    # logger_send_tx = Logger(log_file_name="liquidations_send", log_level=logging.INFO, logger_name="liquidation_send").get_log()
    send_lock = False
    send_counter = 0

    print("Init varaibles ...")
    # initialize local variable
    users_pending = queue.Queue()
    users_continue = queue.Queue(maxsize=1000)
    signal_recv = {}
    logger_liq_onchain = Logger(log_file_name=LOG_DIRECTORY + "liquidations_onchain", log_level=logging.DEBUG, logger_name="liquidation_call").get_log()
    liq_onchain = LiquidationCall(logger_liq_onchain)
    liq_onchain.get_block_time = get_block_time
    liq_onchain.get_reserves_value = get_reserves_value
    liq_onchain.w3_liqcall = Web3LiqListening()

    event_vai_repay = VaiState()
    users_to_liquidate = {}
    ws_main = None

    print("Init states from local file ...")
    # reload users and token infos and sync to latest block
    w3_liq = Web3CompoundVenues()

    accounts = init_accounts(w3_liq)
    bnb48 = Bnb48()
    bnb48.acc.nonce = w3_liq.w3.eth.get_transaction_count(bnb48.acc.get_address())
    bnb_gas_price = 60000000000 # bnb48.query_gas_price()

    reserves_init = w3_liq.query_markets_list()
    states = reload_states(reserves_init)
    states.plug_in = event_vai_repay

    print("Sync latest states and update local file ...")
    try:
        sync_states(states, w3_liq, reserves_init, 100)
    except Exception as e:
        logger.error(f'Sync to latest states failed: error {e}')
    
    for usr, _ in states.plug_in.storage.items():
        states.users_states[usr].vai_repay = w3_liq.query_user_vai_repay(usr)
    print(f'users vai repay updated: {{"users": {states.plug_in.storage}}}')
    states.plug_in.storage.clear()

    states.cache()
    sync_states(states, w3_liq, reserves_init)

    print("Init states by quering remotly ...")
    # query token related infos directly
    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_risks(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_init)
    comet = init_comet_configs(w3_liq, reserves_init, states.last_update)
    print(f"{comet.ctokens_collateral_factor}")
    signals = init_signals(w3_liq, reserves_init, states.ctokens)
    block_infos = init_block_infos(w3_liq)

    # router init should after ctoken configs init
    routers = RouterV2(ABIUniV2('pancakge_v2'))
    init_router_pools(routers, reserves_init, states.ctokens)
    print(routers.print_liq_pool())

    # todo: disable the multi processing (3/3)
    signal.signal(signal.SIGTERM, handle_sigterm)
    ctx = multiprocessing.get_context('spawn')
    core = 3  # cpu_count()
    # multi_pool = ctx.Pool(processes=core)
    multi_pool = FakePool()

    print("Precalculate users volume ...")
    # pre calculation in order to generate hot states
    results = complete_states_info(states)
    asyncio.run(pre_set(results))
    states = HighProfitSates(states, DESIRED_PROFIT_SCALE)

    print("Prefiltering users volume ...")
    users_pre_filtered = {}
    for aggr in list(signals.signal_token_map.keys()):
        # the aggr is in lower case
        tokens_addr, _ = signals.get_tokens_from_aggr(aggr)
        users = states.users_filtering(tokens_addr)
        users_trim = users_trimming_wrap(users, int(time.time())+1200)
        users_pre_filtered[aggr] = users_trim
    print(users_pre_filtered)

    print("Sync latest states again ...")
    # sync to latest block again if the last sync take a long time
    sync_states(states, w3_liq, reserves_init)
    logger.info("Init finishes")

    pid = os.getpid()
    logger.info(f"The pid of main program is {pid}")

    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f'Program terminated: {{"error": {e}, "trace": {traceback.format_exc()}}}')
    finally:
        multi_pool.terminate()
        multi_pool.join()
