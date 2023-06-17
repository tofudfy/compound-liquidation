
import json
import orjson
import logging
import asyncio
import timeit
import time

from web3 import Web3
from eth_utils import keccak
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3.types import TxReceipt, TxParams
from websockets import connect

from logger import Logger
from transaction import create_type0_tx
from sign_diy import sign_tx0
from configs.config import CONNECTION, NETWORK, AAVE_SELECTOR, AAVE_V2_SIGNAL_FILTER_DICT, provider, config_init, query_reserves_list


SK = "a2e88e0e5517d8f4e7174746aa92acea66d1315356b7ffe7ad0741177d32fce0"

SECRET_KEYS = [
    'a2e88e0e5517d8f4e7174746aa92acea66d1315356b7ffe7ad0741177d32fce0',  # 0x8B280bd1A681db462aD5818CdF0e9Ec65F51bDec
    # '45575b48d22701b972f3fdc4e46860d502f68579bba9cf4d0318d4611506aa2a',  # 0x5795e3FA50eC03688Baa0F9Bc6830D084A597D91
    '769f5a7a1a16f4cae6f7696f5fd743ae856a2970f6fea5eefa7bc6be445308ba',  # 0x395483AabAd534F8e7D6a67DE766692d941868d5
    'f8667382357e23d8d2a91d6db2d42f111d8a5bec69dd31858c384de412045dec',  # 0xEAA7dc0fde5949479A5B66b883F50027539f89Ca
]


async def get_pending_transactions_light():
    counter = 0
    while True:
        counter += 1
        try:
            async with connect(CONNECTION[NETWORK]['light']['url'],
                        extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
                await ws.send(
                    json.dumps({
                        'm': 'subscribe',
                        'p': 'txpool',
                        'tx_filters': AAVE_V2_SIGNAL_FILTER_DICT[NETWORK][AAVE_SELECTOR]['aggregator']
                    }))
                subscription_response = await ws.recv()
                logger.info(subscription_response.strip())

                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=7200)
                        logger.debug("new message received")
                    except asyncio.TimeoutError:
                        logger.error("ws Timeout error: no signal")
                        continue

                    message = orjson.loads(message)
                    for tx in message['Txs']:
                        t = tx['Tx']
                        await self_contract_v3(int(t['gasPrice'], 16), t['input'], t['hash'])

        except Exception as e:
            logger.error(f"unable to connect to light node: {e}")

        if counter >= 3:
            raise Exception("connect to light nodes too many times")
        else:
            logger.info("try to reconnect to light node")


def start_new_subscribe(ws, callback) -> asyncio.Task:
    task = asyncio.create_task(txtracking_subscribe(ws, callback))
    return task


async def txtracking_subscribe(ws, callback):
    await ws.send(
        json.dumps({
            'm': 'subscribe',
            'p': 'txtrack',
        }))

    subscription_response = await ws.recv()
    logger.info(subscription_response.strip())

    while True:
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=7200)
            msg = json.loads(message)

            if msg['type'] == 'trackertxResult':
                callback(msg['result'])

        except Exception as e:
            logger.error('txtracking error: {}'.format(e))


def process_receipts(receipts: list):
    global local_nonce
    for receipt in receipts:
        receipt = TxReceipt(receipt)
        logger.info('received receipt: {}'.format(receipt))

        '''
        if reverse_dict.get(receipt['transactionHash'], ''):
            reverse_dict.clear()
            local_nonce += 1
        '''

        # for version3 only
        for i in range(len(accounts)):
            sign_acc = accounts[i]
            if sign_acc.send_dict.get(receipt['transactionHash'], 0):
                sign_acc.free()
                sign_acc.increase_nonce()
                break


async def tx_send_and_track_subscribe():
    global gl_ws
    async with connect(CONNECTION[NETWORK]['light']['url'],
                extra_headers={'auth': CONNECTION[NETWORK]['light']['auth']}) as ws:
        
        gl_ws = ws

        try:
            s1 = start_new_subscribe(ws, process_receipts)
            await s1
        except Exception as e:
            logger.error(f"tracking subscribe error: {e}")


async def self_contract(gas_fee, signal_hash):
    tx['gasPrice'] = gas_fee
    tx['nonce'] = local_nonce

    logger.debug("ready to start")
    start = timeit.default_timer()
    signed_tx = account.sign_transaction(tx)
    end = timeit.default_timer()

    ws = gl_ws
    await ws.send(json.dumps({'m': 'sendtx', 'p': signed_tx.rawTransaction.hex()[2:]}))
    
    logger.info(f'self transfer: {{"sign_time": {end-start}, "signal":"{signal_hash}", "hash":"{signed_tx.hash.hex()}", "tx":{tx}}}')
    reverse_dict[signed_tx.hash.hex()] = tx['nonce']


async def self_contract_v2(gas_fee, input_data, signal_hash):
    global local_nonce
    # if reverse_dict.get(input_data, None) is None:
    #     local_nonce += 1

    tx['nonce'] = local_nonce
    tx['gasPrice'] = gas_fee

    # logger.debug("ready to start")
    # start = timeit.default_timer()
    encoded_tx = sign_tx0(tx, account)
    # end = timeit.default_timer()

    ws = gl_ws
    await ws.send(json.dumps({'m': 'sendtx', 'p': encoded_tx.hex()[2:]}))
    
    tx_hash = '0x' + keccak(encoded_tx).hex()
    logger.info(f'self transfer: {{"hash":"{tx_hash}", "signal":"{signal_hash}", "gas_price": {gas_fee}, "nonce":{local_nonce}, "data": {input_data}}}')  # "sign_time": {end-start},
    reverse_dict[tx_hash] = tx['nonce']


async def self_contract_v3(gas_fee, input_data, signal_hash):
    if task_dict.get(input_data, None) is not None:
        acc_index = task_dict[input_data]
        sign_acc = accounts[acc_index] 
    else:
        for i in range(len(accounts)):
            sign_acc = accounts[i]
            if not sign_acc.is_inuse:
                break

    tx['nonce'] = sign_acc.nonce
    tx['gasPrice'] = gas_fee

    # logger.debug("ready to start")
    # start = timeit.default_timer()
    encoded_tx = sign_tx0(tx, sign_acc.account)
    # end = timeit.default_timer()

    ws = gl_ws
    await ws.send(json.dumps({'m': 'sendtx', 'p': encoded_tx.hex()[2:]}))
    
    tx_hash = '0x' + keccak(encoded_tx).hex()
    logger.info(f'self transfer: {{"hash":"{tx_hash}", "signal":"{signal_hash}", "gas_price": {tx["gasPrice"]}, "sender":"{sign_acc.account.address}", "nonce":{tx["nonce"]}}}')  # "sign_time": {end-start},
    
    task_dict[input_data] = sign_acc.index
    sign_acc.on_work(input_data)
    sign_acc.send_dict[tx_hash] = int(time.time())

    # time out mechanism
    current_time = int(time.time()) 
    for i in range(len(accounts)):
        sign_acc = accounts[i]
        task_str = sign_acc.is_inuse
        if not task_str:
            continue

        last_send_time = list(sign_acc.send_dict.values())[-1]
        if last_send_time + 20 < current_time:
            sign_acc.is_inuse = ""
            task_dict.pop(task_str)

        logger.debug(vars(sign_acc)) 


async def pt(message):
    try:
        await self_contract(int(message['gasPrice'], 16), message["hash"])
    except Exception as e:
        logger.debug(f'send signal test failed: {e}')


async def main():
    tasks = [
        asyncio.create_task(tx_send_and_track_subscribe()),
        asyncio.create_task(get_pending_transactions_light())
    ]

    await asyncio.gather(*tasks)
    

class SignAccount():
    def __init__(self, w3, sk, index):
        self.index = index
        self.account: LocalAccount = Account.from_key(sk)
        self.nonce = w3.eth.get_transaction_count(self.account.address)
        self.send_dict = {}
        self.is_inuse = ""

    def increase_nonce(self):
        self.nonce += 1
    
    def on_work(self, task_str):
        self.is_inuse = task_str

    def free(self):
        self.is_inuse = ""
        self.send_dict.clear() 


if __name__ == '__main__':
    w3 = Web3(provider)
    logger = Logger(log_file_name="backup_sends", log_level=logging.DEBUG, logger_name="backup").get_log()
    
    reserves = query_reserves_list()
    config_init(reserves)

    account: LocalAccount = Account.from_key(SK)
    local_nonce = w3.eth.get_transaction_count(account.address)
    gl_ws = None
    temp_data = ""
    reverse_dict = {}

    # for version 3 only
    task_dict = {}
    account_index = 0
    accounts = []
    for sk in SECRET_KEYS:
        accounts.append(SignAccount(w3, sk, account_index))
        account_index += 1
    
    for i in range(len(accounts)):
        logger.debug(vars(accounts[i]))

    tx: TxParams = {
        "to": b'\x1b\x02\xda\x8c\xb0\xd0\x97\xeb\x8dW\xa1u\xb8\x8c}\x8bG\x99u\x06',
        "value": 0,
        "gas": 30000,
        # "chainId": 137
    }

    address = account.address
    time_stamp = int(time.time())-100
    data = '0x38ed1739'
    data += '00000000000000000000000000000000000000000000000000000000000003e8'
    data += '0000000000000000000000000000000000000000000000000000000000000000'
    data += '00000000000000000000000000000000000000000000000000000000000000a0'
    data += address.lower()[2:].zfill(64)
    data += hex(time_stamp)[2:].zfill(64)
    data += '0000000000000000000000000000000000000000000000000000000000000002'
    data += '0000000000000000000000002791bca1f2de4661ed88a30c99a7a9449aa84174'
    data += '0000000000000000000000007ceb23fd6bc0add59e62ac25578270cff1b9f619'
    tx['data'] = bytes.fromhex(data[2:]) 

    asyncio.run(main())
    
