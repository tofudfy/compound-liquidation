from typing import TypedDict, List
from web3 import Web3
from hexbytes import HexBytes
from web3.types import LogReceipt


class SignedTxDIY(TypedDict):
    nonce: int
    gasPrice: int
    gas: int
    to: bytes
    value: int
    data: bytes


class LogEventLight(TypedDict):
    address: str
    topics: List[str]
    txIndex: int
    data: str
    transactionHash: str


class LogReceiptLight(TypedDict):
    id: str
    type: str
    blockHash: str
    blockNumber: int
    events: List[LogEventLight]


def converter(dct: LogReceiptLight) -> List[LogReceipt]:
    logs = []
    if 'events' in dct:
        for v in dct['events']:
            address = Web3.toChecksumAddress(v['address'])
            data = v['data']

            topics = []
            for topic in v['topics']:
                topics.append(HexBytes(bytes.fromhex(topic[2:])))

            logs.append(LogReceipt(**{
                "address": address,
                "data": data,
                "topics": topics,
                "blockNumber": dct['blockNumber'],
                "blockHash": HexBytes(bytes.fromhex(dct['blockHash'][2:])),
                "transactionIndex": v['txIndex'],
                "transactionHash": HexBytes(bytes.fromhex(v['transactionHash'][2:]))
            }))

    return logs
