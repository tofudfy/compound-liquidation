import asyncio
import json
import orjson
import timeit
import requests
import hashlib

from eth_abi import encode
from web3 import Web3
from web3.types import TxData, TxReceipt
from hexbytes import HexBytes
from websockets import connect
from requests import session
from typing import List, Dict

from logger import Logger
from configs.config import CONNECTION, NETWORK, INTVL, URL, ADDRESS_ZERO
from configs.web3_liq import Web3Liquidation
from configs.protocol import Web3CompoundVenues


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
    def __init__(self, url: str, headers=None) -> None:
        self.url = url
        self.headers = headers


async def subscribe_event_light(filt, callback, logger: Logger, sub_name="light_event_sub"):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'receipts',
        'event_filter': filt
    })
    ws = WSconnect(CONNECTION[NETWORK]['light']['url'], {'auth': CONNECTION[NETWORK]['light']['auth']})
    await subscribe_to_node(ws, sub_infos, callback, logger, sub_name)


async def subscribe_tx_light(filt, callback, logger: Logger, sub_name="light_pendTx_sub"):
    sub_infos = json.dumps({
        'm': 'subscribe',
        'p': 'txpool',
        'tx_filters': filt
    })
    ws = WSconnect(CONNECTION[NETWORK]['light']['url'], {'auth': CONNECTION[NETWORK]['light']['auth']})
    await subscribe_to_node(ws, sub_infos, callback, logger, sub_name)


async def subscribe_to_node(ws: WSconnect, sub_infos: str, callback, logger: Logger, sub_name: str):
    async with connect(ws.url, ping_interval=None, extra_headers=ws.headers) as ws:
        await ws.send(sub_infos)

        subscription_response = await ws.recv()
        logger.info(f'"{sub_name}": {subscription_response}')

        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=None)
            except Exception as e:
                raise Exception(f'subscribe to light node failed, error: {e}')
            
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


def send_msg_tenderly(tx, state_diff: Dict, block_num):
    url = "https://api.tenderly.co/api/v1/account/fdeng/project/Project/simulate"
    headers = {
        "Content-Type": "application/json",
        'X-Access-Key': "1owY8h5U2iwYfurSsy24twLuWZkjjqg9",
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
        "gas": tx['gas'],
        "state_objects": state_objects
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


# acc = AccCompound('35a0224d1a96550df9d63544f7d8b28ba3a7fb3408e9692c5f64bf2868caa34b')
def state_diff_venus_price(w3_liq: Web3Liquidation, sig_hash: str, to_addr: str, params: List, account_addr="0x314CB7E388B4491B21bB703813eC961D9Df64e0a", proxy_addr=""):
    w3 = w3_liq.w3

    tx_sig: TxData = w3.eth.get_transaction(sig_hash)
    block_num = tx_sig['blockNumber']
    aggregator = tx_sig['to']
    gas_price = tx_sig['gasPrice']

    aggr_sc = w3_liq.gen_aggregator(aggregator)
    # we simulate the price without giving the actual signal
    # thus, we need to get and change the s_transmissions of old round id that updated by last signal 
    # and query the s_transmissions of new round id, use the new value to replace the old s_transmissions 
    round_id = aggr_sc.functions.latestRound().call(block_identifier=block_num-1)
    round_id_value = aggr_sc.functions.latestRound().call(block_identifier=block_num)

    # get the value of the target sig stored
    mapping_index = calculate_mapping_index(round_id, 43)
    mapping_index_value = calculate_mapping_index(round_id_value, 43)
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

    return state_diff, gas_price, account_addr


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


def gen_contract_data():
    """
    [2023-04-16 21:35:05.116] - [line:584] - INFO:
    liquidation start: {
        "index":"1b2af322808be0448edfe7b88ca7eb32", 
        "user":"0x9109358674f1c9a1a945a1d9880fb7ef1ddc43a3", 
        "revenue":2.656284532361661, 
        "block_num":27399446, 
        "params":['0x9109358674f1c9a1a945a1d9880fb7ef1ddc43a3', 77361501995088862, '0xfD5840Cd36d94D7229439859C0112a4185BC0255'], 
        "to_addr": "0xA07c5b74C9B40447a954e1466938b865b6BBea36", 
        "gainedAmount": 131441338183, 
        "signal":"0xf90665fe402a9db7e0ada14b8374d679181a06d335bff2dbe4c3957bc07a145f"}
    """
    params_liq = ['0x9109358674F1C9a1a945a1d9880fb7EF1DDC43a3', 77361501995088862, '0xfD5840Cd36d94D7229439859C0112a4185BC0255']
    borrower = params_liq[0]
    repay_amount = params_liq[1]
    
    debt_ctoken = "0xA07c5b74C9B40447a954e1466938b865b6BBea36"
    col_ctoken = params_liq[2]
    token0 = "0x55d398326f99059fF775485246999027B3197955" # states.ctokens[debt_ctoken].configs.underlying
    token1 = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c" # states.ctokens[col_ctoken].configs.underlying
    
    zero_for_one = True
    pool_addr = "0x1111111111111111111111111111111111111111"

    function_signature = "swap(bool,uint256,address,address,address,address,address,address)"

    # Compute the function selector
    function_hash = hashlib.sha3_256(function_signature.encode()).hexdigest()[:8]
    print(f"Function selector: {function_hash}")

    # Define input parameters
    params = (
        zero_for_one,  # zeroForOne
        repay_amount,  # amount
        pool_addr,  # pair
        token0,  # token0
        token1,  # token1
        borrower,  # borrower
        debt_ctoken,  # repayCToken
        col_ctoken,  # seizeCToken
    )

    # Encode input parameters
    encoded_params = encode(["bool", "uint256", "address", "address", "address", "address", "address", "address"], params)
    print(f"Encoded parameters: {encoded_params.hex()}")

    # Assemble the data
    data = f"0x{function_hash}{encoded_params.hex()}"
    print(f"Data: {data}")

    intput = "0x1d249383"
    intput += hex(zero_for_one)[2:].zfill(64)  # zero_for_one 
    intput += hex(-params_liq[1] & (2**256-1))[2:] # repayAmount
    intput += pool_addr.lower()[2:].zfill(64)  # pair
    intput += token0.lower()[2:].zfill(64)     # token0
    intput += token1.lower()[2:].zfill(64)     # token1
    intput += params_liq[0].lower()[2:].zfill(64)  # borrower
    intput += debt_ctoken.lower()[2:].zfill(64)    # debt_ctoken
    intput += params_liq[2].lower()[2:].zfill(64)  # col_ctoken
    print(intput)


def test1():
    w3_liq = Web3Liquidation('http')
    sig_hash = "0xcc91742384aab7631e63959731cd1ffd9253d5a7f92214d1e6ae11f2a203abe5"
    to_addr = "0x95c78222B3D6e262426483D42CfA53685A67Ab9D"
    params = ['0x1F6D66bA924EBF554883Cf84d482394013eD294B', 353044375646226984767, '0x151B1e2635A717bcDc836ECd6FbB62B674FE3E1D']
    state_diff_venus_price(w3_liq, sig_hash, to_addr, params)


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
    gen_contract_data()
