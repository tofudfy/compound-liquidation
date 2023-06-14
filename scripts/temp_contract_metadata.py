import json
import requests
from ens import ENS
from web3 import Web3

from configs.config import NETWORK, RESERVES
from configs.web3_liq import Web3Liquidation

API_ENDPOINT = {
    'Ethereum': {
        'url': "https://api.etherscan.io/api?module=contract",
        "apikey": "ZBP8EK62PT6IHARCBVJ3W9VS57EA5UHBC8"
    },
    'Polygon': {
        'url': "https://api.polygonscan.com/api?module=contract",
        "apikey": "WZ8VJAFIDZJ5EYX5JPFCZ7VN4Y7H6HAKJA" 
    }
}

# api-endpoint
URL = API_ENDPOINT[NETWORK]['url']

# defining a params dict for the parameters to be sent to the API
PARAMS = {
    'action': "getsourcecode",
    'address': "",
    'apikey': ""
}
PARAMS['apikey'] = API_ENDPOINT[NETWORK]['apikey']


def get_address_enc(contract_address):
    # Instantiate the ENS resolver
    w3_liq = Web3Liquidation()
    ens = ENS.fromWeb3(w3_liq.w3)

    # Resolve the ENS name for the address
    name = ens.name(contract_address)

    # Print the contract name if available
    if name:
        print("Contract name:", name)
    else:
        print("No contract name found for the address.")


def get_address_sourcecode(contract_address):
    w3_liq = Web3Liquidation()
    # Fetch the bytecode of the contract
    bytecode = w3_liq.w3.eth.get_code(contract_address)

    # Parse the bytecode to extract the metadata
    metadata_start = bytecode.find(b'\x7b"')
    metadata_end = bytecode.find(b'"', metadata_start + 1)
    metadata_str = bytecode[metadata_start:metadata_end + 1].decode('utf-8')

    try:
        metadata = json.loads(metadata_str)
        if 'compiler' in metadata and 'metadata' in metadata['compiler']:
            metadata_json = json.loads(metadata['compiler']['metadata'])
            if 'sources' in metadata_json:
                source_file_name = list(metadata_json['sources'].keys())[0]
                print("Solidity file name:", source_file_name)
            else:
                print("Solidity file name not found in contract metadata.")
        else:
            print("Solidity file name not found in contract metadata.")
    except ValueError:
        print("Unable to parse contract metadata.")


def send_request(address):
    PARAMS['address'] = address
    r = requests.get(url=URL, params=PARAMS)
    req = r.json()
    return req


def get_reserve_comp(addr):
    w3_liq = Web3Liquidation()
    ctoken_sc = w3_liq.gen_ctokens(addr)
    comp = ctoken_sc.functions.comptroller().call()
    return comp


def get_reserves_sourcecode():
    reserves = RESERVES

    dic = {}
    for ctoken in reserves:
        addr = ctoken 
        data = send_request(ctoken)

        if data['result'][0]['Proxy'] == "1":
            addr = data['result'][0]['Implementation']
            addr = Web3.to_checksum_address(addr)
            data = send_request(addr)

        comp = get_reserve_comp(addr)
        dic[ctoken] = [
            data['result'][0]['ContractName'],
            comp
        ]

    print(dic)


if __name__ == '__main__':
    contract_address = '0x39AA39c021dfbaE8faC545936693aC917d5E7563'

    get_reserves_sourcecode()
