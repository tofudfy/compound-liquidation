import asyncio
import json
import orjson
import timeit
import requests
import hashlib
import queue

from eth_abi import encode
from web3 import Web3
from web3.types import TxData, TxReceipt
from hexbytes import HexBytes
from websockets import connect
from requests import session
from typing import List, Dict

from logger import Logger
from configs.config import CONNECTION, NETWORK, INTVL, URL, ADDRESS_ZERO, AGGR_CTOKEN_MAP
from configs.web3_liq import Web3Liquidation
from configs.protocol import Web3CompoundVenues
from configs.tokens import CtokenInfos


DEV_ALL = {
    "Ethereum": 1,
    "BSC": 0
}
DEV = DEV_ALL[NETWORK]

class FakeLogger(object):
    def __init__(self) -> None:
        pass
    
    def info(self, message):
        print('INFO:', message)

    def debug(self, message):
        print('DEBUG:', message)

    def error(self, message):
        print('ERROR:', message)


class FakePool(object):
    def __init__(self) -> None:
        pass

    def terminate(self):
        pass

    def join(self):
        pass

    def apply_async(self, map_func, args=None):
        my_queue = queue.Queue()
        my_queue.put(map_func(*args))
        return my_queue


async def polling_full(w3_liq: Web3Liquidation, filt, callback):
    while True:
        w3 = w3_liq.w3
        event_filter = w3.eth.filter(filt)
        while True:
            try:
                events = event_filter.get_new_entries()
            except Exception as e:
                await asyncio.sleep(2)
                # logger.error("In users: {}".format(e))
                break

            if len(events) != 0:
                callback(events)
            # logger.error("In users: {}".format(e))
            await asyncio.sleep(INTVL)


class WSconnect(object):
    def __init__(self, url: str, headers=None, ssl=None) -> None:
        self.url = url
        self.headers = headers
        self.ssl = ssl


# https://docs.infura.io/infura/networks/ethereum/json-rpc-methods/subscription-methods/eth_subscribe
async def subscribe_event_full(ws_full, filt, callback, logger: Logger, sub_name="full_event_sub"):
    json_rpc = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["logs", filt]}
    await subscribe_full(ws_full, json_rpc, callback, logger, sub_name)


async def subscribe_tx_full(ws_full, callback, logger: Logger, sub_name="full_pendTx_sub"):
    json_rpc = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["newPendingTransactions"]}
    await subscribe_full(ws_full, json_rpc, callback, logger, sub_name)


async def subscribe_header_full(ws_full, callback, logger: Logger, sub_name="full_header_sub"):
    json_rpc = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["newHeads"]}
    await subscribe_full(ws_full, json_rpc, callback, logger, sub_name)


async def subscribe_full(ws, json_rpc, callback, logger, sub_name):
    counter = 0
    while True:
        if counter >= 3:
            raise Exception(f"subscribe {sub_name} to full nodes too many times")

        json_rpc['id'] = counter
        sub_infos = json.dumps(json_rpc)

        try:
            await subscribe_to_node(ws, sub_infos, callback, logger, sub_name)
        except Exception as e:
            if "1006" in str(e):
                logger.error(f'try to re-subscribe {sub_name} to full node: {{"error": {e}}}')
            else:
                counter += 1
                logger.error(f'try to re-subscribe {sub_name} to full node: {{"times": {counter}, "error": {e}}}')
            continue


async def subscribe_event_light(ws_light, filt, callback, logger: Logger, sub_name="light_event_sub"):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'receipts',
        'event_filter': filt
    })
    
    counter = 0
    while True:
        counter += 1
        if counter >= 6:
            raise Exception(f"subscribe {sub_name} to light node too many times")            

        try:
            await subscribe_to_node(ws_light, sub_infos, callback, logger, sub_name)
        except Exception as e:
            logger.error(f'try to re-subscribe {sub_name} to light node: {{"times": {counter}, "error": {e}}}')
            continue


async def subscribe_tx_light(ws_light, filt, callback, logger: Logger, sub_name="light_pendTx_sub"):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'txpool',
        'tx_filters': filt
    })
    await subscribe_to_node(ws_light, sub_infos, callback, logger, sub_name)


# unsolved problem: https://github.com/ethereum/web3.py/issues/1487
async def subscribe_to_node(ws: WSconnect, sub_infos: str, callback, logger: Logger, sub_name: str):
    async with connect(ws.url, ping_interval=None, extra_headers=ws.headers, ssl=ws.ssl) as ws:
        await ws.send(sub_infos)
        subscription_response = await ws.recv()
        subscription_response = subscription_response.strip("\n")
        print(f'"{sub_name}": {{"response":{subscription_response}, "subInfos":{sub_infos}}}')

        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=None)
            except Exception as e:
                raise Exception(f'subscribe {sub_name} get response from node failed: {e}')
            
            start = timeit.default_timer()
            logger.debug(f'{sub_name} async gets control')

            # orjson is faster than json
            response = orjson.loads(response)
            callback(response)

            end = timeit.default_timer() 
            logger.debug(f'{sub_name} async out of control: {{"total_time": {end-start}}}')


def send_msg(url: str, data: str):
    # s=session()
    # resp=s.post(url, json=data)

    headers = {'Content-Type': 'application/json'}
    resp = requests.request("POST", url, headers=headers, data=data)

    return resp.text


TENDERLY_USER = "fdeng"
TENDERLY_PROJECT = "Project"
TENDERLY_ACCESS_KEY = "1owY8h5U2iwYfurSsy24twLuWZkjjqg9"
TEST_BUNDLE = [
    [
        {
            "nonce": 20,
            "gasPrice": 2619047619047,
            "gasLimit": 22000,
            "to": "0xfc030e374112103c889d0c9b6dbe2b9c6fc94614",
            "value": 0,
            "data": "",
            "from": "0xfc030e374112103c889d0c9b6dbe2b9c6fc94614",
        },
        {
            "nonce": 870486,
            "gasPrice": 3000000000,
            "gasLimit": 500000,
            "to": "0x137924d7c36816e0dcaf016eb617cc2c92c05782",
            "value": 0,
            "data": "c980753900000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000320000000000000000000000000000000000000000000000000000000000000040000000101010100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280000000000000000000000002e9bed4b8ee20134054a7b8b22d1085000593e3030a0d0300040b0e0c0907080506010f020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000071407bf3c000000000000000000000000000000000000000000000000000000071407bf3c000000000000000000000000000000000000000000000000000000071407bf3c000000000000000000000000000000000000000000000000000000071407bf3c000000000000000000000000000000000000000000000000000000071414f990000000000000000000000000000000000000000000000000000000071414f9900000000000000000000000000000000000000000000000000000000714218480000000000000000000000000000000000000000000000000000000071422e66a000000000000000000000000000000000000000000000000000000071422e66a0000000000000000000000000000000000000000000000000000000714763fe8000000000000000000000000000000000000000000000000000000071493c680000000000000000000000000000000000000000000000000000000071493c6800000000000000000000000000000000000000000000000000000000714956e5a0000000000000000000000000000000000000000000000000000000714956e5a0000000000000000000000000000000000000000000000000000000714d8df660000000000000000000000000000000000000000000000000000000714f4dad800000000000000000000000000000000000000000000000000000000000000063f98b6569eab7a06764a94266a53a83d0e8efdb82376726747ad44625f6677672687e8b3b16c47bfe5c8d73249c370abac1f386d640e324e9feb202f23665a405cadc320461c68c60b76d4f92e0c0c65507c8d5f4823d8e48c6a7a1bf75f345e0dcce56416d50563156e0bb0842a18e89278c8e29599c36141e1bfa703f4a3d1b6c60105b80a2e1d5d85f579083d4568e927353032f1d36b3c076fde30fdef9ff116f4c277435a74d5a699d3857d597eb776c0aa877eb127029008786b1c0c2d0000000000000000000000000000000000000000000000000000000000000006633ad98d620188aa5e9e9d885779557908d2352687283f65959ca05d0468a98a7e7e7008e3fcb3f69ae4ae7e4ee93e328c0128d3e1933fe305ba64114befee6165a873d0c3465eac35fb26530bdaa634b7db0ced12e1781c3e77ac426cfd3c837be00f8ede6fb7f0d3e91b7016f5cb669a7744210bf17898aed53aa3f317d8ed20aa1a7912f3a60415b021f66e0318961c3480a6ebfef692704e11b857f9d75b6fb10fed0e2033fdba627c592a91201700b7a7ed7ff174c485a911ef4e62bb42",
            "from": "0xa53bdb1522a58dee57b89e0579c13b15825b8d77",
        },
        {
            "nonce": 25,
            "gasPrice": 3000000000,
            "gasLimit": 3000000,
            "to": "0x57aba600c3880d73b42b1197b90224ba8e1e0c5a",
            "value": 0,
            "data": "18de0524000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000a01656e695c7b6b77000000000000000000000000804678fa97d91b974ec2af3c843270886528a9e60000000000000000000000000e09fabb73bd3ade0a17ecc321fd13a19e81ce82000000000000000000000000e9e7cea3dedca5984780bafc599bd69add087d56000000000000000000000000ddaa0ce8f1edc89cebad99815d088f10fcd32d1200000000000000000000000095c78222b3d6e262426483d42cfa53685a67ab9d00000000000000000000000086ac3974e2bd0d60825230fa6f355ff11409df5c",
            "from": "0x4153aef7bf3c7833b82b8f2909b590ddcf6f8c15",
        }
    ],
    "0x1b2fa6f"
]

def send_msg_tenderly(tx, state_diff: Dict, block_num):
    url = f"https://api.tenderly.co/api/v1/account/{TENDERLY_USER}/project/{TENDERLY_PROJECT}/simulate"

    headers = {
        "Content-Type": "application/json",
        'X-Access-Key': TENDERLY_ACCESS_KEY,
    }

    state_objects = {}
    for addr, data in state_diff.items():
        state_objects[addr] = {}
        if 'stateDiff' in data:
            state_objects[addr]['storage'] = data['stateDiff']

        if 'balance' in data:
            state_objects[addr]['balance'] = data['balance']

    data = json.dumps({
        "save": True,
        "save_if_fails": True,
        "simulation_type": 'full',
        "network_id": tx['chainId'],
        "from": tx['from'],
        "to": tx['to'],
        "input": tx['data'],
        "value": tx['value'], 
        "gas": tx['gas'],
        # "gas_price": tx[],
        "state_objects": state_objects
    })
    print(data)

    resp = requests.request("POST", url, headers=headers, data=data)
    return resp.text


# reference: https://docs.tenderly.co/web3-gateway/references/simulate-bundle-json-rpc
def send_tenderly_simulate_bundle_gateway(bundles_with_blocknum):
    url = "https://mainnet.gateway.tenderly.co/V2gxnJbsyvoQVabveaFUi"
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "tenderly_simulateBundle",
        "params": bundles_with_blocknum
    }

    resp = requests.request("POST", url, headers=headers, data=data)
    print(resp.text)


# reference from https://docs.tenderly.co/simulations-and-forks/simulation-api/simulation-bundles
def send_tenderly_simulate_bundle_simulator(bundles):
    url = f"https://api.tenderly.co/api/v1/account/{TENDERLY_USER}/project/{TENDERLY_PROJECT}/simulate-bundle"
    headers = {
        "Content-Type": "application/json",
        'X-Access-Key': TENDERLY_ACCESS_KEY,
    }

    results = []
    for tx in bundles:
        prefix = {
            "save": True,
            "save_if_fails": True,
            "simulation_type": 'full',
            "network_id": '56',
        }
        prefix.update(tx)
        results.append(prefix)

    data = json.dumps({
        "simulations": results
    })
    print(data)

    resp = requests.request("POST", url, headers=headers, data=data)
    return resp.text


def calculate_mapping_index(key, slot: int):
    if isinstance(slot, int):
        slot_hex = hex(slot)[2:].rjust(64, '0')
    elif isinstance(slot, HexBytes):
        slot_hex = slot.hex()[2:].rjust(64, '0') 

    if isinstance(key, int):
        key_hex = hex(key)[2:].rjust(64, '0')
    # address type
    elif isinstance(key, str):
        key_hex = key[2:].rjust(64, '0')
    elif isinstance(key, HexBytes):
        key_hex = key.hex()[2:].rjust(64, '0')

    mapping_index = Web3.keccak(bytes.fromhex(key_hex + slot_hex))
    return mapping_index


class TxFees(object):
    def __init__(self, gas_price: int, mev: int, max_fee: int) -> None:
        self.gas_price = gas_price
        self.mev = mev
        self.max_fee = max_fee


# used for Venus protocol currently, not suitable for Compound V2 protocol
# acc = AccCompound('35a0224d1a96550df9d63544f7d8b28ba3a7fb3408e9692c5f64bf2868caa34b')
def state_diff_aggr_price(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, account_addr="0x314CB7E388B4491B21bB703813eC961D9Df64e0a", proxy_addr=""):
    """
    only supported AccessControlledOffchainAggregator.sol
    """
    w3 = w3_liq.w3

    tx_sig: TxData = w3.eth.get_transaction(sig_hash)
    block_num = tx_sig['blockNumber']
    aggregator = tx_sig['to']
    gas_price = tx_sig['gasPrice']
    mev = tx_sig.get('maxPriorityFeePerGas', 0)
    max_fee = tx_sig.get('maxFeePerGas')
    fees = TxFees(
        gas_price=gas_price,
        mev=mev,
        max_fee=max_fee,
    ) 

    aggr_sc = w3_liq.gen_aggregator(aggregator)

    # we simulate the price without giving the actual signal
    # thus, we need to get and change the s_transmissions of old round id that updated by last signal 
    # and query the s_transmissions of new round id, use the new value to replace the old s_transmissions 
    round_id = aggr_sc.functions.latestRound().call(block_identifier=block_num-1)
    round_id_value = aggr_sc.functions.latestRound().call(block_identifier=block_num)

    # get the value of the target sig stored
    mapping_index = calculate_mapping_index(round_id, 43+DEV)
    mapping_index_value = calculate_mapping_index(round_id_value, 43+DEV)
    value = w3.eth.get_storage_at(aggregator, mapping_index_value)
    print(mapping_index.hex(), value.hex())

    # balance
    bal_mapping_index = calculate_mapping_index(account_addr, 1)
    # value_bal = w3.eth.get_storage_at(token_addr, bal_mapping_index)

    # allowance
    inter_mapping_index = calculate_mapping_index(account_addr, 2)
    allow_mapping_index = calculate_mapping_index(proxy_addr, inter_mapping_index)
    # value_allow = w3.eth.get_storage_at(token_addr, allow_mapping_index)

    ctoken_sc = w3_liq.gen_ctokens(to_addr)
    token_addr = ctoken_sc.functions.underlying().call()
    
    # manually set tendely state override
    print(f'{{"from": "{account_addr}", "to": "{proxy_addr}", "token": "{token_addr}", "amount": {params[1]}, "block_num": {block_num}}}')

    state_diff = {
        # unused?
        # account.address: {
        #     "balance": 1 * 10**18,
        # },

        # approve and change debt balance, BEP20
        # token_addr: {
        #     "stateDiff": {
        #         # fake debt balance
        #         bal_mapping_index.hex(): hex(params[1]),
        #         allow_mapping_index.hex(): hex(params[1])
        #     }
        # },

        # modify price oracle
        aggregator: {
            "stateDiff": {
                # hex number can not with leading zero digits
                mapping_index.hex(): '0x' + value.hex()[2:].lstrip('0')
            }
        }
    }

    return state_diff, fees, account_addr


def state_diff_uniswap_anchor_price(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, ctk: Dict[str, CtokenInfos], account_addr="0x314CB7E388B4491B21bB703813eC961D9Df64e0a", proxy_addr=""):
    w3 = w3_liq.w3
    tx_sig: TxData = w3.eth.get_transaction(sig_hash)
    block_num = tx_sig['blockNumber']
    aggregator = tx_sig['to']
    gas_price = tx_sig['gasPrice']
    mev = tx_sig['maxPriorityFeePerGas'] 
    max_fee = tx_sig['maxFeePerGas']
    fees = TxFees(
        gas_price=gas_price,
        mev=mev,
        max_fee=max_fee,
    ) 

    aggr_sc = w3_liq.gen_aggregator(aggregator)
    round_id_value = aggr_sc.functions.latestRound().call(block_identifier=block_num)
    # mapping_index_value_aggr = calculate_mapping_index(round_id_value, 43+DEV)
    # value_transmit_hexbytes = w3.eth.get_storage_at(aggregator, mapping_index_value_aggr)
    # value_transmit = int(value_transmit_hexbytes.hex()[-8:], 16)
    value_transmit = aggr_sc.functions.getAnswer(round_id_value).call()

    ctoken_addr = AGGR_CTOKEN_MAP[aggregator.lower()]
    decimals_delta = ctk[ctoken_addr].configs.reporter_multiplier - ctk[ctoken_addr].configs.base_units
    value_price = int(value_transmit * 10**decimals_delta)
    value_price_hex = hex(value_price)

    decimals_delta2 = 30 - ctk[ctoken_addr].configs.base_units 
    print(f"price of ctoken {ctoken_addr} is update to {value_price * 10**decimals_delta2}")

    symbol_hash = ctk[ctoken_addr].configs.symbol_hash 
    mapping_index = calculate_mapping_index(symbol_hash, 2)

    # get the value of the target sig stored
    uniswap_anchor = "0x50ce56A3239671Ab62f185704Caedf626352741e"
    value = w3.eth.get_storage_at(uniswap_anchor, mapping_index)
    print(mapping_index.hex(), value.hex())

    if to_addr == "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5":
        token_addr = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        # bal_mapping_index = calculate_mapping_index(account_addr, 15)
        # inter_mapping_index = calculate_mapping_index(account_addr, 16)
        # allow_mapping_index = calculate_mapping_index(proxy_addr, inter_mapping_index)
    else:
        ctoken_sc = w3_liq.gen_ctokens(to_addr)
        token_addr = ctoken_sc.functions.underlying().call()
        # bal_mapping_index = calculate_mapping_index(account_addr, 15) 

    # manually set tendely state override
    print(f'{{"from": "{account_addr}", "to": "{proxy_addr}", "token": "{token_addr}", "amount": {params[1]}, "block_num": {block_num}}}')

    state_diff = {
        # token_addr: {
        #     "stateDiff": {
        #         # fake debt balance
        #         bal_mapping_index.hex(): hex(params[1]),
        #         allow_mapping_index.hex(): hex(params[1])
        #     }
        # },
        # modify price oracle
        uniswap_anchor: {
            "stateDiff": {
                # hex number can not with leading zero digits
                mapping_index.hex(): '0x' + value_price_hex[2:].rjust(len(value_price_hex) // 2 * 2, '0')
            }
        }
    }

    return state_diff, fees, account_addr


'''
def call_bundle(w3_liq: Web3Liquidation, url: str, sig_hash: str, to_addr: str, params: List):
    txs = []
    tx1 = w3_liq.w3.eth.get_raw_transaction(sig_hash).hex()
    txs.append(tx1)

    tx1_recpt: TxReceipt = w3_liq.w3.eth.get_transaction_receipt(sig_hash)
    gas_price = tx1_recpt['effectiveGasPrice']
    block_num= tx1_recpt['blockNumber'] 

    ctoken_sc = w3_liq.gen_ctokens(to_addr)
    tx2_raw = ctoken_sc.functions.liquidateBorrow(*params).build_transaction({'gasPrice': gas_price})

    sk_new = gen_new_account()
    account_new = AccCompound(sk_new)
    tx2 = account_new.sign_tx(tx2_raw).hex()
    txs.append(tx2)

    data = json.dumps({
        "method": "eth_callBundle",
        "params": [{'txs':txs,'blockNumber': hex(block_num),'stateBlockNumber':hex(block_num-1)}],
        "id": 1,
        "jsonrpc": "2.0"
    })
    
    return send_msg(url, data)
'''


def test1():
    w3_liq = Web3Liquidation('http')
    sig_hash = "0xcc91742384aab7631e63959731cd1ffd9253d5a7f92214d1e6ae11f2a203abe5"
    to_addr = "0x95c78222B3D6e262426483D42CfA53685A67Ab9D"
    params = ['0x1F6D66bA924EBF554883Cf84d482394013eD294B', 353044375646226984767, '0x151B1e2635A717bcDc836ECd6FbB62B674FE3E1D']
    state_diff_aggr_price(w3_liq, sig_hash, to_addr, params)


def test2():
    data = json.dumps({
        "method":"eth_call",
        "params":[
            {
                "value":hex(0),
                "chainId":hex(56),
                "gas":hex(8000000),
                "gasPrice":hex(5000000000),
                "from":"0x314CB7E388B4491B21bB703813eC961D9Df64e0a",
                "to":"0x0870793286aaDA55D39CE7f82fb2766e8004cF43",
                "data":"0x64fd7078000000000000000000000000f508fcd89b8bd15579dc79a6827cb4686a3592c8000000000000000000000000edaf30a3bbf3a8b20d053aad3b34450e6d5953b2000000000000000000000000000000000000000000000006b28bb2ac4f3d12ec00000000000000000000000095c78222b3d6e262426483d42cfa53685a67ab9d"
            },
            "0x1a109b1",
            {
                "0x314CB7E388B4491B21bB703813eC961D9Df64e0a":{
                    "balance":hex(1000000000000000000)
                },
                "0x2170Ed0880ac9A755fd29B2688956BD959F933F8":{
                    "stateDiff":{
                        "0xcbeef0c0f328e2b4309f3a545c7e06607e83e23cc524d49ac4cc4eaa52077453":"0x6b28bb2ac4f3d12ec",
                        "0xb9f27a955d54a7757f6bb162a0eb653cac9b62e0002dd3051545eb5120225bdd":"0x6b28bb2ac4f3d12ec"
                    }
                },
                "0xfC3069296a691250fFDf21fe51340fdD415a76ed":{
                    "stateDiff":{
                        "0xf98868cf41765daca7b7d786ceb99f4ab86d5d24ffc3efe44002b64eab3f894c":"0x6438d3bc000000000000000000000000000000000000003149b50e80"
                    }
                }
            }
        ],
        "id":1,
        "jsonrpc":"2.0"
    })

    res = send_msg(URL['http'], data)
    print(res)


if __name__ == "__main__":
    # test1()
    # test2()

    # res= send_tenderly_simulate_bundle_gateway(TEST_BUNDLE)
    res = send_tenderly_simulate_bundle_simulator(TEST_BUNDLE[0])
    print(res)
