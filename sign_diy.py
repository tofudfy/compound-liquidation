import rlp
from web3 import Web3
from rlp.sedes import (
    Binary,
    big_endian_int,
    binary,
)

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_rlp import HashableRLP
from hexbytes import HexBytes
from types_liq import SignedTxDIY

UNSIGNED_TRANSACTION_FIELDS = (
    ('nonce', big_endian_int),
    ('gasPrice', big_endian_int),
    ('gas', big_endian_int),
    ('to', Binary.fixed_length(20, allow_empty=True)),
    ('value', big_endian_int),
    ('data', binary),
)


class UnsignedTransaction(HashableRLP):
    fields = UNSIGNED_TRANSACTION_FIELDS


class Transaction(HashableRLP):
    fields = UNSIGNED_TRANSACTION_FIELDS + (
        ('v', big_endian_int),
        ('r', big_endian_int),
        ('s', big_endian_int),
    )


def sign_transaction_hash(account, transaction_hash):
    signature = account.sign_msg_hash(transaction_hash)
    (v_raw, r, s) = signature.vrs
    v = v_raw + 27
    return (v, r, s)


def encode_transaction(unsigned_tx_dict, vrs):
    (v, r, s) = vrs
    signed_transaction = Transaction(v=v, r=r, s=s, **unsigned_tx_dict)
    return rlp.encode(signed_transaction)


def sign_tx0(tx: SignedTxDIY, account):
    unsigned_transaction = UnsignedTransaction.from_dict(tx)
    transaction_hash_inter = unsigned_transaction.hash()

    (v, r, s) = sign_transaction_hash(account._key_obj, transaction_hash_inter)
    encoded_transaction = encode_transaction(tx, vrs=(v, r, s))

    return HexBytes(encoded_transaction)


if __name__ == '__main__':
    import timeit

    # Prepare the transaction data
    nonce = 123
    gas_price = 20000000000
    gas_limit = 21000
    to_address = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
    value = 0
    private_key = bytes.fromhex("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    account: LocalAccount = Account.from_key(private_key.hex())

    tx_data = {
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": gas_limit,
        "to": b"k\x17Tt\xe8\x90\x94\xc4M\xa9\x8b\x95N\xed\xea\xc4\x95'\x1d\x0f",
        "value": value,
        "data": b""
    }

    for i in range(10):
        start = timeit.default_timer()
        signed_tx_self = sign_tx0(tx_data, account)
        end = timeit.default_timer()
        print(end-start)

        start = timeit.default_timer()
        signed_tx = account.sign_transaction(tx_data)
        end = timeit.default_timer()
        print(end-start)

        print(" ")
