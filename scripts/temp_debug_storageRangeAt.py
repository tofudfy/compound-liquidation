from web3 import Web3
from configs.config import load_provider

provider = load_provider('http2')

# index = str(1).zfill(64)
index = "b4b281715f5febc8302c0109f5723874ae06bd46ddd2d179f2930dc8bc0f8d38"
index_hash = Web3.keccak(bytes.fromhex(index))
result = provider.make_request(
    'debug_storageRangeAt', 
    [
        "0xa556be00db0c3b13ae4a7361cce56b99be9e9d277351b206b16d033da1eca432",  # blockhash
        0,
        "0x137924D7C36816E0DcAF016eB617Cc2C92C05782",  # aggregator contract
        index_hash.hex(),
        16
    ])
print(result)