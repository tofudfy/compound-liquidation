import json
import time

from tronpy.abi import trx_abi
from web3 import Web3

from configuration import (
    provider, NETWORK, COMPOUND, SELECTOR, EXP_SCALE,
    log_v2, json_file_load, config_init, get_reserves
)

from get_configs_from_comet import (
    comet_configs_init,
    get_collateral_factor
)

COMPOUND_V3_USERS_FILTER_TEMP = """
{
    "address": "",
    "topics": [
        [
            "0x1a2a22cb034d26d1854bdc6666a5b91fe25efbbb5dcad3b0355478d6f5c362a1",
            "0x13ed6866d4e1ee6da46f845c46d7e54120883d75c5ea9a2dacc1c4ca8984ab80",
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            "0x875352fb3fadeb8c0be7cbbe8ff761b308fa7033470cd0287f02f3436fd76cb9",
            "0x4dec04e750ca11537cabcd8a9eab06494de08da3735bc8871cd41250e190bc04",
            "0xa91e67c5ea634cd43a12c5a482724b03de01e85ca68702a53d0c2f45cb7c1dc5",
            "0x3bad0c59cf2f06e7314077049f48a93578cd16f5ef92329f1dab1420a99c177e"
        ],
        []
    ]
}
"""

"""
RepayBorrow (address payer, address borrower, uint256 repayAmount, uint256 accountBorrows, uint256 totalBorrows)
[topic0] 0x1a2a22cb034d26d1854bdc6666a5b91fe25efbbb5dcad3b0355478d6f5c362a1

Borrow (address borrower, uint256 borrowAmount, uint256 accountBorrows, uint256 totalBorrows)
[topic0] 0x13ed6866d4e1ee6da46f845c46d7e54120883d75c5ea9a2dacc1c4ca8984ab80

Transfer (index_topic_1 address from, index_topic_2 address to, uint256 amount)
[topic0] 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef

Mint (address minter, uint256 mintAmount, uint256 mintTokens)
[topic0] 0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f
Notice: together with Transfer

Redeem (address redeemer, uint256 redeemAmount, uint256 redeemTokens)
[topic0] 0xe5b754fb1abb7f01b499791d0b820ae3b6af3424ac1c59768edb53f4ec31a929
Notice: together with Transfer

ReservesAdded (address benefactor, uint256 addAmount, uint256 newTotalReserves)
[topics0] 0xa91e67c5ea634cd43a12c5a482724b03de01e85ca68702a53d0c2f45cb7c1dc5
Notice: totalReserves

ReservesReduced (address admin, uint256 reduceAmount, uint256 newTotalReserves)
[topics0] 
Notice: totalReserves

AccrueInterest (uint256 interestAccumulated, uint256 borrowIndex, uint256 totalBorrows)
[topic0] 0x875352fb3fadeb8c0be7cbbe8ff761b308fa7033470cd0287f02f3436fd76cb9
Notice: borrowIndex, totalReserves

AccrueInterest (uint256 cashPrior, uint256 interestAccumulated, uint256 borrowIndex, uint256 totalBorrows)
[topic0] 0x4dec04e750ca11537cabcd8a9eab06494de08da3735bc8871cd41250e190bc04
"""
EVENT_ABI = {
    "0x1a2a22cb034d26d1854bdc6666a5b91fe25efbbb5dcad3b0355478d6f5c362a1": {
        "name": "RepayBorrow",
        "index_topic": [],
        "data": ["address", "address", "uint256", "uint256", "uint256"]
    },
    "0x13ed6866d4e1ee6da46f845c46d7e54120883d75c5ea9a2dacc1c4ca8984ab80": {
        "name": "Borrow",
        "index_topic": [],
        "data": ["address", "uint256", "uint256", "uint256"]
    },
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef": {
        "name": "Transfer",
        "index_topic": ["address", "address"],
        "data": ["uint256"]
    },
    "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f": {
        "name": "Mint",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    },
    "0xe5b754fb1abb7f01b499791d0b820ae3b6af3424ac1c59768edb53f4ec31a929": {
        "name": "Redeem",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    },
    "0xa91e67c5ea634cd43a12c5a482724b03de01e85ca68702a53d0c2f45cb7c1dc5": {
        "name": "ReservesAdded",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    },
    "0x3bad0c59cf2f06e7314077049f48a93578cd16f5ef92329f1dab1420a99c177e": {
        "name": "ReservesReduced",
        "index_topic": [],
        "data": ["address", "uint256", "uint256"]
    },
    "0x875352fb3fadeb8c0be7cbbe8ff761b308fa7033470cd0287f02f3436fd76cb9": {
        "name": "AccrueInterest",
        "index_topic": [],
        "data": ["uint256", "uint256", "uint256"]
    },
    "0x4dec04e750ca11537cabcd8a9eab06494de08da3735bc8871cd41250e190bc04": {
        "name": "AccrueInterest_delegate",
        "index_topic": [],
        "data": ["uint256", "uint256", "uint256", "uint256"]
    }
}

'''
{
    user {
        reserve: [ is_collateral, collateral_amount, borrow_amount ]
        ...
    }
}
'''
TEMPLATE = "./users/users_template.json"
ALIAS = COMPOUND[NETWORK][SELECTOR]
if ALIAS['users_file_status'] == 1:
    FILE_PATH_START = ALIAS['users_file']
else:
    FILE_PATH_START = TEMPLATE
FILE_PATH_RECORD = ALIAS['users_file']

users_raw = json_file_load(FILE_PATH_START)
if FILE_PATH_START == TEMPLATE:
    users_raw['last_update'] = ALIAS['init_block_number']

users_health_factor = {}

# todo: initialization
borrow_index_dict = {}
total_reserve_dict = {}
total_borrow_dict = {}
total_supply_dict = {}


def get_borrow_index(reserve):
    return borrow_index_dict[reserve]


def get_total_reserve(reserve):
    return total_reserve_dict[reserve]


def get_total_borrow(reserve):
    return total_borrow_dict[reserve]


def get_total_supply(reserve):
    return total_supply_dict[reserve]


def get_exchange_rate(reserve):
    reserve = Web3.toChecksumAddress(reserve)

    total_supply = get_total_supply(reserve)
    total_borrow = get_total_borrow(reserve)
    total_reserve = get_total_reserve(reserve)
    total_cash = 0  # todo

    if total_supply == 0:
        return 0  # todo: initialExchangeRateMantissa
    else:
        temp = total_cash + total_borrow - total_reserve
        return temp * EXP_SCALE // total_supply


def users_filter_converter_light():
    filt = json.loads(COMPOUND_V3_USERS_FILTER_TEMP)
    array = []

    for key, value in filt.items():
        if key == "topics":
            for topic in value[0]:
                array.append([topic])

    return array


def check_user_and_reserve(user, reserve):
    if users_raw['users'].get(user, None) is None:
        users_raw['users'][user] = {}

    if users_raw['users'][user].get(reserve, None) is None:
        users_raw['users'][user][reserve] = [0, 0, 0]


def log_parser_wrap(logs):
    num_list = []
    for log in logs:
        log_parser(log)
        if len(num_list) == 0:
            num_list.append(log['blockNumber'])

        if log['blockNumber'] != num_list[-1]:
            num_list.append(log['blockNumber'])

    log_v2.info("users updated, block number: {}".format(num_list))


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

    reserve = log['address']
    reserve = Web3.toChecksumAddress(reserve)

    # include: Transfer, Mint, Redeem
    if obj['name'] == 'Transfer':
        from_user = log['topics'][1][12:].hex()
        to_user = log['topics'][2][12:].hex()
        amount = args_data[0]

        check_user_and_reserve(from_user, reserve)
        check_user_and_reserve(to_user, reserve)

        if total_supply_dict.get(reserve, None) is None:
            total_supply_dict[reserve] = 0

        if from_user == reserve.lower():
            total_supply_dict[reserve] += amount

        if to_user == reserve.lower():
            total_supply_dict[reserve] -= amount

        users_raw['users'][from_user][reserve][0] -= amount
        users_raw['users'][to_user][reserve][0] += amount
        log_v2.debug("{} transfer {} amount of reserve {}, current COLLATERAL balance {}".
                     format(from_user, amount, reserve, users_raw['users'][from_user][reserve][0]))
        log_v2.debug("{} receive {} amount of reserve {}, current COLLATERAL balance {}".
                     format(to_user, amount, reserve, users_raw['users'][from_user][reserve][0]))
        log_v2.debug("reserve {} total supply {}".format(reserve, total_supply_dict[reserve]))

    if obj['name'] == 'RepayBorrow':
        borrower = '0x' + trx_abi.encode_single("address", args_data[1]).hex()[24:]
        amount = args_data[3]
        repay_amount = args_data[2]
        total_borrow = args_data[4]

        check_user_and_reserve(borrower, reserve)
        users_raw['users'][borrower][reserve][1] = amount
        users_raw['users'][borrower][reserve][2] = borrow_index_dict[reserve]
        total_borrow_dict[reserve] = total_borrow
        log_v2.debug("borrower {} {} {} amount of reserve {}, current DEBT balance {}, borrow index {}, total borrow {}".
                     format(borrower, obj['name'], repay_amount, reserve, amount, borrow_index_dict[reserve], total_borrow_dict[reserve]))

    if obj['name'] == 'Borrow':
        borrower = '0x' + trx_abi.encode_single("address", args_data[0]).hex()[24:]
        amount = args_data[2]
        borrow_amount = args_data[1]
        total_borrow = args_data[3]

        check_user_and_reserve(borrower, reserve)
        users_raw['users'][borrower][reserve][1] = amount
        users_raw['users'][borrower][reserve][2] = borrow_index_dict[reserve]
        total_borrow_dict[reserve] = total_borrow
        log_v2.debug("borrower {} {} {} amount of reserve {}, current DEBT balance {}, borrow index {}, total borrow {}".
                     format(borrower, obj['name'], borrow_amount, reserve, amount, borrow_index_dict[reserve], total_borrow_dict[reserve]))

    if obj['name'] == 'AccrueInterest' or obj['name'] == 'AccrueInterest_delegate':
        if obj['name'] == 'AccrueInterest_delegate':
            deviation = 1
        else:
            deviation = 0
        
        interest_accumulated = args_data[0+deviation]
        borrow_index = args_data[1+deviation]
        total_borrow = args_data[2+deviation]

        borrow_index_dict[reserve] = borrow_index
        total_borrow_dict[reserve] = total_borrow

        reserve_factor = get_collateral_factor(reserve)
        total_reserve_dict[reserve] += reserve_factor * interest_accumulated // EXP_SCALE

        log_v2.debug("reserve {} update: borrow index {}, total reserves {}, total borrow {}".
                     format(reserve, borrow_index_dict[reserve], total_reserve_dict[reserve], total_borrow_dict[reserve]))

    if obj['name'] == 'ReservesAdded' or obj['name'] == 'ReservesReduced':
        new = args_data[2]
        total_reserve_dict[reserve] = new
        log_v2.debug("reserve {} update: total reserves {}".format(reserve, total_reserve_dict[reserve]))


# currently unused
def update_timestamp(time_stamp):
    users_raw['last_update'] = time_stamp


def init():
    w3 = Web3(provider)
    count = 0
    block_number = ALIAS['init_block_number'] + 20000  # test only
    # block_number = w3.eth.get_block_number()
    print("users sync to latest block number: {}".format(block_number))
    if block_number <= users_raw['last_update']:
        return

    filt = json.loads(COMPOUND_V3_USERS_FILTER_TEMP)
    filt['address'] = get_reserves()
    print(filt)

    while users_raw['last_update'] <= block_number:
        from_block = users_raw['last_update']
        to_block = from_block + 999
        if to_block > block_number:
            to_block = block_number

        filt['fromBlock'] = hex(from_block)
        filt['toBlock'] = hex(to_block)

        try:
            logs = w3.eth.get_logs(filt)
        except Exception as e:
            log_v2.error(e)
            time.sleep(2)
            continue
        
        if len(logs) != 0:
            log_parser_wrap(logs)
        
        users_raw['last_update'] = to_block + 1

        count += 1
        if count > 100:
            json_object = json.dumps(users_raw, indent=4)
            with open(FILE_PATH_RECORD, "w") as outfile:
                outfile.write(json_object)
            count = 0

        time.sleep(1)


def trim():
    key1 = []
    key2 = []

    for user, reserves in users_raw['users'].items():
        key1.append(user)
        temp = []
        for reserve, data in reserves.items():
            if data[0] == 0 and data[1] == 0:
                temp.append(reserve)
        key2.append(temp)

    for i in range(len(key1)):
        for reserve in key2[i]:
            users_raw['users'][key1[i]].pop(reserve)

    for user in key1:
        if not users_raw['users'][user]:
            users_raw['users'].pop(user)
            continue


def get_users_start():
    init()
    trim()

    json_object = json.dumps(users_raw, indent=4)

    # Writing to sample.json
    with open(FILE_PATH_RECORD, "w") as outfile:
        outfile.write(json_object)


def users_filtering(tokens_addr):
    users = users_raw['users']
    res = []
    for usr, reserves in users.items():
        a = []
        for reserve, data in reserves.items():
            for token_addr in tokens_addr:
                if reserve.lower() == token_addr.lower():
                    a.append(token_addr)

        if len(a) > 0:
            health_factor = get_health_factor(usr)
            res.append((usr, a, reserves, health_factor))

    return res


def get_health_factor(user):
    return users_health_factor.get(user, None)


def set_health_factor(user, hf, last_update):
    users_health_factor[user] = [hf, last_update]


if __name__ == '__main__':
    config_init()
    comet_configs_init()
    get_users_start()
