import asyncio
import time
import os
import json
import timeit
import threading
import queue
import numpy as np

from logger import Logger
from web3 import Web3
from websockets import connect
from tronpy.abi import trx_abi
from multiprocessing import cpu_count, Manager, Pool

from configuration import (
    config_init, get_reserves, get_signal_filters, token_aggregator_mapping,
    price_cache_read, price_cache_write, get_liquidation_incentive,
    COMPOUND_ALIAS, LIQUDATION_LOG_LEVEL, EXP_SCALE,
    CONNECTION, NETWORK, provider, cerc20_interface
)

from get_users_from_logs import (
    COMPOUND_V3_USERS_FILTER_TEMP, log_parser_wrap,
    get_exchange_rate, get_users_start,
    get_borrow_index,
    users_filtering, set_health_factor
)

from get_configs_from_comet import (
    COMPOUND_V3_CONFIGS_FILTER_TEMP,
    comet_configs_log_parser_wrap,
    get_collateral_factor,
)

TRANSMIT_FUNC_SIG = bytes.fromhex('c9807539')
TRANSMIT_ARG_TYPES1 = ['bytes', 'bytes32[]', 'bytes32[]', 'bytes32']
TRANSMIT_ARG_TYPES2 = ['bytes32', 'bytes32', 'int192[]']

DESIRED_PROFIT = 1 * 10**6  # todo: need testing
HF_THRESHOLD = 1  # todo: need testing
HF_LOWER = HF_THRESHOLD*0.8
HF_UPPER = HF_THRESHOLD*1.4
HF_BASE = HF_THRESHOLD*1.2


async def get_pending_transactions_light_v2(callback):
    while True:
        logger.info("try to subscribe to light node")
        try:
            async with connect(CONNECTION[NETWORK]['light']['url'], ping_interval=None,
                               extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
                await ws.send(
                    json.dumps({
                        'm': 'subscribe',
                        'p': 'txpool',
                        'tx_filters': get_signal_filters()
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
                        callback(t, True, tx_filter_and_parsing)

        except Exception as e:
            logger.error("{}, unable to subscribe to light node".format(e))
            break


def tx_filter_and_parsing(tx_attribute_dict):
    """
    parsing the pending transactions in order to
    1. from 'input' to get the latest price update
    2. from 'to' to infer the A/ETH token
    :param tx_attribute_dict:
    :return:
    """
    contract_addr = tx_attribute_dict['to']
    input_str = tx_attribute_dict['input']
    call_data_bin = bytes.fromhex(input_str[2:])

    if len(call_data_bin) <= 4:
        return Error

    method_signature = call_data_bin[:4]
    if method_signature == TRANSMIT_FUNC_SIG:
        try:
            args = trx_abi.decode(TRANSMIT_ARG_TYPES1, call_data_bin[4:])
            args = trx_abi.decode(TRANSMIT_ARG_TYPES2, args[0])

            # 链上的中位数算法为简单的2分，而非数学中的中位数定义
            a = np.array(args[2])
            # price = np.median(a)
            price = a[len(a)//2]

            logger.debug("parsing result: {} {}".format(contract_addr, price))
            return no_name(contract_addr, price)
        except AssertionError:
            return AssertionError

    return Error


def no_name(aggregator, price):
    r = []
    aggr_infos = token_aggregator_mapping(aggregator)
    token_addr = aggr_infos[0]
    aggr_tokens = aggr_infos[1]
    logger.debug("the matched info of aggregator {} is {}".format(aggregator, aggr_infos))

    if aggr_tokens[1] == COMPOUND_ALIAS['base_currency']:
        r.append((token_addr, price))
    else:
        return Error
    return r


async def users_subscribe_full(callback):
    filt = json.loads(COMPOUND_V3_USERS_FILTER_TEMP)
    filt['address'] = get_reserves()
    logger.debug("the user filter is {}".format(filt))

    while True:
        w3 = Web3(provider)
        event_filter = w3.eth.filter(filt)
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


async def comet_configs_subscribe_full(callback):
    filt = json.loads(COMPOUND_V3_CONFIGS_FILTER_TEMP)
    filt['address'] = COMPOUND_ALIAS['comet']
    logger.debug("the comet configs filter is {}".format(filt))

    while True:
        w3 = Web3(provider)
        event_filter = w3.eth.filter(filt)
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


def message_check(message, block_number):
    w3 = Web3(provider)
    try:
        message['to'] = Web3.toChecksumAddress(message['to'])
        message['from'] = Web3.toChecksumAddress(message['from'])

        w3.eth.call(message, block_number)
    except Exception as e:
        logger.info("message simulate error: {}".format(e))
        return False

    return True


def calculate_health_factor(usr, exchange_rates):
    sum_collateral = 0
    sum_borrow_plus_effects = 0

    for token_addr, reserve in usr[2].items():
        collateral_balance = reserve[0]
        debt_balance = reserve[1]
        interest_index = reserve[2]
        borrow_index = get_borrow_index(token_addr)
        debt_balance = debt_balance * borrow_index // interest_index

        price = price_cache_read(token_addr)
        # todo: how to get exchange_rate
        exchange_rate = exchange_rates[token_addr]
        collateral_factor = get_collateral_factor(token_addr)

        if collateral_factor != 0 and collateral_balance > 0:
            sum_collateral += collateral_factor * exchange_rate // EXP_SCALE * price // EXP_SCALE * collateral_balance // EXP_SCALE

        if debt_balance > 0:
            sum_borrow_plus_effects += price * debt_balance // EXP_SCALE

    if sum_borrow_plus_effects <= 0:
        return 0
    else:
        health_factor = sum_collateral / sum_borrow_plus_effects
        short_fall = sum_borrow_plus_effects - sum_collateral
        logger.debug("user {} health factor: {}, sum collateral {}, sum borrow {}, shortfall {}".
                     format(usr[0], health_factor, sum_collateral, sum_borrow_plus_effects, short_fall))
        return health_factor


# todo: doTransferIn simulation？ 只影响seize_tokens计算
def do_transfer_in(amount):
    return amount


def mul_scalar_truncate(ratio, repay_amount):
    return ratio * repay_amount // EXP_SCALE


def liquidation_simulation(reserves, exchange_rates, liquidation_incent):
    debts = []
    max_liquidatable_debt = 0
    for token_addr, data in reserves.items():
        debt_balance = data[1]
        interest_index = data[2]
        borrow_index = get_borrow_index(token_addr)
        debt_balance = debt_balance * borrow_index // interest_index
        actual_repay_amount = do_transfer_in(debt_balance)
        if debt_balance > max_liquidatable_debt:
            max_liquidatable_debt = debt_balance
            debts.append(
                (token_addr, actual_repay_amount)
            )

    if len(debts) == 0:
        return [], []

    debts = sorted(debts, reverse=True)
    target_debt = debts[0]

    collaterals = []
    for token_addr, data in reserves.items():
        collateral_balance = data[0]
        if collateral_balance > 0:
            price = price_cache_read(token_addr)
            debt_price = price_cache_read(target_debt[0])
            exchange_rate = exchange_rates[token_addr]
            actual_repay_amount = target_debt[1]

            numerator = liquidation_incent * debt_price // EXP_SCALE
            denominator = price * exchange_rate // EXP_SCALE
            ratio = numerator * EXP_SCALE // denominator
            seize_tokens = mul_scalar_truncate(ratio, actual_repay_amount)

            if collateral_balance < seize_tokens:
                continue

            # refer to getHypotheticalAccountLiquidityInternal
            profit = (seize_tokens * price - debt_balance * debt_price) // EXP_SCALE
            collaterals.append((profit, token_addr, seize_tokens, debt_balance, actual_repay_amount))

    collaterals = sorted(collaterals, reverse=True)
    return collaterals, target_debt


def liquidation_init(usr, exchange_rates, liq_incentive):
    usr_addr = usr[0]
    reserves = usr[2]

    collaterals, debt = liquidation_simulation(reserves, exchange_rates, liq_incentive)
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
    # token address, token address, user_addr, debt_to_cover, receive_atoken
    return (collaterals[0][1], debt[2], usr_addr, collaterals[0][5], False), onchain_swap_profit_max


def health_factor_and_liquidation(usr, block_num, exchange_rates, liq_incentive, q):
    if usr[3] is None or (HF_THRESHOLD <= usr[3][0] <= HF_BASE):
        new_health_factor = calculate_health_factor(usr, exchange_rates)
        q.put((usr[0], new_health_factor), block=False)
    elif HF_BASE < usr[3][0] < HF_UPPER or HF_LOWER < usr[3][0] < HF_THRESHOLD:
        if usr[3][1]+3600 < block_num:
            new_health_factor = calculate_health_factor(usr, exchange_rates)
            q.put((usr[0], new_health_factor), block=False)
        else:
            return
    elif usr[3][0] >= HF_UPPER:
        if usr[3][1]+3600*3 < block_num:
            new_health_factor = calculate_health_factor(usr, exchange_rates)
            q.put((usr[0], new_health_factor), block=False)
        else:
            return
    else:  # usr[3][0] <= HF_LOWER
        return

    if HF_THRESHOLD > new_health_factor > HF_LOWER:  # 1 ether
        liquidation_params, revenue = liquidation_init(usr, exchange_rates, liq_incentive)

        if liquidation_params is not None:
            logger.info("revenue ({} ether) liquidation start, params {}".format(revenue/10**18, liquidation_params))
            # liquidation_start(liquidation_params)


def multi_threads(users, block_num, exchange_rates, liq_incentive, q):
    thread_pool = []

    for usr in users:
        thd = threading.Thread(target=health_factor_and_liquidation, args=(usr, block_num, exchange_rates, liq_incentive, q))
        thd.start()
        thread_pool.append(thd)

    for th in thread_pool:
        th.join()


def users_filtering_wrap(tokens_addr):
    users = users_filtering(tokens_addr)
    logger.debug("from token {} filtered {} users".format(tokens_addr, len(users)))
    return users


def write_health_factor(q, block_time):
    c = 0
    logger.debug('write health factor start')
    while True:
        try:
            res = q.get(block=True, timeout=0.01)
            set_health_factor(res[0], res[1], block_time)
            c += 1
        except queue.Empty:
            break

    # logger.debug('taking {} results from mutliprocessing: {}'.format(len(results), results))
    return c


def query_exchange_rates():
    w3 = Web3(provider)

    exchange_rate_dict = {}
    reserves = get_reserves()
    for token_addr in reserves:
        token_contract = w3.eth.contract(address=token_addr, abi=cerc20_interface)
        exchange_rate = token_contract.functions.exchangeRateStored().call()
        exchange_rate_dict[token_addr] = exchange_rate
    return exchange_rate_dict


def cal_exchange_rates():
    exchange_rate_dict = {}
    reserves = get_reserves()
    for token_addr in reserves:
        exchange_rate = get_exchange_rate(token_addr)
        exchange_rate_dict[token_addr] = exchange_rate
    return exchange_rate_dict

def pt(message, is_check, f):
    w3 = Web3(provider)
    block_number = w3.eth.get_block_number()
    if is_check:
        if not message_check(message, block_number):
            return

    sta = timeit.default_timer()
    logger.debug("receive height {}, start message handling: {}".format(block_number, message))

    try:
        res = f(message)
        logger.info("tx {}: has {} new prices update: {}".format(message['hash'], len(res), res))
    except Exception as e:
        logger.error(e)
        return

    tokens_addr = []
    for r in res:
        token_addr = Web3.toChecksumAddress(r[0])
        new_price = r[1]
        old_price = price_cache_read(token_addr)
        logger.debug("the prices of token {}: old {}, new {}".
                     format(token_addr, old_price, new_price))

        price_cache_write(token_addr, new_price)
        tokens_addr.append(token_addr)

    users = users_filtering_wrap(tokens_addr)
    length = len(users)
    if length == 0:
        return

    query_start = timeit.default_timer()
    exchange_rates = query_exchange_rates()
    query_end = timeit.default_timer()

    liquidation_incent = get_liquidation_incentive()
    logger.debug("liquidation incentive: {}; query exchange rates: {}, time: {}".
                 format(liquidation_incent, exchange_rates, query_end - query_start))

    core = cpu_count()
    p = Pool(core)
    q = Manager().Queue()

    for i in range(core):
        left = i*length//core
        right = (i+1)*length//core
        p.apply_async(multi_threads, args=(users[left:right], block_number, exchange_rates, liquidation_incent, q,))

    p.close()
    p.join()

    counter = write_health_factor(q, block_number)
    stop = timeit.default_timer()
    if counter != 0:
        logger.debug('finish message handling, users {}, process {}, total time: {} ava: {} '.format(length, counter, stop - sta, (stop - sta)/counter))
    else:
        logger.debug('finish message handling, users {}, process {}, total time: {}'.format(length, counter, stop - sta))


async def main():
    tasks = [
        asyncio.create_task(users_subscribe_full(log_parser_wrap)),
        asyncio.create_task(comet_configs_subscribe_full(comet_configs_log_parser_wrap)),
        asyncio.create_task(get_pending_transactions_light_v2(pt))
    ]

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    log_infos = COMPOUND_ALIAS['log_file']['liq']
    logger = Logger(log_file_name=log_infos[0], log_level=LIQUDATION_LOG_LEVEL, logger_name=log_infos[1]).get_log()

    config_init()
    # reserve_config_cache_init(reserves)
    # reserve_price_cache_init(reserves)

    get_users_start()
    get_users_start()  # double check, if the users_xxx.json is too old
    logger.info("Init finishes")

    pid = os.getpid()
    logger.info("pid of main program is {}".format(pid))

    while True:
        try:
            asyncio.run(main())
        except:
            time.sleep(1)
            logger.info("Program restart")
            continue
