import time
import asyncio
from flashbots import flashbot
from configs.config import BNB48
from transaction.types import create_self_transfer, create_type0_tx, create_type2_tx
from transaction.bnb48 import Bnb48
from transaction.account import SECRET_KEYS, AccCompound

BNB_GAS_PRICE = 60000000000


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


class WsSender(object):
    def __init__(self, ws) -> None:
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
        tasks = []
        for res in results:
            signed_tx_raw = res[1]
            tasks.append(asyncio.create_task(self.send_tx_task(signed_tx_raw)))

        await asyncio.gather(*tasks)



class BnB48Sender(object):
    def __init__(self) -> None:
        self.bnb48 = Bnb48()
        self.storage = {}

    async def send_transactions(self, results, expire, callback, signal_recv=None):
        if len(results) == 0:
            return

        if signal_recv is not None:
            txs = [
                signal_recv['raw_tx']
            ]
        else:
            txs = []

        dedup = {}
        profits = 0
        for res in results:
            index = res[0]
            signed_tx_raw = res[1]
            profit = res[2]

            txs.append(signed_tx_raw.hex())

            if dedup.get(index, None) is None:
                dedup[index] = 1
                profits += profit
        
        bnb_cost = 0.8 * profits / 320
        if bnb_cost > 0.06:
            bnb_cost = 0.06 
        
        mev_gas_price = bnb_cost / 21000
        if mev_gas_price >= BNB_GAS_PRICE:  # at least 0.00126 BNB = 0.4 USD
            txs = [create_self_transfer(mev_gas_price, self.bnb48.acc)] + txs
            error_code = self.bnb48.send_puissant(txs, expire)
            callback(error_code, mev_gas_price, txs, expire)

        await asyncio.sleep(0.001)
    
    def update(self, w3, validator: str, block_number: int, block_timestamp: int):
        if validator in BNB48:
            is_bnb48 = True
        else:
            is_bnb48 = False

        del_list = []
        for id, exp_time in self.storage.items():
            res = self.get_puissant_status(id)
            print(f'bnb48 status:{{"block_num": {block_number}, "is_bnb48": {is_bnb48}, "id": "{id}", "response": {res}}}')

            if exp_time < block_timestamp:
                del_list.append(id)

        for id in del_list:
            self.storage.pop(id)

        # update nonce
        self.bnb48.acc.nonce = w3.eth.get_transaction_count(self.bnb48.acc.get_address())


class FlashSender(object):
    def __init__(self, w3) -> None:
        sender = AccCompound(SECRET_KEYS['Flash'][0])
        flashbot(w3, sender.account)
        self.w3_flash = w3

    # https://github.com/flashbots/web3-flashbots/blob/master/examples/simple.py
    async def send_transactions(self, results, expire, callback, signal_recv=None):
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

    def update(self, w3, validator, block_number, block_timestamp):
        pass
