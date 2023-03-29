import asyncio
import time
import os
import timeit
import threading
import queue
import multiprocessing
import traceback

from logger import Logger
from web3 import Web3
from tronpy.abi import trx_abi
from multiprocessing import cpu_count
from errors import MyError
from typing import Dict, List

from utils import WSconnect, polling_full, subscribe_to_node, subscribe_tx_light, subscribe_event_light
from types_liq import LogReceiptLight, converter
from configs.config import CONNECTION, NETWORK, P_ALIAS, LIQUDATION_LOG_LEVEL, EXP_SCALE, ADDRESS_ZERO
from configs.web3_liq import Web3Liquidation
from configs.users import States, HighProfitSates, HealthFactor, gen_states_filter, reload_states, sync_states
from configs.comet import CometConfigs, gen_comet_filter, init_comet_configs
from configs.tokens import CompReserve, CtokenInfos,  complete_ctokens_configs_info, complete_ctokens_risks, query_exchange_rate
from configs.signals import init_signals, gen_signals_filter, complete_ctokens_price_info, price_scale
from configs.block import init_block_infos

DESIRED_PROFIT = 1 * 10**18  # in USD
HF_THRESHOLD = 1


def on_message(message: Dict):
    if 'params' in message and 'result' in message['params']:
        result = message['params']['result']

        if 'number' in result:
            block_number = int(result['number'], 16)
            block_timestamp = int(result['timestamp'], 16)
            base_fee = int(result['baseFeePerGas'], 16)
            gas_price = w3_liq.w3.eth.gas_price

            # task 1: Update the local block number, timestamp, and base fee
            block_infos.update(block_number, block_timestamp, base_fee, gas_price)

            # task 2: Update one of the exchange rate every block
            index = block_number % len(reserves_init)
            token_addr = reserves_init[index]
            states.ctokens[token_addr].risks.exchange_rate = query_exchange_rate(w3_liq, token_addr)

            # task 3: timeout the staled price
            for reserve in reserves_init:
                states.ctokens[reserve].price.revert()


async def get_chain_infos_full():
    counter = 0
    json_rpc = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["newHeads"]}
    while True:
        counter += 1
        json_rpc['id'] = counter
        ws = WSconnect(CONNECTION[NETWORK]['ws'])

        subscribe_to_node(ws, json_rpc, on_message)

        if counter >= 5:
            raise Exception("subscribe new headers to full nodes too many times")
        else:
            logger.info("try to re-subscribe to full node")


def get_pending_callback(message):
    txs = message['Txs']
    for tx in txs:
        t = tx['Tx']
        t['from'] = tx['From']
        pt(t)


async def get_pending_transactions_light(callback):
    while True:
        logger.info("try to subscribe to light node")
        try:
            subscribe_tx_light(signals.signals_event_filter_light, callback)

        except Exception as e:
            logger.error("{}, unable to subscribe to light node".format(e))
            break


'''
async def continues_liquidation(callback):
    while True:
        start = timeit.default_timer()
        logger.debug("continues liquidation in control")
        try:
            callback(current_time, block_number)
            
            stop = timeit.default_timer()
            logger.debug(f'continues liquidation out of control: {{"total_time": {stop-start}, "height": {block_number}}}')
            await asyncio.sleep(0.1)

        except Exception as e:
            raise Exception(f"error in continues liquidation: {e}")


async def continues_health_factor_calculation(current_time, block_num):
    # task 1: listen to the users by block, to generate top-of-block
    results = get_continues_users_queue(current_time)
    if len(results) != 0:   
        logger.info(f"continues liquidations start at {block_num} + 1")
        users = deduplication(results)
        users_trim = users_trimming_v3(users, 0, current_time, False, True)   
        await pre_calculate_health_factor(users_trim, current_time, is_all=True)

    # task 2: finish the hf calculation of the remaining users
    users_trim = get_pending_users_queue()
    if len(users_trim) != 0:
        logger.info(f"continues pending users start at {block_num} + 1")   
        await pre_calculate_health_factor(users_trim, current_time, is_signal=signal_infos.get('hash', ''))
        return
    
    # task3: update infos periodically
    now = time.time() % INTVL  #
    num = 180 // INTVL  # trigger every 3 mins
    index = block_num//num
    if block_num%num == 1 and now <= 0.12:
        logger.info(f"continues random sample start at {block_num} + 1, index {index}")
        # users = get_user_random_samples(SAMPLING_LIMIT)
        users = get_user_spesific_samples(SAMPLING_LIMIT, index)
        users_trim = users_trimming_v3(users, 0, current_time, False, False)
        await pre_calculate_health_factor(users_trim, current_time)
    elif block_num%num == 3 and now <= 0.12:
        token_addr = get_reserves_key_by_index(index)
        logger.info(f"continues pre users filtering, index {index}, token {token_addr}")
        users = users_filtering_v2([token_addr])
        users_trim = users_trimming_v3(users, 0, current_time+1200, True, False) 
        set_users_prefiltered(token_addr, users_trim)
'''


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
    states.block_hash = block_hash
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


def signals_subscribe_callback(response: LogReceiptLight):
    logs = converter(response)
    for log in logs:
        contract_addr = log['address']
        aggr_infos = signals.signal_token_map[contract_addr]
        ctoken_addr = aggr_infos.token
        decimals = states.ctokens[ctoken_addr].configs.decimals
        states.ctokens[ctoken_addr].price.comfirm(log, decimals)


async def users_polling_full(callback):
    filt = gen_states_filter(reserves_init)
    logger.debug("the user filter is {}".format(filt))
    polling_full(w3_liq, filt, callback)


async def comet_configs_polling_full(callback):
    filt = gen_comet_filter()
    logger.debug("the comet configs filter is {}".format(filt))
    polling_full(w3_liq, filt, callback)


def calculate_health_factor_wrap(usr) -> (str, HealthFactor):
    return calculate_health_factor(usr, states.users_states[usr].reserves, states.ctokens, comet)


def calculate_health_factor(usr: str, reserves: Dict[str, CompReserve], ctk: Dict[str, CtokenInfos], comet: CometConfigs) -> (str, HealthFactor):
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
        return usr, HealthFactor(0, sum_borrow_plus_effects, int(time.time()))
    else:
        health_factor = sum_collateral / sum_borrow_plus_effects
        short_fall = sum_borrow_plus_effects - sum_collateral
        liquidity = 0
        if short_fall < 0:
            short_fall = 0
            liquidity = sum_collateral - sum_borrow_plus_effects

        # logger.debug(f"user {usr} (0, liquidity {liquidity}, shortfall {short_fall}), health factor {health_factor}, sum collateral {sum_collateral}, sum borrow {sum_borrow_plus_effects}")
        print(f"user: {usr} account liquidity: (0, {liquidity}, {short_fall}), health factor: {health_factor}, sum collateral {sum_collateral}, sum borrow {sum_borrow_plus_effects}")

        return usr, HealthFactor(health_factor, sum_borrow_plus_effects, int(time.time()))


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


def signal_simulate_health_factor(results: List[(str, HealthFactor)]):
    for res in results:
        (usr, new_health_factor) = res
        if 1 > new_health_factor.value/HF_THRESHOLD > 0:
            liquidation_params, revenue = liquidation_init(usr, states.users_states[usr].reserves, states.ctokens, comet)

            if liquidation_params is not None:
                logger.info(f"revenue ({revenue/10**18} ether) liquidation start, params {liquidation_params}")
                # liquidation_start(liquidation_params)


def users_filtering_wrap(tokens_addr):
    users = states.users_filtering(tokens_addr)
    logger.debug("from token {} filtered {} users".format(tokens_addr, len(users)))
    return users


def write_health_factor(results: List[(str, HealthFactor)]):
    logger.debug('write health factor start')
    for res in results:
        (usr, new_health_factor) = res
        states.users_states[usr].health_factor = new_health_factor


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


def start_multi_process_wrap(targets, map_func, args_par) -> List[(str, HealthFactor)]:
    return start_multi_process(pool, targets, core, map_func, args_par)


def start_multi_process(p, targets, target_num, map_func, args_par) -> List[(str, HealthFactor)]:
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


def start_for_loop(targets) -> List[(str, HealthFactor)]:
    res = []
    for usr in targets:
        res.append(calculate_health_factor_wrap(usr))

    return res


def signal_calculate_health_factor(tim_users) -> List[(str, HealthFactor)]:
    stop1 = timeit.default_timer()
    if len(tim_users) > 2000:
        args = ()
        results = start_multi_process_wrap(tim_users, start_for_loop, args)
    else:
        results = start_for_loop(tim_users)
    stop2 = timeit.default_timer()
    logger.debug(f'hf calculation finish: {{"process": {len(tim_users)}, "time": {stop2-stop1}}}')

    return results


def complete_states_info(states: States):
    users = list(states.users_states.keys())
    results = signal_calculate_health_factor(users)
    write_health_factor(results)


def pt(message):
    sta = timeit.default_timer()
    logger.debug(f'new message received: {{"hash":"{message["hash"]}"}}')

    # signal verify and parsing
    try:
        # different signal may use different parser
        res = signals.tx_filter_and_parsing(message, block_infos.gas_price)
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
        new_price = price_scale(price, states.ctokens[token_addr].configs.decimals)

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

    write_health_factor(results)
    stop = timeit.default_timer()


async def main():
    tasks = [
        asyncio.create_task(subscribe_event_light(gen_states_filter(reserves_init), users_subscribe_callback)),
        asyncio.create_task(subscribe_event_light(gen_comet_filter(), comet_subscribe_callback)),
        asyncio.create_task(subscribe_event_light(gen_signals_filter(), signals_subscribe_callback)),
        asyncio.create_task(get_chain_infos_full()),
        asyncio.create_task(get_pending_transactions_light(get_pending_callback))
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

    # pre calculation in order to generate hot states
    complete_states_info(states)
    states = HighProfitSates(states, DESIRED_PROFIT)

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

