import json
import os

from collections import deque
from typing import Dict, List
from tronpy.abi import trx_abi
from eth_abi import decode
from web3 import Web3
from web3.types import LogReceipt
from eth_typing import Address, ChecksumAddress

from configs.config import P_ALIAS, EXP_SCALE
from configs.tokens import CompReserve, tokens_load, reserves_load, new_reserve, backtesting_reserves, CtokenInfos, CONFIGS_PATH_RECORD, COMET_CONFIGS_PATH_RECORD
from configs.utils import json_file_load, json_write_to_file, query_events_loop, data_cache_hook
from configs.web3_liq import Web3Liquidation

from configs.config import RESERVES

TEMPLATE = "./users/users_template.json"
FILE_PATH_RECORD = P_ALIAS['users_file']

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

NewReserveFactor(uint256 oldReserveFactorMantissa, uint256 newReserveFactorMantissa)
[topics0] 
Notice: reeserveFactor
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
    },
    "": {
        "name": "NewReserveFactor",
        "index_topic": [],
        "data": ["uint256", "uint256"]
    },
}

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
            "0x3bad0c59cf2f06e7314077049f48a93578cd16f5ef92329f1dab1420a99c177e",
            "0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5"
        ]
    ]
}
"""


def gen_states_filter(reserves: List):
    filt = json.loads(COMPOUND_V3_USERS_FILTER_TEMP)
    filt['address'] = reserves
    return filt


def new_health_factor(health_factor=0, debt_volume=0, last_update=0):
    return HealthFactor(health_factor, debt_volume, last_update)


class HealthFactor(object):
    def __init__(self, health_factor: int, debt_volume: int, last_update: int):
        self.value = health_factor
        self.debt_volume = debt_volume
        self.last_update = last_update

    def to_list(self) -> List:
        return [self.value, self.debt_volume, self.last_update]
    
    def get_col_volume(self):
        return self.health_factor * self.debt_volume


class UserStates(object):
    def __init__(self, reserves: Dict, health_factor: HealthFactor):
        self.reserves = reserves_load(reserves)
        self.health_factor = health_factor

    def get_health_factor(self):
        return self.health_factor

    # def update_health_factor(self, hf, last_update):
    #     self.health_factor = HealthFactor(hf, last_update)


class States(object):
    def __init__(self, users_states: Dict[str, UserStates], ctokens_infos: Dict[str, CtokenInfos], last_update: int, block_hash: str):
        self.users_states = users_states
        self.ctokens = ctokens_infos
        self.last_update = last_update
        self.block_hash = block_hash

    def check_user_and_reserve(self, user, reserve):
        if self.users_states.get(user, None) is None:
            self.users_states[user] = UserStates({}, new_health_factor())

        if self.users_states[user].reserves.get(reserve, None) is None:
            self.users_states[user].reserves[reserve] = new_reserve()

    def users_filtering(self, tokens_addr):
        users = []
        for usr, states in self.users_states.items():
            for token_addr in tokens_addr:
                if states.reserves.get(token_addr, None) is not None:
                    users.append(usr)
                    break
        return users

    def to_json(self):
        users_new_dict = {}
        for usr, usr_states in self.users_states.items():
            users_new_dict[usr] = {}
            reserves_new_dict = {}
            for reserve, reserve_states in usr_states.reserves.items():
                reserves_new_dict[reserve] = reserve_states.to_list()
            users_new_dict[usr]['reserves'] = reserves_new_dict

            new_hf_json = usr_states.health_factor.to_list()
            users_new_dict[usr]['healthFactor'] = new_hf_json

        ctokens_risks_new_dict = {}
        ctokens_balances_new_dict = {}
        for ctoken, infos in self.ctokens.items():
            ctokens_risks_new_dict[ctoken] = infos.risks.to_dict()
            ctokens_balances_new_dict[ctoken] = infos.balances.to_dict()

        return users_new_dict, ctokens_risks_new_dict, ctokens_balances_new_dict

    def cache(self):
        self.trim()
        # self.trim_ctokens(reserves)

        users_new_dict, ctokens_risks_dict, ctokens_balances_dict = self.to_json()
        # users_states_json = json.dumps(self.users_states, default=lambda obj: obj.__dict__, indent=4)

        current_file = os.path.abspath(__file__)
        current_path = os.path.dirname(current_file)

        json_write_to_file({
            "users": users_new_dict,
            "lastUpdate": self.last_update,
            "blockHash": self.block_hash
        }, current_path, FILE_PATH_RECORD)

        json_write_to_file({
            "reserves": ctokens_risks_dict,
            "lastUpdate": self.last_update
        }, current_path, COMET_CONFIGS_PATH_RECORD)

        json_write_to_file({
            "reserves": ctokens_balances_dict,
            "lastUpdate": self.last_update
        }, current_path, CONFIGS_PATH_RECORD)

    def trim(self):
        key1 = []
        key2 = []

        # mark empty reserves
        for user, states in self.users_states.items():
            key1.append(user)
            reserves_empty = []
            reserves = states.reserves
            for reserve, data in reserves.items():
                if data.col_amount == 0 and data.debt_amount == 0:
                    reserves_empty.append(reserve)
            key2.append(reserves_empty)

        # delete empty reserves
        for i in range(len(key1)):
            user = key1[i]
            for reserve in key2[i]:
                self.users_states[user].reserves.pop(reserve)

        # delete empty users
        for user in key1:
            if not self.users_states[user]:
                self.users_states.pop(user)

    def trim_ctokens(self, all_ctokens):
        for fake_user in all_ctokens:
            if self.users_states.get(fake_user, None) is not None:
                self.users_states.pop(fake_user)

    def update(self, log: LogReceipt) -> List:
        users_changed = []
        if log.get('removed', False):
            # log_v2.info("log is removed {}".format(log))
            return

        topic = log['topics'][0].hex()
        obj = EVENT_ABI.get(topic, None)
        if obj is None:
            # log_v2.error("unexpected topics in get users: {}".format(log))
            return

        try:
            data = bytes.fromhex(log['data'][2:])
            args_data = decode(obj['data'], data)  # todo: optimization
        except Exception as e:
            # log_v2.error(e)
            return

        reserve = log['address']
        reserve = Web3.toChecksumAddress(reserve)

        # include: Transfer, Mint, Redeem
        if obj['name'] == 'Transfer':
            from_user = log['topics'][1][12:].hex()
            to_user = log['topics'][2][12:].hex()
            amount = args_data[0]

            self.check_user_and_reserve(from_user, reserve)
            self.check_user_and_reserve(to_user, reserve)

            if from_user == reserve.lower():
                self.ctokens[reserve].balances.total_supply += amount

            if to_user == reserve.lower():
                self.ctokens[reserve].balances.total_supply -= amount

            self.users_states[from_user].reserves[reserve].col_amount -= amount
            self.users_states[to_user].reserves[reserve].col_amount += amount
            users_changed.append(from_user)
            users_changed.append(to_user)

            '''
            log_v2.debug("{} transfer {} amount of reserve {}, current COLLATERAL balance {}".
                        format(from_user, amount, reserve, users_raw['users'][from_user][reserve][0]))
            log_v2.debug("{} receive {} amount of reserve {}, current COLLATERAL balance {}".
                        format(to_user, amount, reserve, users_raw['users'][from_user][reserve][0]))
            log_v2.debug("reserve {} total supply {}".format(reserve, total_supply_dict[reserve]))
            '''

        if obj['name'] == 'RepayBorrow':
            borrower = args_data[1]  # '0x' + trx_abi.encode_single("address", args_data[1]).hex()[24:]
            amount = args_data[3]
            repay_amount = args_data[2]
            total_borrow = args_data[4]

            self.check_user_and_reserve(borrower, reserve)
            users_changed.append(borrower)
            self.users_states[borrower].reserves[reserve].debt_amount = amount
            self.users_states[borrower].reserves[reserve].debt_interest = self.ctokens[reserve].risks.borrow_index
            self.ctokens[reserve].balances.total_borrow = total_borrow
            '''
            log_v2.debug("borrower {} {} {} amount of reserve {}, current DEBT balance {}, borrow index {}, total borrow {}".
                        format(borrower, obj['name'], repay_amount, reserve, amount, borrow_index_dict[reserve], total_borrow_dict[reserve]))      
            '''

        if obj['name'] == 'Borrow':
            borrower = args_data[0]  # '0x' + trx_abi.encode_single("address", args_data[0]).hex()[24:]
            amount = args_data[2]
            borrow_amount = args_data[1]
            total_borrow = args_data[3]

            self.check_user_and_reserve(borrower, reserve)
            users_changed.append(borrower)
            self.users_states[borrower].reserves[reserve].debt_amount = amount
            self.users_states[borrower].reserves[reserve].debt_interest = self.ctokens[reserve].risks.borrow_index
            self.ctokens[reserve].balances.total_borrow = total_borrow
            '''
            log_v2.debug("borrower {} {} {} amount of reserve {}, current DEBT balance {}, borrow index {}, total borrow {}".
                        format(borrower, obj['name'], borrow_amount, reserve, amount, borrow_index_dict[reserve], total_borrow_dict[reserve]))       
            '''

        if obj['name'] == 'AccrueInterest' or obj['name'] == 'AccrueInterest_delegate':
            if obj['name'] == 'AccrueInterest_delegate':
                deviation = 1
            else:
                deviation = 0

            interest_accumulated = args_data[0+deviation]
            borrow_index = args_data[1+deviation]
            total_borrow = args_data[2+deviation]

            self.ctokens[reserve].risks.borrow_index = borrow_index
            self.ctokens[reserve].balances.total_borrow = total_borrow
            self.ctokens[reserve].balances.total_reserve += self.ctokens[reserve].risks.reserve_factor * interest_accumulated // EXP_SCALE
            '''
            log_v2.debug("reserve {} update: borrow index {}, total reserves {}, total borrow {}".
                         format(reserve, borrow_index_dict[reserve], total_reserve_dict[reserve], total_borrow_dict[reserve]))      
            '''

        if obj['name'] == 'ReservesAdded' or obj['name'] == 'ReservesReduced':
            new = args_data[2]
            self.ctokens[reserve].balances.total_reserve = new
            '''
            log_v2.debug("reserve {} update: total reserves {}".format(reserve, total_reserve_dict[reserve]))
            '''

        if obj['name'] == 'NewReserveFactor':
            new = args_data[1]
            self.ctokens[reserve].risks.reserve_factor = new
            '''
            log_v2.debug("reserve {} update: reserve factor {}".format(reserve, reserve_factor[reserve]))
            '''

        return users_changed


def filter_states(users_states: Dict[str, UserStates], profit_thres) -> Dict[str, UserStates]:
    users_states_trimed = {}
    for usr, data in users_states.items():
        if data.health_factor.debt_volume > profit_thres:
            users_states_trimed[usr] = data

    return users_states_trimed


class HighProfitSates(States):
    def __init__(self, full_states: States, profit_thres: float):
        super().__init__(
            filter_states(full_states.users_states, profit_thres),
            full_states.ctokens, full_states.last_update, full_states.block_hash
        )
        self.parent = full_states
        self.update_users = []
        self.debt_desired = profit_thres * 2 * EXP_SCALE

    def update(self, log: LogReceipt):
        new_updated_users: List = super().update(log)
        for usr in new_updated_users:
            self.update_debt(usr)
        
        self.update_users += new_updated_users

    def update_debt(self, usr: str):
        sum_borrow_plus_effects = 0
        reserves = self.users_states[usr].reserves
        ctk = self.ctokens

        for token_addr, reserve in reserves.items():
            # collateral_balance = reserve.col_amount
            debt_balance = reserve.debt_amount
            interest_index = reserve.debt_interest

            price = ctk[token_addr].price.price_current

            if debt_balance > 0:
                borrow_index = ctk[token_addr].risks.borrow_index
                debt_balance = debt_balance * borrow_index // interest_index
                sum_borrow_plus_effects += debt_balance * price // EXP_SCALE

        self.users_states[usr].health_factor.debt_volume = sum_borrow_plus_effects 

    def write_back_changed_states(self):
        for usr in self.update_users:
            self.parent.users_states[usr] = self.users_states[usr]

    def write_back_lowprof_states(self):
        for usr in self.update_users:
            state = self.eliminate_lowprof_states(usr)
            if state is not None:
                self.parent.users_states[usr] = state
            
    def eliminate_lowprof_states(self, usr: str) -> UserStates:
        if self.users_states[usr].health_factor.debt_volume < self.debt_desired:
            return self.users_states.pop(usr)
        else:
            return None


class FIFOStates(object):
    def __init__(self, max_length):
        self.max_length = max_length
        self.cache = deque(maxlen=max_length)

    def push(self, element: HighProfitSates):
        self.cache.append(element)
        if len(self.array) == self.max_length:
            old_elemnt: HighProfitSates = self.array.popleft()
            old_elemnt.write_back_changed_states()


def users_load(path: str) -> (Dict[str, UserStates], int, str):
    if P_ALIAS['users_file_status'] == 1:
        file_path_start = P_ALIAS['users_file']
        users_raw = json_file_load(path + os.sep + file_path_start)
        users_states = users_raw['users']
        last_update = users_raw['lastUpdate']
        block_hash = users_raw['blockHash']
    else:
        users_states = {}
        last_update = P_ALIAS['init_block_number']
        block_hash = ""

    results = {}
    for user, user_states in users_states.items():
        # todo: health_factor = user_states['healthFactor'] 
        results[user] = UserStates(user_states['reserves'], new_health_factor())

    return results, last_update, block_hash


def reload_states(reserves: List) -> States:
    current_file = os.path.abspath(__file__)
    path = os.path.dirname(current_file)

    users_states, last_update_u, block_hash = users_load(path)
    ctokens_infos, last_update_t = tokens_load(reserves, path)
    if last_update_u != last_update_t:
        raise Exception('')

    return States(users_states, ctokens_infos, last_update_u, block_hash)


def query_reserves(usr: str, w3_liq: Web3Liquidation, reserves: List, identifier="latest") -> Dict[str, List]:
    user_reserves = {}
    usr = Web3.toChecksumAddress(usr)
    for ctoken_addr in reserves:
        try:
            ctoken_contract = w3_liq.gen_tokens(ctoken_addr)
            res = ctoken_contract.functions.getAccountSnapshot(usr).call(block_identifier=identifier)
            print(f'user {usr[:6]} reserve "{ctoken_addr}" at {identifier} snapshot {res}')
            error = res[0]
            col_amount = res[1]
            debt_amount = res[2]

            if error == 0 and col_amount != 0 or debt_amount != 0:
                user_reserves[ctoken_addr] = [col_amount, debt_amount, 1]
        # some ctoken contract may not deployed with the identified specified
        except:
            continue

    return user_reserves


def backtesting_users(w3_liq: Web3Liquidation, user: str, reserves: List, block_num: int):
    users_states = {}
    reserves = query_reserves(user, w3_liq, reserves, block_num)
    print(reserves)
    users_states[user] = UserStates(reserves, new_health_factor())

    return users_states


def backtesting_states(w3_liq: Web3Liquidation, user: str, reserves: List, block_num: int) -> States:
    users_states = backtesting_users(w3_liq, user, reserves, block_num)
    reserves_trim = list(users_states[user].reserves.keys())
    ctokens_infos = backtesting_reserves(w3_liq, reserves_trim, block_num)
    return States(users_states, ctokens_infos, int(block_num), "")


def sync_states(states: States, w3_liq: Web3Liquidation, reserves: List):
    w3 = w3_liq.w3
    block_number = w3.eth.get_block_number()
    # block_number = states.last_update + 800000
    filt = gen_states_filter(reserves)

    query_events_loop(w3, states, filt, block_number)  # , data_cache_hook)


def reload_and_cache_test():
    # w3_liq = Web3Liquidation(provider_type='http2')
    # w3_liq = Web3Liquidation(provider_type='ws_ym')
    w3_liq = Web3Liquidation()
    # reserves = w3_liq.query_markets_list()
    reserves = RESERVES
    states = reload_states(reserves)
    sync_states(states, w3_liq, reserves)
    states.cache()


def users_states_test():
    w3_liq = Web3Liquidation(provider_type='http')
    reserves = RESERVES
    user = "0xe0b8fffb423bd44ca7c97c9f5aeefb4605614f73"
    last_update = 12195511
    query_reserves(user, w3_liq, reserves, last_update)


if __name__ == '__main__':
    reload_and_cache_test()
    # users_states_test()
