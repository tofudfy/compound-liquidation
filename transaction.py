import asyncio
import json
import queue
import logging
import json
import ssl
import urllib.request
import secrets
import time

from typing import Tuple, List
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.types import TxReceipt, TxParams
from web3.middleware import geth_poa_middleware
from websockets import connect
from hexbytes import HexBytes

from sign_diy import sign_tx0
from logger import Logger
from utils import FakeLogger
from types_liq import SignedTxDIY
from configs.config import CONNECTION, NETWORK, INTVL, load_provider
from configs.web3_liq import Web3Liquidation

SECRET_KEYS = {
    "Polygon": [
        '68c857207d2cd8fdee278b8d8e69335774bb1629c683b2939709062f630408e5',  # 0x6DCdAE2FaF3D8aaa53B344C490335716AD20B716
        '365f73aa00bd53cfe6527e7804320c20d697c27902494dd30c1a7a94fb77c677',  # 0xEaF49401160dd0bca634d8E18d9DF41d3F6153Bb
        # '45575b48d22701b972f3fdc4e46860d502f68579bba9cf4d0318d4611506aa2a',  # 0x5795e3FA50eC03688Baa0F9Bc6830D084A597D91
        # 'f8667382357e23d8d2a91d6db2d42f111d8a5bec69dd31858c384de412045dec',  # 0xEAA7dc0fde5949479A5B66b883F50027539f89Ca
        # '769f5a7a1a16f4cae6f7696f5fd743ae856a2970f6fea5eefa7bc6be445308ba',  # 0x395483AabAd534F8e7D6a67DE766692d941868d5
        'a2e88e0e5517d8f4e7174746aa92acea66d1315356b7ffe7ad0741177d32fce0',  # 0x8B280bd1A681db462aD5818CdF0e9Ec65F51bDec
    ],
    "BSC": [
        "4f8580093452b5663d4ec462440907f998ea23944187454255b23961cadbcea1",  # 0x4153aEf7bf3c7833b82B8F2909b590DdcF6f8c15
        # "94643883510a28929d98b377aa9743a1f331623e8bf6a82985f4f619c133dcae",  # 0x0B8466B903951FCbb61b57316E7CCCa722e027e7
    ],
    "BNB48": [
        "15755ada41d9f255ef2fbe3e1d382ee75dea7b24fb451294c11eac90342d28a2",  # 0xFC030e374112103C889D0c9b6DBe2b9c6fC94614
    ],
    "Test": [
    
    ]
}
secret_keys = SECRET_KEYS[NETWORK]


class AccCompound(object):
    def __init__(self, sk) -> None:
        self.account: LocalAccount = Account.from_key(sk)
        # todo: multiprocessing cannot pickle module
        # self.sk = sk
        self.nonce = 0

    def sign_tx(self, tx):
        account = self.account
        # account = Account.from_key(self.sk)
        signed_tx = account.signTransaction(tx)
        return signed_tx.rawTransaction, signed_tx.hash
    
    def sign_tx_diy(self, tx) -> HexBytes:
        account = self.account
        # account = Account.from_key(self.sk)
        return sign_tx0(tx, account)

    def get_address(self):
        account = self.account
        # account = Account.from_key(self.sk)
        return account.address


def gen_new_account() -> AccCompound:
    priv = secrets.token_hex(32)
    private_key = "0x" + priv
    print ("SAVE BUT DO NOT SHARE THIS:", private_key)
    acct = AccCompound(private_key)
    print("Address:", acct.get_address())
    
    return acct 


def init_accounts(w3_liq: Web3Liquidation) -> List[AccCompound]:
    accounts = []
    for sk in secret_keys:
        account = AccCompound(sk)
        account.nonce = w3_liq.w3.eth.get_transaction_count(account.get_address())
        accounts.append(account)

    return accounts
    

async def send_tx_task(signed_tx_raw, ws):
    '''
    await ws.send(
        json.dumps({
            'm': 'sendtx',
            'p': signed_tx_raw.hex()[2:]
        }))
    '''
    await asyncio.sleep(0.001)


def sign_sending_tx_to_tasks(index: int, tx: SignedTxDIY, profit: int, accounts: List[AccCompound]):
    coroutines = []
    for acc in accounts:
        tx['nonce'] = acc.nonce
        # todo: how to solve this issue in multiprocessing
        acc.nonce += 1
        # signed_tx_raw = acc.sign_tx_diy(tx)
        signed_tx_raw, _ = acc.sign_tx(tx)

        # coroutine = send_tx_task(index, signed_tx_raw)
        coroutine = [index, signed_tx_raw, profit]
        coroutines.append(coroutine)

    return coroutines


def process_receipts(receipts: list, logger):
    for receipt in receipts:
        receipt = TxReceipt(receipt)
        logger.info('received receipt: {}'.format(receipt))


def start_new_subscribe(ws, callback, logger) -> asyncio.Task:
    task = asyncio.create_task(txtracking_subscribe(ws, callback, logger))
    return task


async def txtracking_subscribe(ws, callback, logger):
    await ws.send(
        json.dumps({
            'm': 'subscribe',
            'p': 'txtrack',
        }))

    subscription_response = await ws.recv()
    logger.info(subscription_response)

    while True:
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=7200)
            # 收交易回执与发交易的ws链接请用同一个
            msg = json.loads(message)

            if msg['type'] == 'trackertxResult':
                #通过id唯一确认订阅的流。应该单独实现一个 handleMsg的路由来分发消息
                callback(msg['result'])

        except Exception as e:
            logger.error('txtracking error: {}'.format(e))


def create_type2_tx(base_fee, mev, value=0, gas=22000):
    tx: TxParams = {
        # "from": get_account_addr(0),
        "value": int(value),
        "gas": int(gas),
        "maxFeePerGas": int(mev + base_fee * 2),
        "maxPriorityFeePerGas": int(mev),
        "chainId": CONNECTION[NETWORK]['chain_id'],
        "type": 2,
    }

    return tx


def create_type0_tx(gas_fee, value=0, gas=22000):
    tx: TxParams = {
        # "from": get_account_addr(0),
        "value": int(value),
        "gas": int(gas),
        "gasPrice": int(gas_fee),
        # "chainId": CONNECTION[NETWORK]['chain_id'],
    }

    return tx


def create_self_transfer(gas_fee, acc: AccCompound):
    tx = create_type0_tx(gas_fee)
    tx['to'] = acc.get_address()
    tx['nonce'] = acc.nonce
    tx["chainId"] = CONNECTION[NETWORK]['chain_id']

    signed_tx_raw, hash = acc.sign_tx(tx)
    return signed_tx_raw.hex()


'''
async def self_transfer(gas_fee, signal_hash):
    account = AccCompound(SECRET_KEYS['Test'][0])

    tx = create_type0_tx(gas_fee)
    tx['to'] = account.get_address()
    tx['nonce'] = account.nonce

    signed_tx = account.sign_transaction(tx)
    inverse_dict[signed_tx.hash.hex()] = tx['nonce']

    ws = get_websocket()
    await ws.send(json.dumps({'m': 'sendtx', 'p': signed_tx.rawTransaction.hex()[2:]}))
    print(f'self transfer: {{"signal":"{signal_hash}", "hash":"{signed_tx.hash.hex()}", "tx":{tx}}}')


async def self_contract(gas_fee, signal_hash):
    account = AccCompound(SECRET_KEYS['Test'][0])
    address = account.get_address()

    tx = create_type0_tx(gas_fee, gas=30000)
    tx['to'] = '0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506'
    tx['nonce'] = account.nonce

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
    tx['data'] = data 

    signed_tx = account.sign_transaction(tx)
    inverse_dict[signed_tx.hash.hex()] = tx['nonce']

    ws = get_websocket()
    await ws.send(json.dumps({'m': 'sendtx', 'p': signed_tx.rawTransaction.hex()[2:]}))
    print(f'self transfer: {{"signal":"{signal_hash}", "hash":"{signed_tx.hash.hex()}", "tx":{tx}}}')
'''


def add_executor(address):
    data = '0x1f5a0bbe'
    data += address.lower()[2:].zfill(64)

    tx: TxParams = {
        "to": '0x7E977e82e3eaf3DB7c3dfCCf727C66Bdf80d6Dee',
        "value": 0,
        "data": data,
        "gas": 50000,
        "gasPrice": 135000000000,
        "chainId": CONNECTION[NETWORK]['chain_id'],
    }

    return tx


# task2: 
def get_signed_add_executor(executor_index):
    sk = secret_keys[executor_index]
    account = AccCompound(sk)
    address = account.get_address()

    tx = add_executor(address)
    tx['nonce'] = account.nonce
    print(tx)

    return account.sign_tx(tx)


def query_base_fee():
    w3 = Web3(load_provider('http'))
    base_fee = w3.eth.get_block(block_identifier="latest").baseFeePerGas
    return base_fee


def create_type2_tx_wrap(mev, value=0, gas=22000):
    base_fee = query_base_fee()
    return create_type2_tx(base_fee, mev, value, gas) 


# task1: 
def get_signed_transfer(from_account_index, to_account_index, val=0):
    # task1: 
    acc_from = AccCompound(SECRET_KEYS['BSC'][from_account_index])
    w3 = Web3(load_provider('http_local')) 
    acc_from.nonce = w3.eth.get_transaction_count(acc_from.get_address())
    acc_to = AccCompound(SECRET_KEYS['BNB48'][to_account_index])

    tx = create_type0_tx(10000000000, value=val)
    tx['nonce'] = acc_from.nonce
    tx['to'] = acc_to.get_address()
    print(tx)
    acc_from.nonce += 1

    return acc_from.sign_tx(tx)


Total_txs_sent = 0
async def send_tx_every10(ws, txcount: int):
    # 收交易回执与发交易的ws了解请用同一个
    global Total_txs_sent
    for i in range(txcount):
        signed_tx_raw, hash = get_signed_transfer(0, 0, 0.06*10**18)
        # signed_tx_raw, hash = get_signed_add_executor(0)

        print('send transaction:', hash.hex())
        await ws.send(json.dumps({'m': 'sendtx', 'p': signed_tx_raw.hex()[2:]}))

        Total_txs_sent += 1
        await asyncio.sleep(10)

    print('Total_txs_sent', Total_txs_sent)


async def main():
    path = 'ws://127.0.0.1:51316'
    Total_txs_to_send = 1

    async with connect(path, extra_headers={'auth': '085da4b6a041efcef1ef681e5c9c'}, max_size=1048576 * 4) as ws:
        s1 = start_new_subscribe(ws, process_receipts, FakeLogger())
        asyncio.create_task(send_tx_every10(ws, Total_txs_to_send))
        await s1


if __name__ == '__main__':
    asyncio.run(main())
    # gen_new_account()
