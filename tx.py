import asyncio
import json

from typing import List
from web3 import Web3
from web3.types import TxReceipt, TxParams
from websockets import connect

from utils import FakeLogger
from types_light import SignedTxDIY
from configs.config import CONNECTION, NETWORK, load_provider
from configs.web3_liq import Web3Liquidation 
from transaction.account import SECRET_KEYS, AccCompound
from transaction.types import create_type2_tx, create_type0_tx 
    
secret_keys = SECRET_KEYS[NETWORK]


def init_accounts(w3_liq: Web3Liquidation) -> List[AccCompound]:
    accounts = []
    for sk in secret_keys:
        account = AccCompound(sk)
        account.nonce = w3_liq.w3.eth.get_transaction_count(account.get_address())
        accounts.append(account)

    return accounts


def sign_sending_tx_to_tasks(index: int, tx: SignedTxDIY, profit: int, accounts: List[AccCompound]):
    coroutines = []
    for acc in accounts:
        tx['nonce'] = acc.nonce
        # todo: how to solve this issue in multiprocessing
        acc.nonce += 1
        # signed_tx_raw = acc.sign_tx_diy(tx)
        signed_tx_raw, _ = acc.sign_tx(tx)

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


# task1: 
def get_signed_transfer(from_account_index, to_account_index, val=0):
    # task1: 
    acc_from = AccCompound(SECRET_KEYS['BSC'][from_account_index])
    w3 = Web3(load_provider('http_local')) 
    acc_from.nonce = w3.eth.get_transaction_count(acc_from.get_address())
    acc_to = AccCompound(SECRET_KEYS['BNB48'][to_account_index])

    tx, _ = create_type0_tx(10000000000, value=val)
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
