from web3.types import TxParams 
from transaction.account import AccCompound

from configs.config import CONNECTION, NETWORK


def create_type2_tx(gas_fee, base_fee, mev, value=0, gas=22000):
    tx: TxParams = {
        # "from": get_account_addr(0),
        "value": int(value),
        "gas": int(gas),
        "maxFeePerGas": int(mev + base_fee * 2),
        "maxPriorityFeePerGas": int(mev),
        "chainId": CONNECTION[NETWORK]['chain_id'],
        "type": 2,
    }

    return tx, tx["maxFeePerGas"] 


def create_type0_tx(gas_fee, base_fee, mev, value=0, gas=22000):
    tx: TxParams = {
        # "from": get_account_addr(0),
        "value": int(value),
        "gas": int(gas),
        "gasPrice": int(gas_fee),
        # "chainId": CONNECTION[NETWORK]['chain_id'],
    }

    return tx, tx["gasPrice"]


def create_self_transfer(gas_fee, acc: AccCompound):
    tx, _ = create_type0_tx(gas_fee)
    tx['to'] = acc.get_address()
    tx['nonce'] = acc.nonce
    acc.nonce += 1

    signed_tx_raw, hash = acc.sign_tx(tx)
    return signed_tx_raw.hex()