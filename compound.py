import asyncio
import time
import os
import json
import timeit
import threading
import queue
import numpy as np
import multiprocessing
import traceback

from logger import Logger
from web3 import Web3
from websockets import connect
from tronpy.abi import trx_abi
from multiprocessing import cpu_count
from errors import MyError
from typing import Dict, List

from types_liq import LogReceiptLight, converter
from configs.config import CONNECTION, NETWORK, P_ALIAS, LIQUDATION_LOG_LEVEL, EXP_SCALE, ADDRESS_ZERO
from configs.web3_liq import Web3Liquidation
from configs.users import UserStates, gen_states_filter, reload_states, sync_states
from configs.comet import CometConfigs, gen_comet_filter, init_comet_configs
from configs.tokens import CompReserve, CtokenInfos,  complete_ctokens_configs_info, complete_ctokens_price_info, complete_ctokens_risks, query_exchange_rate
from configs.signals import Signals, init_signals
from configs.block import BlockInfos, init_block_infos

TRANSMIT_FUNC_SIG = bytes.fromhex('c9807539')
TRANSMIT_ARG_TYPES1 = ['bytes', 'bytes32[]', 'bytes32[]', 'bytes32']
TRANSMIT_ARG_TYPES2 = ['bytes32', 'bytes32', 'int192[]']

DESIRED_PROFIT = 1 * 10**18  # in USD
HF_THRESHOLD = 1


async def get_chain_infos_full():
    counter = 0
    json_rpc_str = '{"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["newHeads"]}'
    while True:
        counter += 1
        async with connect(CONNECTION[NETWORK]['ws']) as ws:
            json_rpc_str.replace("1,", str(counter) + ",")
            await ws.send(json_rpc_str)
            subscription_response = await ws.recv()
            logger.info(subscription_response)

            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=60)
                    on_message(message)
                except Exception as e:
                    logger.error(f"get chain infos error: {e}")
                    break

        if counter >= 5:
            raise Exception("subscribe new headers to full nodes too many times")
        else:
            logger.info("try to re-subscribe to full node")


def on_message(message):
    data = json.loads(message)

    if 'params' in data and 'result' in data['params']:
        result = data['params']['result']

        if 'number' in result:
            block_number = int(result['number'], 16)
            block_timestamp = int(result['timestamp'], 16)
            base_fee = int(result['baseFeePerGas'], 16)
            gas_price = w3_liq.w3.eth.gas_price

            # Update the local block number, timestamp, and base fee
            block_infos.update(block_number, block_timestamp, base_fee, gas_price)

            # Update one of the exchange rate every block
            index = block_number % len(reserves_init)
            token_addr = reserves_init[index]
            states.ctokens[token_addr].risks.exchange_rate = query_exchange_rate(w3_liq, token_addr)


async def get_pending_transactions_light(callback):
    while True:
        logger.info("try to subscribe to light node")
        try:
            async with connect(CONNECTION[NETWORK]['light']['url'], ping_interval=None,
                               extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
                await ws.send(
                    json.dumps({
                        'm': 'subscribe',
                        'p': 'txpool',
                        'tx_filters': signals.signals_event_filter
                    }))
                subscription_response = await ws.recv()
                logger.info(subscription_response.strip())

                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=1200)
                    except Exception as e:
                        logger.error("error: {}, websocket exception".format(e))
                        break

                    message = json.loads(message)
                    txs = message['Txs']
                    for tx in txs:
                        t = tx['Tx']
                        t['from'] = tx['From']
                        callback(t, tx_filter_and_parsing_wrap)

        except Exception as e:
            logger.error("{}, unable to subscribe to light node".format(e))
            break


def tx_filter_and_parsing_wrap(tx_attribute_dict):
    tx_filter_and_parsing(signals, block_infos, tx_attribute_dict)


def tx_filter_and_parsing(sig: Signals, blk: BlockInfos, tx_attribute_dict):
    """
    parsing the pending transactions in order to
    1. from 'input' to get the latest price update
    2. from 'to' to infer the A/ETH token
    :param blk:
    :param sig:
    :param tx_attribute_dict:
    :return:
    """
    sender = tx_attribute_dict['from']
    contract_addr = tx_attribute_dict['to']
    input_str = tx_attribute_dict['input']
    call_data_bin = bytes.fromhex(input_str[2:])

    if len(call_data_bin) <= 4:
        raise MyError("call data error")

    method_signature = call_data_bin[:4]
    if method_signature != TRANSMIT_FUNC_SIG:
        raise MyError("unknown function signature")

    signal_gasprice = tx_attribute_dict['gasPrice']
    local_gasprice = blk.gas_price
    if 0.9*local_gasprice > signal_gasprice:
        raise MyError(f'signal price too low: {{"local":{local_gasprice}, "signal":{signal_gasprice}}}')

    args = trx_abi.decode(TRANSMIT_ARG_TYPES1, call_data_bin[4:])
    args = trx_abi.decode(TRANSMIT_ARG_TYPES2, args[0])

    raw_report_ctx = args[0]
    signal_epoch = int(raw_report_ctx[-5:].hex(), 16)
    local_epoch = sig.signals_epoch.get(contract_addr, 0)
    if local_epoch > signal_epoch:
        raise MyError(f'signal stale report: {{"local":{local_epoch}, "signal":{signal_epoch}}}')
    else:
        sig.signals_epoch[contract_addr] = signal_epoch

    a = np.array(args[2])
    price = a[len(a)//2]

    # logger.debug("parsing result: {} {}".format(contract_addr, price))
    return no_name(sig, contract_addr, price)


def no_name(signals, aggregator, price) -> List:
    r = []
    aggr_infos = signals.signal_token_map[aggregator]
    token_addr = aggr_infos.token
    pair_symbols = aggr_infos.pair_symbols
    # logger.debug("the matched info of aggregator {} is {}".format(aggregator, aggr_infos))

    if pair_symbols[1] == P_ALIAS['base_currency']:
        r.append((token_addr, price))
    else:
        raise MyError("unrecognize aggregators")
    return r


def users_subscribe_callback(response: LogReceiptLight):
    block_num = response['blockNumber']
    block_hash = response['blockHash']
    logs = converter(response)

    # if not continues
    new_block = w3_liq.w3.eth.get_block(block_hash)
    parent_hash_str = '0x' + new_block['parentHash'].hex()
    if states.block_hash != parent_hash_str:
        pass

    if block_num < states.last_update:
        logger.info(f'logs out of date: {{"block_num":{block_num}, "logs":{logs}}}')
        return

    for log in logs:
        states.update(log)
    states.last_update = block_num
    logger.info(f'users in local cache updated: {{"block_num": {block_num}}}')


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


async def subscribe_light(filt, callback):
    async with connect(CONNECTION[NETWORK]['light']['url'], ping_interval=None,
                       extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
        await ws.send(
            json.dumps({
                'm': 'subscribe',
                'p': 'receipts',
                'event_filter': filt
            }))

        subscription_response = await ws.recv()
        logger.info(subscription_response)

        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=None)
                start = timeit.default_timer()
                logger.debug("user balance listening in control")
            except Exception as e:
                logger.error(f"unable to connect to get receipts of users: {e}")
                break

            response = json.loads(response)
            callback(response)
            stop = timeit.default_timer()
            logger.debug(f'user balance listening out of control:{{"total_time":{stop-start}}}')


async def users_polling_full(callback):
    filt = gen_states_filter(reserves_init)
    logger.debug("the user filter is {}".format(filt))

    while True:
        w3 = w3_liq.w3
        event_filter = w3.eth.filter(filt)
        while True:
            try:
                events = event_filter.get_new_entries()
            except Exception as e:
                await asyncio.sleep(12)
                logger.error("In users: {}".format(e))
                break

            if len(events) != 0:
                callback(events)
            await asyncio.sleep(6)


async def comet_configs_polling_full(callback):
    filt = gen_comet_filter()
    logger.debug("the comet configs filter is {}".format(filt))

    while True:
        event_filter = w3_liq.w3.eth.filter(filt)
        while True:
            try:
                events = event_filter.get_new_entries()
            except Exception as e:
                await asyncio.sleep(12)
                logger.error("In users: {}".format(e))
                break

            # logger.debug("users events received")
            if len(events) != 0:
                callback(events)
            await asyncio.sleep(6)


def calculate_health_factor_wrap(usr):
    return calculate_health_factor(usr, states.users_states[usr].reserves, states.ctokens, comet)


def calculate_health_factor(usr: str, reserves: Dict[str, CompReserve], ctk: Dict[str, CtokenInfos], comet: CometConfigs):
    sum_collateral = 0
    sum_borrow_plus_effects = 0

    for token_addr, reserve in reserves.items():
        collateral_balance = reserve.col_amount
        debt_balance = reserve.debt_amount
        interest_index = reserve.debt_interest

        price = ctk[token_addr].price.price_current

        collateral_factor = comet.ctokens_collateral_factor[token_addr]
        exchange_rate = ctk[token_addr].risks.exchange_rate
        if collateral_factor > 0 and collateral_balance > 0:
            sum_collateral += ((collateral_factor * exchange_rate // EXP_SCALE) * price // EXP_SCALE) * collateral_balance // EXP_SCALE

        if debt_balance > 0:
            borrow_index = ctk[token_addr].risks.borrow_index
            debt_balance = debt_balance * borrow_index // interest_index
            sum_borrow_plus_effects += debt_balance * price // EXP_SCALE

        if token_addr == ADDRESS_ZERO:
            pass

        print(f"user {usr}, reserve {token_addr}, price {price}, ctoken balance {collateral_balance}, borrow balance {debt_balance}, exchange rate {exchange_rate}, collateral factor {collateral_factor}")
        # logger.debug(f"user {usr}, reserve {token_addr}, price {price}, ctoken balance {collateral_balance}, borrow balance {debt_balance}, exchange rate {exchange_rate}, collateral factor {collateral_factor}")

    if sum_borrow_plus_effects <= 0:
        # logger.debug("user {} no borrows".format(usr[0]))
        return 0
    else:
        health_factor = sum_collateral / sum_borrow_plus_effects
        short_fall = sum_borrow_plus_effects - sum_collateral
        liquidity = 0
        if short_fall < 0:
            short_fall = 0
            liquidity = sum_collateral - sum_borrow_plus_effects

        # logger.debug(f"user {usr} (0, liquidity {liquidity}, shortfall {short_fall}), health factor {health_factor}, sum collateral {sum_collateral}, sum borrow {sum_borrow_plus_effects}")
        print(f"user: {usr} account liquidity: (0, {liquidity}, {short_fall}), health factor: {health_factor}, sum collateral {sum_collateral}, sum borrow {sum_borrow_plus_effects}")

        return health_factor


# todo: doTransferIn simulation?
def do_transfer_in(amount):
    return amount


def mul_scalar_truncate(ratio, repay_amount):
    return ratio * repay_amount // EXP_SCALE


def liquidation_simulation(reserves: Dict[str, CompReserve], ctokens: Dict[str, CtokenInfos], com: CometConfigs):
    debts = []
    for ctoken_addr, data in reserves.items():
        debt_balance = data.debt_amount
        interest_index = data.debt_interest
        borrow_index = ctokens[ctoken_addr].risks.borrow_index

        debt_balance = debt_balance * borrow_index // interest_index
        if debt_balance > 0:
            # unused
            # actual_repay_amount = do_transfer_in(debt_balance)
            debt_max = mul_scalar_truncate(com.closs_factor, debt_balance)
            debt_price = ctokens[ctoken_addr].price.price_current
            debt_normalize = debt_price * debt_max // EXP_SCALE
            debts.append(
                (debt_normalize, ctoken_addr, debt_max)
            )

    if len(debts) == 0:
        return [], []

    debts = sorted(debts, reverse=True)
    target_debt = debts[0]
    ctoken_addr = target_debt[1]
    actual_repay_amount = target_debt[2]
    debt_price = ctokens[ctoken_addr].price.price_current

    collaterals = []
    for token_addr, data in reserves.items():
        collateral_balance = data.col_amount
        if collateral_balance > 0:
            price = ctokens[token_addr].price.price_current
            exchange_rate = ctokens[token_addr].risks.exchange_rate
            numerator = com.liq_incentive * debt_price // EXP_SCALE
            denominator = price * exchange_rate // EXP_SCALE
            ratio = numerator * EXP_SCALE // denominator
            seize_tokens = mul_scalar_truncate(ratio, actual_repay_amount)

            if collateral_balance < seize_tokens:
                continue

            # refer to getHypotheticalAccountLiquidityInternal
            profit_apprx = (seize_tokens * exchange_rate // EXP_SCALE * price - actual_repay_amount * debt_price) // EXP_SCALE
            collaterals.append((profit_apprx, token_addr, seize_tokens, actual_repay_amount))

    collaterals = sorted(collaterals, reverse=True)
    return collaterals, target_debt


def liquidation_init(usr_addr: str, reserves: Dict[str, CompReserve], ctokens: Dict[str, CtokenInfos], comet: CometConfigs):
    collaterals, debt = liquidation_simulation(reserves, ctokens, comet)
    if len(debt) == 0:
        return None, None

    if len(collaterals) == 0:
        logger.info("bad debts, please add user {} into black lists".format(usr_addr))
        return None, None

    onchain_swap_profit_max = collaterals[0][0]
    logger.debug("user {}, target debt {}, can get collaterals {}, max on-chain swap profit {}".
                 format(usr_addr, debt, collaterals, onchain_swap_profit_max))

    if onchain_swap_profit_max < DESIRED_PROFIT:
        logger.debug("user {} profit {} is too low, liquidation abandoned".format(usr_addr, onchain_swap_profit_max))
        return None, None

    # logger.info("user {} with sufficient profits {}".format(usr_addr, onchain_swap_profit_max))
    # col token, debt token, user_addr, debt_to_cover, receive_atoken
    return (collaterals[0][1], debt[1], usr_addr, collaterals[0][3], False), onchain_swap_profit_max


def signal_simulate_health_factor(results):
    for res in results:
        usr = res[0]
        new_health_factor = res[1]

        if 1 > new_health_factor/HF_THRESHOLD > 0:
            liquidation_params, revenue = liquidation_init(usr, states.users_states[usr].reserves, states.ctokens, comet)

            if liquidation_params is not None:
                logger.info(f"revenue ({revenue/10**18} ether) liquidation start, params {liquidation_params}")
                # liquidation_start(liquidation_params)


def users_filtering_wrap(tokens_addr):
    users = states.users_filtering(tokens_addr)
    logger.debug("from token {} filtered {} users".format(tokens_addr, len(users)))
    return users


def write_health_factor(results: List, block_time: int):
    logger.debug('write health factor start')
    for res in results:
        usr = res[0]
        states.users_states[usr].update_health_factor(res[1], block_time)


def calculate_health_factor_fake_inverse(health_factor_after, delta):
    if delta < 0:
        f_delta = 1 + delta
    else:
        f_delta = 1/(1 + delta)

    return health_factor_after / f_delta


def find_closet_hf_users(users, delta_max):
    thres = calculate_health_factor_fake_inverse(HF_THRESHOLD, delta_max)

    filtered_users = []
    for usr in users:
        hf = states.users_states[usr].health_factor.value
        if hf < thres:
            filtered_users.append(usr)

    return filtered_users


def find_closet_hf_users_index(sorted_users, delta_max):
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


def start_multi_process_wrap(targets, map_func, args_par):
    return start_multi_process(pool, targets, core, map_func, args_par)


def start_multi_process(p, targets, target_num, map_func, args_par):
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


def start_for_loop(targets):
    res = []
    for usr in targets:
        res.append([usr, calculate_health_factor_wrap(usr), int(time.time())])

    return res


def signal_calculate_health_factor(tim_users):
    stop1 = timeit.default_timer()
    if len(tim_users) > 2000:
        args = ()
        results = start_multi_process_wrap(tim_users, start_for_loop, args)
    else:
        results = start_for_loop(tim_users)
    stop2 = timeit.default_timer()
    logger.debug(f'hf calculation finish: {{"process": {len(tim_users)}, "time": {stop2-stop1}}}')

    return results


def pt(message, f):
    sta = timeit.default_timer()
    logger.debug(f'new message received: {{"hash":"{message["hash"]}"}}')

    # signal verify and parsing
    try:
        res = f(message)
        logger.info("tx {}: has {} new prices update: {}".format(message['hash'], len(res), res))
    except Exception as e:
        logger.error(e)
        return

    # update local price cache
    tokens_addr = []
    delta_max = 0
    for r in res:
        token_addr = Web3.toChecksumAddress(r[0])
        price = r[1]
        new_price = states.ctokens[token_addr].price_scale(price)

        old_price = states.ctokens[token_addr].price.price_current
        new_delta = new_price / old_price - 1
        if abs(new_delta) > abs(delta_max):
            delta_max = new_delta

        states.ctokens[token_addr].price.update(new_price, int(time.time()))
        tokens_addr.append(token_addr)

    # filter users list based on token address
    users = users_filtering_wrap(tokens_addr)
    # index = find_closet_hf_users_index(users, delta_max)
    # sorted_users = users[0:index]
    sorted_users = find_closet_hf_users(users, delta_max)

    # calculate users health factor
    results = signal_calculate_health_factor(sorted_users)
    signal_simulate_health_factor(results)

    block_time = block_infos.block_time
    write_health_factor(results, block_time)
    stop = timeit.default_timer()


async def main():
    tasks = [
        asyncio.create_task(subscribe_light(gen_states_filter(reserves_init), users_subscribe_callback)),
        asyncio.create_task(subscribe_light(gen_comet_filter(), comet_subscribe_callback)),
        asyncio.create_task(get_chain_infos_full()),
        asyncio.create_task(get_pending_transactions_light(pt))
    ]

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    log_infos = P_ALIAS['log_file']['liq']
    logger = Logger(log_file_name=log_infos[0], log_level=LIQUDATION_LOG_LEVEL, logger_name=log_infos[1]).get_log()

    # reload users and token infos and sync to latest block
    w3_liq = Web3Liquidation(provider_type='http')
    reserves_init = w3_liq.query_markets_list()
    states = reload_states(reserves_init)
    sync_states(states, w3_liq, reserves_init)

    # query token related infos directly
    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_risks(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_init)
    comet = init_comet_configs(w3_liq, reserves_init)
    signals = init_signals(w3_liq, reserves_init, states.ctokens)
    block_infos = init_block_infos(w3_liq)

    # sync to latest block again if the last sync take a long time
    sync_states(states, w3_liq, reserves_init)
    states.cache()
    logger.info("Init finishes")

    pid = os.getpid()
    logger.info("pid of main program is {}".format(pid))

    ctx = multiprocessing.get_context('spawn')
    core = cpu_count()
    pool = ctx.Pool(processes=core)

    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f'Program terminated: {{"error": {e}, "trace": {traceback.format_exc()}}}')

