import logging
import json
import time
import asyncio

from typing import List
from web3 import Web3
from web3.types import LogReceipt, TxReceipt, TxData
from web3.middleware import geth_poa_middleware
from eth_abi import decode
from datetime import datetime, timezone, timedelta

from logger import Logger
from utils import subscribe_event_light

from configs.config import NETWORK, ADDRESS_ZERO, P_ALIAS, PROVIDER_TYPE, RESERVES, load_provider
from configs.utils import query_events_loop
from configs.web3_liq import Web3Liquidation


START_BLOCK = 39285900
END_BLOCK = 39339400
PREFIX = "./"  # "./logs/20221128/actual/"
LOG_FILE = PREFIX + "liquidation_calls_" + str(START_BLOCK) + "_" + str(END_BLOCK)

LIQUIDATION_FILTER_TEMP = """
{
    "address": "",
    "topics": [
        [
            "0x298637f684da70674f26509b10f07ec2fbc77a335ab1e7d6215a4b2484d8bb52"
        ]
    ]
}
"""

"""
LiquidateBorrow (
    address liquidator,
    address borrower,
    uint256 repayAmount,
    address cTokenCollateral,
    uint256 seizeTokens
)
"""
EVENT_ABI = {
    "0x298637f684da70674f26509b10f07ec2fbc77a335ab1e7d6215a4b2484d8bb52": {
        "name": "LiquidateBorrow",
        "index_topic": [],
        "data": ["address", "address", "uint256", "address", "uint256"]
    }
}

ETH_CALL_ASSET_PRICE = "0xb3596f07000000000000000000000000"  # + ADDRESS
ETH_CALL_ASSETS_PRICE = "0x9d23d9f200000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000002"


def gen_liquidation_filter(reserves: List):
    filt = json.loads(LIQUIDATION_FILTER_TEMP)
    filt['address'] = reserves
    return filt


'''
AAVE_ETH_USD = CONNECTION[NETWORK]['eth-usd']
def get_asset_price(token_addr, block_num):
    if price_dic.get(token_addr, None) is None:
        price_dic[token_addr] = {}

    if price_dic[token_addr].get(block_num, None) is None:
        if token_addr == "ETH":
            data = "0x50d25bcd"
            to = AAVE_ETH_USD
        else:
            data = ETH_CALL_ASSET_PRICE + token_addr[2:]
            # data = ETH_CALL_ASSETS_PRICE + collateral_asset[2:] + debt_asset[2:]
            to = AAVE_ORACLE_V2

        price = query_asset_price(to, data, block_num)
        price_dic[token_addr][block_num] = int(price.hex(), 16)

    return price_dic[token_addr][block_num]
'''


class Web3LiqListening(object):
    def __init__(self, provider_type=PROVIDER_TYPE) -> None:
        self.w3 = Web3(load_provider(provider_type))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    def eth_call(self, params, block_number):
        return self.w3.eth.call(params, block_number)

    def query_asset_price(self, to, data, block_number):
        params = {}
        params['to'] = Web3.toChecksumAddress(to)
        params['data'] = data

        try:
            res = self.eth_call(params, block_number)
        except Exception:
            res = '0x0'

        return res
    
    def get_asset_price(net, block_num):
        # todo: get convert price from chainlink oracle at specific block number
        pass

    def get_block_time(self, block_num):
        block = self.w3.eth.get_block(block_num)
        block_time = block['timestamp']
        return block_time

    def query_base_fee(self, block_num):
        block = self.w3.eth.get_block(block_num)
        return block['baseFeePerGas']

    def query_recpt_infos(self, tx_hash):
        try:
            recpt: TxReceipt = self.w3.eth.get_transaction_receipt(tx_hash)
            gas_used = recpt['gasUsed']
            gas_price = recpt['effectiveGasPrice']
        except Exception:
            gas_used = 0
            gas_price = 0

        return gas_used, gas_price

    def query_tx_origin(self, tx_hash):
        try:
            tx: TxData = self.w3.eth.get_transaction(tx_hash) 
            tx_origin = tx['from']
        except:
            tx_origin = ADDRESS_ZERO
        return tx_origin

    def query_trace_call(self, tx_hash):
        tracer = {'tracer': "callTracer"}
        params = [tx_hash, tracer]

        try:
            res = self.w3.provider.make_request("debug_traceTransaction", params)
        except Exception:
            return None

        return res


def trace_call_parsing(res):
    if res is None:
        return [], 0

    value_list = []
    mev_dict = {}
    sum = 0

    # MEV builder through inner Tx
    calls = res["result"]["calls"]
    for call in calls:
        if call["type"] == "CALL":
            value = int(call["value"], 16)/10**18
            if value != 0:
                sum += value
                value_list.append(value)
                mev_dict['inner_tx'] = sum

    # MEV builder through transfer directly
    value = int(res["result"]["value"], 16)/10**18
    if value != 0:
        sum += value
        mev_dict['transfer'] = value

    logger.debug("inner tx transfers: {}".format(value_list))
    return mev_dict, sum


'''
def temp():
    collateral_price = get_asset_price(collateral_asset, block_num)
    debt_price = get_asset_price(debt_asset, block_num)

    collateral_decimals = get_reserves_decimals(collateral_asset)
    debt_decimals = get_reserves_decimals(debt_asset)

    collateral_value = (collateral_price / 10**18) * (liquidated_collateral_amount / 10**collateral_decimals)
    debt_value = (debt_price / 10**18) * (debt_to_cover / 10**debt_decimals)
'''


class LiquidationCall(object):
    def __init__(self, logger: Logger):
        self.w3_liqcall: Web3LiqListening = None
        self.logger = logger
        # self.last_update = last_update
        self.get_block_time = None
        self.get_reserves_value = None
    
    def update(self, log: LogReceipt):
        if log.get('removed', False):
            return

        topic = log['topics'][0].hex()
        obj = EVENT_ABI.get(topic, None)
        if obj is None:
            return

        try:
            data = bytes.fromhex(log['data'][2:])
            args_data = decode(obj["data"], data)
        except Exception as e:
            raise Exception(f'liquidation parsing failed: {{"error": {e}, "log":{log}}}')

        if obj['name'] == "LiquidateBorrow":
            """
            address liquidator,
            address borrower,
            uint256 repayAmount,
            address cTokenCollateral,
            uint256 seizeTokens
            """
            liquidator = args_data[0]
            user = args_data[1]
            collateral_asset = args_data[3]
            debt_asset = log['address']
            debt_to_cover = args_data[2]
            liquidated_collateral_amount = args_data[4]
            params = [user, debt_to_cover, collateral_asset]

            # todo
            collateral_value = self.get_reserves_value(collateral_asset, liquidated_collateral_amount, is_col=True)
            debt_value = self.get_reserves_value(debt_asset, debt_to_cover)
            # collateral_value = 0
            # debt_value = 0 
            revenue = collateral_value - debt_value

            # block and transaction infos
            block_num = log['blockNumber']
            block_timestamp = self.get_block_time(block_num)
            readable_time = unix_to_readable(block_timestamp)
            tx_hash = log['transactionHash'].hex()
            index = log['transactionIndex']

            # if self.w3_liqcall is None
            # need to query from the full node
            # query transaction by tx_hash
            try:
                # time.sleep(0.005)
                tx: TxData = self.w3_liqcall.w3.eth.get_transaction_by_block(block_num, index)
            except Exception as e:
                self.logger.info(f'liquidationCalls: {{"txHash": "{tx_hash}", "time": "{readable_time}", "blockNumber": {block_num}, "index": {index}, "liquidator": "{liquidator}", "borrower": "{user}", "debt": "{debt_asset}", "repayAmount": {debt_to_cover}, "collateral":"{collateral_asset}", "gainedAmount":{liquidated_collateral_amount}, "revenue": {revenue}, "params": {params}}}')
                return
            
            tx_hash = tx['hash'].hex()
            # executor = self.w3_liqcall.query_tx_origin(tx_hash)
            executor = tx['from']
            if liquidator in ["0x0870793286aada55d39ce7f82fb2766e8004cf43"]:  # lower case
                liquidator = tx['to']

            if P_ALIAS['base_currency'] != "USD":
                native_usd_price = self.w3_liqcall.get_asset_price(NETWORK, block_num)
            else:
                native_usd_price = 1
            revenue_usd = revenue * native_usd_price
            revenues = [revenue_usd, collateral_value, debt_value]

            # query debug trace
            # res = self.w3_liqcall.query_trace_call(tx_hash)
            # v_list, mev_value = trace_call_parsing(res)
            v_list = {}
            mev_value = 0

            # query gas cost from transaction_recept by tx_hash 
            gas_used, gas_price = self.w3_liqcall.query_recpt_infos(tx_hash)
            gas_cost_native = gas_price * gas_used / 10**18
            gas_cost_usd = gas_cost_native * native_usd_price
            gas_costs = [gas_cost_usd, gas_cost_native]

            # query base fee from block by block_num 
            # base_fee = self.w3_liqcall.query_base_fee(block_num)
            # priority_fee = gas_price - base_fee
            # priority = priority_fee * gas_used / 10**18
            # v_list['priority'] = priority

            profit_native = (revenues[1] - revenues[2]) - gas_cost_native - mev_value
            profit_usd = profit_native * native_usd_price
            profits = [profit_usd, profit_native]

            self.logger.info(f'liquidationCalls: {{"txHash": "{tx_hash}", "time": "{readable_time}", "blockNumber": {block_num}, "index": {index}, "executor": "{executor}", "liquidator": "{liquidator}", "borrower": "{user}", "debt": "{debt_asset}", "repayAmount": {debt_to_cover}, "collateral":"{collateral_asset}", "gainedAmount":{liquidated_collateral_amount}, "profit": {profits}, "revenue": {revenues}, "gasCost": {gas_costs}, "MEV": {mev_value}, "params": {params}}}')


def unix_to_readable(block_timestamp):
    return datetime.fromtimestamp(block_timestamp, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')


def query_liquidation():
    w3_liq = Web3Liquidation()
    filt = gen_liquidation_filter()
    obj = None
    query_events_loop(w3_liq.w3, obj, filt, END_BLOCK)


if __name__ == '__main__':
    logger = Logger(log_file_name=LOG_FILE, log_level=logging.DEBUG, logger_name="liquidation_call").get_log()
    
    filt = gen_liquidation_filter(RESERVES)
    asyncio.run(subscribe_event_light(filt, None, None))

    # test only
    # tx_hash = "0x89d263f9197a81d2ba5bc68acf3a13920b7219f97b26666fe28499ea89cf519c"
    # res = query_trace_call(tx_hash)
    # value = trace_call_parsing(res)
    # print(value)

    # test only: https://etherscan.io/tx/0xf63ad944568f4882e7e38493ad10fd208cffd72b5c727c645cfed0e76dcbfeb2#eventlog
    # price = get_asset_price("0xF629cBd94d3791C9250152BD8dfBDF380E2a3B9c", 15960346)
    # print(price)
