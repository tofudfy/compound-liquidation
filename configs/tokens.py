import time
import os
import json

from web3 import Web3
from typing import Dict, List, Tuple
from web3.types import LogReceipt
# from tronpy.abi import trx_abi

from configs.config import P_ALIAS, EXCHANGE_RATE_INIT, EXP_SCALE
from configs.utils import json_file_load

CONFIGS_PATH_RECORD = P_ALIAS['ctoken_congis_file']
COMET_CONFIGS_PATH_RECORD = P_ALIAS['comet_configs_file']


class AaveReserve(object):
    def __init__(self, is_collateral: bool, atoken_amount: int, stoken_amount: int, vtoken_amount: int, interest_index: int, interest_update: int):
        # self.addr = token_addr
        self.is_collateral = is_collateral
        self.atoken_amount = atoken_amount
        self.stoken_amount = stoken_amount
        self.vtoken_amount = vtoken_amount
        self.interest_index = interest_index
        self.interest_update = interest_update


def new_reserve(col_amount=0, is_col_liq=0, debt_amount=0, debt_interest=0):
    return CompReserve(col_amount, is_col_liq, debt_amount, debt_interest)


class CompReserve(object):
    """
    reserve: [ is_collateral, collateral_amount, borrow_amount ]
    """
    def __init__(self, col_amount: int, is_col_liq: int, debt_amount: int, debt_interest: int):
        self.col_amount = col_amount
        self.is_col_liq = is_col_liq
        self.debt_amount = debt_amount
        self.debt_interest = debt_interest

    # currently unused
    def __str__(self) -> str:
        return f'CompReserve(col_amount={self.col_amount}, is_col_liq={self.is_col_liq}, debt_amount={self.debt_amount}, debt_interest={self.debt_interest})'

    def to_list(self) -> List:
        return [self.col_amount, self.is_col_liq, self.debt_amount, self.debt_interest]


def reserves_load(reserves) -> Dict[str, CompReserve]:
    results = {}
    for reserve, data in reserves.items():
        results[reserve] = new_reserve(col_amount=data[0], is_col_liq=data[1], debt_amount=data[2], debt_interest=data[3])

    return results


class CtokenRiskParams(object):
    def __init__(self, borrow_index: int, reserve_factor: int, exchange_rate: int):
        self.borrow_index = borrow_index
        self.reserve_factor = reserve_factor
        self.exchange_rate = exchange_rate
        # self.last_udpate = last_update

    def to_dict(self) -> Dict:
        return {
            "borrowIndex": self.borrow_index
        }


def new_ctoken_risks(borrow_index=0, reserve_factor=0, exchange_rate=0) -> CtokenRiskParams:
    return CtokenRiskParams(borrow_index, reserve_factor, exchange_rate)


class CtokenBalances(object):
    def __init__(self, total_reserve, total_borrow, total_supply):
        self.total_reserve = total_reserve
        self.total_borrow = total_borrow
        self.total_supply = total_supply
        # self.last_update = last_update

    def to_dict(self):
        return {
            "totalReserve": self.total_reserve,
            "totalBorrow": self.total_borrow,
            "totalSupply": self.total_supply
        }

    # API: getCash
    def cal_exchange_rate(self, reserve):
        # reserve = Web3.toChecksumAddress(reserve)

        total_supply = self.total_reserve
        total_borrow = self.total_borrow
        total_reserve = self.total_supply
        total_cash = 0  # todo getCash()

        if total_supply == 0:
            return EXCHANGE_RATE_INIT  # initialExchangeRateMantissa
        else:
            temp = total_cash + total_borrow - total_reserve
            return temp * EXP_SCALE // total_supply


def new_ctoken_balances(total_reserve=0, total_borrow=0, total_supply=0) -> CtokenBalances:
    return CtokenBalances(total_reserve, total_borrow, total_supply)


def reload_ctokens_balances(path: str) -> Tuple[Dict[str, CtokenBalances], int]:
    ctokens_balances = json_file_load(path + os.sep + CONFIGS_PATH_RECORD)
    last_update = ctokens_balances['lastUpdate']

    balances_dict = {}
    for ctoken, balances in ctokens_balances['reserves'].items():
        total_reserve = balances.get('totalReserves', 0)
        total_borrow = balances.get('totalBorrows', 0)
        total_supply = balances.get('totalSupply', 0)
        balances_dict[ctoken] = CtokenBalances(total_reserve, total_borrow, total_supply)

    return balances_dict, last_update


def reload_ctokens_risks(path: str) -> Tuple[Dict[str, CtokenRiskParams], int]:
    ctokens_risks = json_file_load(path + os.sep + COMET_CONFIGS_PATH_RECORD)
    last_update = ctokens_risks['lastUpdate']

    risks_dict = {}
    for ctoken, risks in ctokens_risks['reserves'].items():
        borrow_index = risks.get('borrowIndex', 0)
        # collateral_factor = risks.get('collateralFactor', 0)
        reserve_factor = risks.get('reserveFactor', 0)
        exchange_rate = risks.get('exchangeRate', 0)
        risks_dict[ctoken] = CtokenRiskParams(borrow_index, reserve_factor, exchange_rate)
    return risks_dict, last_update


class CtokenConfigs(object):
    def __init__(self, ctoken: str, underlying: str, symbol: str, symbol_hash: bytes, base_units: int, price_source: int, price_fixed: int, swap_router: str, reporter: str, reporter_multiplier: int, is_uniswap_reversed: bool, underlying_decimals: int):
        self.ctoken = ctoken
        self.underlying = underlying
        self.symbol_hash = symbol_hash
        self.symbol = symbol
        self.decimals = len(str(base_units)) - 1
        self.price_source = price_source
        self.price_fixed = price_fixed
        self.swap_router = swap_router
        self.reporter = reporter
        self.reporter_multiplier = reporter_multiplier
        self.is_uniswap_reversed = is_uniswap_reversed

        # customized configs
        self.underlying_decimals = underlying_decimals


def new_ctoken_configs(ctoken, reporter, underlying, underlying_decimals, symbol="", base_units=100000000, price_source=0, price_fixed=0, swap_router="0x", reporter_multiplier=0, is_uniswap_reversed=False) -> CtokenConfigs:
    return CtokenConfigs(
        ctoken=ctoken, 
        underlying=underlying,
        underlying_decimals=underlying_decimals,
        symbol=symbol,
        symbol_hash=bytes(symbol, encoding='utf-8'),
        base_units=base_units, 
        price_source=price_source, 
        price_fixed=price_fixed, 
        swap_router=swap_router, 
        reporter=reporter, 
        reporter_multiplier=reporter_multiplier, 
        is_uniswap_reversed=is_uniswap_reversed)


'''
def gen_ctokens_configs(w3_comp: Web3Liquidation, ctoken_addr: str, reporter_type: str, identifier="latest") -> CtokenConfigs:
    ctoken_sc = w3_comp.gen_tokens(ctoken_addr)
    try:
        ctoken_underlying = ctoken_sc.functions.underlying().call()
        # the API of symbol are same for both ctoken and its underlying token
        token_sc = w3_comp.gen_tokens(ctoken_underlying)
        symbol = token_sc.functions.symbol().call()
    except:
        symbol = "vBNB"  # todo: extend
        # print(ctoken_addr)

    price_sc = w3_comp.gen_price_oracle()
    reporter = price_sc.functions.getFeed(symbol).call(block_identifier=identifier) 
    return new_ctoken_configs(ctoken_addr, reporter, reporter_type)


def query_ctokens_configs(w3_comp: Web3Liquidation, ctoken_addr, identifier="latest") -> CtokenConfigs:
    """
    struct TokenConfig {
        0 address cToken;
        1 address underlying;
        2 bytes32 symbolHash;
        3 uint256 baseUnit;
        4 PriceSource priceSource;
        5 uint256 fixedPrice;
        6 address uniswapMarket;
        7 address reporter;
        8 uint256 reporterMultiplier;
        9 bool isUniswapReversed;
    }
    :param reserves:
    :return:
    """
    price_oracle = w3_comp.gen_price_oracle()
    tuples: List = price_oracle.functions.getTokenConfigByCToken(ctoken_addr).call(block_identifier=identifier)
    return CtokenConfigs(tuples[0], tuples[1], tuples[2], tuples[3], tuples[4], tuples[5], tuples[6], tuples[7], tuples[8], tuples[9], "validator")
'''


'''
def sync_collateral_factor():
    filt = {
        "address": P_ALIAS['comet'],
        "topics": [
            ["0x70483e6592cd5182d45ac970e05bc62cdcc90e9d8ef2c2dbe686cf383bcd7fc5"]
        ]
    }

    block_number = w3.eth.get_block_number()
    last_update = get_collateral_lastupdate()
    query_events_loop(filt, comet_log_parser, last_update, block_number, empty_hook)
    collateral_factor_dict = get_collateral_factor_dict()
    collateral_factor_dict['last_update'] = block_number + 1
    json_write_to_file(collateral_factor_dict, COMET_CONFIGS_PATH_RECORD)
'''


'''
# currently unused
def init_ctokens_infos(w3_comp: Web3Liquidation, reserves) -> Dict:
    ctokens_infos = {}
    for ctoken_addr in reserves:
        ctoken_contract = w3_comp.gen_tokens(ctoken_addr)

        # constant configs
        ctoken_configs = query_ctokens_configs(w3_comp, ctoken_addr)
        # symbol = ctoken_contract.functions.symbol().call()

        # update by pending tx
        # ctoken_price = init_ctoken_price(w3_comp, ctoken_addr)

        # update by reserve related events
        borrow_index = ctoken_contract.functions.borrowIndex().call()
        reserve_factor = ctoken_contract.functions.reserveFactorMantissa().call()
        exchange_rate = ctoken_contract.functions.exchangeRateStored().call()
        ctoken_risks = CtokenRiskParams(borrow_index, reserve_factor, exchange_rate)

        # update by user related events
        total_reserve = ctoken_contract.functions.totalReserves().call()
        total_borrow = ctoken_contract.functions.totalBorrows().call()
        total_supply = ctoken_contract.functions.totalSupply().call()
        ctoken_balances = CtokenBalances(total_reserve, total_borrow, total_supply)

        ctokens_infos[ctoken_addr] = CtokenInfos(ctoken_risks, ctoken_balances)

    return ctokens_infos
'''


class CtokenInfos(object):
    def __init__(self, risks: CtokenRiskParams, balances: CtokenBalances):
        self.risks = risks
        self.balances = balances
        self.configs: CtokenConfigs = None
        self.price = None


# used for test
def new_ctokens_infos(reserves: List) -> Dict[str, CtokenInfos]:
    ctokens_infos = {}
    for reserve in reserves:
        ctokens_infos[reserve] = CtokenInfos(new_ctoken_risks(), new_ctoken_balances())
    return ctokens_infos


def tokens_load(reserves: List, path: str) -> Tuple[Dict[str, CtokenInfos], int]:
    if P_ALIAS['users_file_status'] == 0:
        ctokens_infos = {}
        for reserve in reserves:
            ctokens_infos[reserve] = CtokenInfos(new_ctoken_risks(), new_ctoken_balances())
        return ctokens_infos, P_ALIAS['init_block_number']

    balances, last_update_b = reload_ctokens_balances(path)
    risks, last_update_r = reload_ctokens_risks(path)

    if last_update_b != last_update_r:
        raise Exception('')

    ctokens_infos = {}
    for reserve in reserves:
        ctoken_risks = risks.get(reserve, new_ctoken_risks())
        ctoken_balances = balances.get(reserve, new_ctoken_balances())
        ctokens_infos[reserve] = CtokenInfos(ctoken_risks, ctoken_balances)

    return ctokens_infos, last_update_b
