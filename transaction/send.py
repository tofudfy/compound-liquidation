import time
import asyncio
from flashbots import flashbot
from configs.config import BNB48
from transaction.types import create_type0_tx, create_type2_tx
from transaction.bnb48 import Bnb48
from transaction.account import SECRET_KEYS, AccCompound


def init_send_type(net):
    if net == "Polygon":
        return SendType(
           gas_limit=1200000,
           estimate_gas=500000,
           mev_ratio=0,
           send_net=create_type2_tx,
           send_sig=create_type0_tx,
           aggregator=""   # MATIC/USD
        )
    elif net == "BSC":
        return SendType(
           gas_limit=3000000,
           estimate_gas=1500000,
           mev_ratio=0,
           send_net=create_type0_tx,
           send_sig=create_type0_tx,
           aggregator="0x137924D7C36816E0DcAF016eB617Cc2C92C05782"  # BNB/USD
        )
    elif net == "Ethereum":
        return SendType(
           gas_limit=3000000,
           estimate_gas=1500000,
           mev_ratio=0.8,
           send_net=create_type2_tx,
           send_sig=create_type2_tx,
           aggregator=""  # ETH/ETH
        )
    else:
        return None


class SendType(object):
    def __init__(self, gas_limit, estimate_gas, mev_ratio, aggregator, send_sig, send_net) -> None:
        self.gas_limit = gas_limit
        self.estimate_gas = estimate_gas
        self.mev_ratio = mev_ratio
        self.aggr = aggregator
        self.map_sig = send_sig
        self.map_net = send_net
        self.price_token = None
        self.price_decimals = None

    def create_liq_transaction(self, revenue, block_infos, sig_recv=None):
        base_fee = block_infos.base_fee
        mev = self.mev_ratio * (revenue / self.estimate_gas * 10**18  - base_fee)

        if sig_recv is not None:
            gas_fee = sig_recv['gas_price']
            tx, gas_fee = self.map_sig(gas_fee, base_fee, mev)
        else:
            gas_fee = block_infos.gas_price
            tx, gas_fee = self.map_net(gas_fee, base_fee, mev)

        return tx, gas_fee


class Sender(object):
    def __init__(self) -> None:
        self.lock = False
        self.counter = 0


class WsSender(Sender):
    def __init__(self, ws) -> None:
        super().__init__()
        self.ws = ws

    async def send_tx_task(self, signed_tx_raw):
        '''
        await ws.send(
            json.dumps({
                'm': 'sendtx',
                'p': signed_tx_raw.hex()[2:]
            }))
        '''
        await asyncio.sleep(0.001)

    async def send_transactions(self, results):
        if self.lock and len(results) == 0:
            return

        tasks = []
        for res in results:
            signed_tx_raw = res[1]
            tasks.append(asyncio.create_task(self.send_tx_task(signed_tx_raw)))

        await asyncio.gather(*tasks)


def create_self_transfer(gas_fee, acc: AccCompound):
    tx, _ = create_type0_tx(gas_fee, 0, 0)
    tx['to'] = acc.get_address()
    tx['nonce'] = acc.nonce
    acc.nonce += 1

    signed_tx_raw, _ = acc.sign_tx(tx)
    return signed_tx_raw.hex()


class BnB48Sender(Sender):
    def __init__(self, w3, bnb_price_with_decimals) -> None:
        super().__init__()
        self.bnb48 = Bnb48()
        self.w3_bnb48 = w3
        self.bnb_price = bnb_price_with_decimals / 10**18
        self.storage = {}

        self.bnb48.acc.nonce = self.w3_bnb48.eth.get_transaction_count(self.bnb48.acc.get_address())
        self.balance = self.w3_bnb48.eth.get_balance(self.bnb48.acc.get_address())
        self.bnb_gas_price = self.bnb48.query_gas_price()

    def x(self, profits, txs, expire, callback):
        bnb_cost = 0.5 * profits / self.bnb_price
        min_balance = self.balance * 22000/21000
        if bnb_cost > min_balance:
            bnb_cost = min_balance
        
        mev_gas_price = bnb_cost / 21000
        if mev_gas_price < self.bnb_gas_price:  # at least 0.00126 BNB = 0.4 USD
            return

        tx_mev = create_self_transfer(mev_gas_price, self.bnb48.acc)
        txs = tx_mev + txs
        error_code = self.bnb48.send_puissant(txs, expire)
        callback(error_code, mev_gas_price, txs, expire)
    
    async def send_transactions(self, results, expire_raw, callback, signal_recv=None):
        if self.lock and len(results) == 0:
            return

        # todo: redundent operation, depend on the design of func liquidation_start
        dedup = {}
        results_new = []
        for res in results:
            index = res[0]
            signed_tx_raw = res[1]
            profit = res[2]

            # for bnb48 only need one signer
            if dedup.get(index, None) is None:
                dedup[index] = 1
                results_new.append([profit, signed_tx_raw])

        sorted_txs_liq = sorted(results_new, reverse=True)

        # when is triggered by signal
        if signal_recv is not None:
            txs = [
                signal_recv['raw_tx']
            ]
            delay = 6  # 2 block delays in BSC
            profits = 0
            for res in sorted_txs_liq[:2]:
                profit = res[0]
                signed_tx_raw = res[1]

                profits += profit 
                txs.append(signed_tx_raw.hex())
            self.x(profits, txs, expire_raw + delay, callback)

        # 1. when is triggered by sig but sig is not recved by bnb48 validator; 2. not triggered by sig
        delay = 60  # delay for rotation of 
        for res in sorted_txs_liq[:2]:
            profit = res[0]
            signed_tx_raw = res[1]
            self.x(profit, [signed_tx_raw], expire_raw + delay, callback) 
            # todo: ?
            self.bnb48.acc.nonce += 1

        self.bnb48.acc.nonce += 1

        await asyncio.sleep(0.001)
    
    def update(self, validator: str, block_number: int, block_timestamp: int, bnb_price_with_decimals: int):
        if validator in BNB48:
            is_bnb48 = True
        else:
            is_bnb48 = False

        del_list = []
        for id, exp_time in self.storage.items():
            res = self.get_puissant_status(id)
            print(f'bnb48 status:{{"block_num": {block_number}, "is_bnb48": {is_bnb48}, "id": "{id}", "response": {res}}}')

            if 'value' in res and 'status' in res['value'] and "Dropped" in res['value']['status']:
                del_list.append(id) 
                continue

            if exp_time < block_timestamp:
                del_list.append(id)

        for id in del_list:
            self.storage.pop(id)

        # update nonce and balance
        self.bnb48.acc.nonce = self.w3_bnb48.eth.get_transaction_count(self.bnb48.acc.get_address())
        self.balance = self.w3_bnb48.eth.get_balance(self.bnb48.acc.get_address())
        self.bnb_price = bnb_price_with_decimals / 10**18


class FlashSender(Sender):
    def __init__(self, w3) -> None:
        super().__init__()
        sender = AccCompound(SECRET_KEYS['Flash'][0])
        flashbot(w3, sender.account)
        self.w3_flash = w3

    # https://github.com/flashbots/web3-flashbots/blob/master/examples/simple.py
    async def send_transactions(self, results, expire, callback, signal_recv=None):
        if self.lock and len(results) == 0:
            return
        
        for res in results:
            index = res[0]
            signed_tx_raw = res[1]

            if signal_recv is None:
                bundle = [
                    {"signed_transaction": signed_tx_raw},
                ]
            else:     
                bundle = [
                    {"signed_transaction": signal_recv['raw_tx']},
                    {"signed_transaction": signed_tx_raw},
                ]

            # send bundle targeting next block
            target_block_number = str(expire)
            error_code = 0
            try:
                self.w3_flash.flashbots.simulate(bundle, target_block_number)
                error_msg = ""
            except Exception as e:
                error_code = -1
                error_msg = e

            callback(error_code, error_msg, index)

            # replacement_uuid = str(uuid4())
            # send_result = w3.flashbots.send_bundle(
            #     bundle,
            #     target_block_number,
            #     opts={"replacementUuid": replacement_uuid},
            # )
            # logger.debug(f"index {index}, send bundles: {send_result}")
            # logger.info(f"index {index}, send bundleHash: {w3.toHex(send_result.bundle_hash())}")

        await asyncio.sleep(0.001)

    def update(self, validator, block_number, block_timestamp, bnb_price):
        pass
