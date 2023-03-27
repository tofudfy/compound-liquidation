import logging
from web3 import Web3

# NOTICE: modify the argument to configure network and project
# configs: protocol
PROVIDER_TYPE = 'ipc'
# NETWORK = "Ethereum"
# SELECTOR = 'v3'
NETWORK = 'BSC'
SELECTOR = 'venus'


# utils: protocol constant
EXP_SCALE = 10 ** 18
EXCHANGE_RATE_INIT = 200000000000000000000000000
ADDRESS_ZERO = "0x0000000000000000000000000000000000000000"

# configs: logging
LIQUDATION_LOG_LEVEL = logging.DEBUG
EVENT_LOG_LEVEL = logging.DEBUG

# configs: web3 and nodes
CONNECTION = {
    'Ethereum': {
        'ipc': "/data/eth/mev/ethereum/geth.ipc",
        # 'http': "https://eth-mainnet.g.alchemy.com/v2/-rVE6Yp-pyFoYbe7wzM70zDUvN_Vlwkb",
        # 'http': "https://eth-mainnet.g.alchemy.com/v2/1vSGEJ78c6cVpaXsQxP3fA6D0mKVBGMs",
        'http': "https://eth-mainnet.g.alchemy.com/v2/hAtPgPTh1OhcpfjZq9mWz08ib4Zf_lOM",
        # 'ws': "wss://eth-mainnet.g.alchemy.com/v2/1vSGEJ78c6cVpaXsQxP3fA6D0mKVBGMs",
        'ws': "ws://3.115.81.7:8546",
        'light': {
            'url': "ws://localhost:51301",  # "ws://18.198.151.1:51315",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        },
        "contract": "0x",
        "block_interval": 12
    },
    'Polygon': {
        'ipc': "/data/matic/.bor/data/bor.ipc",
        'http': "https://polygon-mainnet.g.alchemy.com/v2/ilY0-W2gP1BsHDtj-Of-C7IRLFe7YXRT",
        'ws': "wss://polygon-mainnet.g.alchemy.com/v2/ilY0-W2gP1BsHDtj-Of-C7IRLFe7YXRT",
        'light': {
            'url': "ws://localhost:51301",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        },
        "block_interval": 2
    },
    'BSC': {
        'ipc': "/data/bsc/2/geth/geth.ipc",
        'http': "https://skilled-twilight-lambo.bsc.discover.quiknode.pro/6954660fddce3df1513d923a32e91364dcb95659/",
        'ws': "wss://skilled-twilight-lambo.bsc.discover.quiknode.pro/6954660fddce3df1513d923a32e91364dcb95659/",
        'light': {
            'url': "ws://localhost:51301",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        },
        "contract": "0x",
        "block_interval": 3
    }
}
INTVL = CONNECTION[NETWORK]['block_interval']

COMPOUND = {
    'Ethereum': {
        'v3': {
            'init_block_number': 7710671,
            'comet': "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            # 'price_oracle': "",
            'base_currency': "USD",
            'signals': ['aggregator'],
            'log_file': {
                'liq': ['liquidation_ethereum_compound_v3.log', 'liq_ethereum_com_v3'],
                'event': ['events_ethereum_compound_v3.log', 'eve_ethereum_com_v3'],
            },
            'ctoken_congis_file': "users/ctoken_configs_ethereum_compound_v3.json",
            'comet_configs_file': "users/comet_configs_ethereum_compound_v3.json",
            'users_file': "users/users_ethereum_compound_v3.json",
            'users_file_status': 1  # 1 for continue; 0 for init from template
        }
    },
    # polygon: https://docs.aave.com/developers/v/2.0/deployed-contracts/matic-polygon-market
    'Polygon': {
    },
    'BSC': {
        'venus': {
            'init_block_number': 2471511,
            'comet': "0xfD36E2c2a6789Db23113685031d7F16329158384",
            # 'price_oracle': "",
            'base_currency': "USD",
            'signals': ['aggregator'],
            'log_file': {
                'liq': ['liquidation_bsc_compound_venus.log', 'liq_bsc_com_venus'],
                'event': ['events_bsc_compound_venus.log', 'eve_bsc_com_venus'],
            },
            'ctoken_congis_file': "users/ctoken_configs_bsc_compound_venus.json",
            'comet_configs_file': "users/comet_configs_bsc_compound_venus.json",
            'users_file': "users/users_bsc_compound_venus.json",
            'users_file_status': 0  # 1 for continue; 0 for init from template
        }
    }
}
P_ALIAS = COMPOUND[NETWORK][SELECTOR]

SIGNAL_FILTER_LIST = {
    'Ethereum': {
        'v3': {
            'aggregator': []
        }
    },
    'BSC': {
        'venus': {
            'aggregator': []
        }
    }
}
S_ALIAS = SIGNAL_FILTER_LIST[NETWORK][SELECTOR]['aggregator']

SIGNAL_TOKEN_DICT = {
    'Ethereum': {
        'v3': {}
    },
    'BSC': {
        'venus': {}
    }
}
ST_ALIAS = SIGNAL_TOKEN_DICT[NETWORK][SELECTOR]

# updated on Mar 24, 2023
RESERVES_ALL = {
    "Ethereum": [
        "0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E",
        "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5",
        "0x158079Ee67Fce2f58472A96584A73C7Ab9AC95c1",
        "0x39AA39c021dfbaE8faC545936693aC917d5E7563",
        "0xf650C3d88D12dB855b8bf7D11Be6C55A4e07dCC9",
        "0xC11b1268C1A384e55C48c2391d8d480264A3A7F4",
        "0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407",
        "0xF5DCe57282A584D2746FaF1593d3121Fcac444dC",
        "0x35A18000230DA775CAc24873d00Ff85BccdeD550",
        "0x70e36f6BF80a52b3B46b3aF8e106CC0ed743E8e4",
        "0xccF4429DB6322D5C611ee964527D42E5d685DD6a",
        "0x12392F67bdf24faE0AF363c24aC620a2f67DAd86",
        "0xFAce851a4921ce59e912d19329929CE6da6EB0c7",
        "0x95b4eF2869eBD94BEb4eEE400a99824BF5DC325b",
        "0x4B0181102A0112A2ef11AbEE5563bb4a3176c9d7",
        "0xe65cdB6479BaC1e22340E4E755fAE7E509EcD06c",
        "0x80a2AE356fc9ef4305676f7a3E2Ed04e12C33946",
        "0x041171993284df560249B57358F931D9eB7b925D",
        "0x7713DD9Ca933848F6819F38B8352D9A15EA73F67"
    ],
    "BSC": [
        "0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8",
        "0xfD5840Cd36d94D7229439859C0112a4185BC0255",
        "0x95c78222B3D6e262426483D42CfA53685A67Ab9D",
        "0x2fF3d0F6990a40261c66E1ff2017aCBc282EB6d0",
        "0x151B1e2635A717bcDc836ECd6FbB62B674FE3E1D",
        "0xA07c5b74C9B40447a954e1466938b865b6BBea36",
        "0x882C173bC7Ff3b7786CA16dfeD3DFFfb9Ee7847B",
        "0xf508fCD89b8bd15579dc79A6827cB4686A3592c8",
        "0x57A5297F2cB2c0AaC9D554660acd6D385Ab50c6B",
        "0xB248a295732e0225acd3337607cc01068e3b9c10",
        "0x5F0388EBc2B94FA8E123F404b79cCF5f40b29176",
        "0x1610bc33319e9398de5f57B33a5b184c806aD217",
        "0x650b940a1033B8A1b1873f78730FcFC73ec11f1f",
        "0x334b3eCB4DCa3593BCCC3c7EBD1A1C1d1780FBF1",
        "0xf91d58b5aE142DAcC749f58A49FCBac340Cb0343",
        "0x972207A639CC1B374B893cc33Fa251b55CEB7c07",
        "0xeBD0070237a0713E8D94fEf1B728d3d993d290ef",
        "0x9A0AF7FDb2065Ce470D72664DE73cAE409dA28Ec",
        "0xec3422Ef92B2fb59e84c8B02Ba73F1fE84Ed8D71",
        "0x5c9476FcD6a4F9a3654139721c949c2233bBbBc8",
        "0x86aC3974e2BD0d60825230fa6F355fF11409df5c",
        "0x26DA28954763B92139ED49283625ceCAf52C6f94",
        "0x08CEB3F4a7ed3500cA0982bcd0FC7816688084c3",
        "0x61eDcFe8Dd6bA3c891CB9bEc2dc7657B3B422E93",
        "0x78366446547D062f45b4C0f320cDaa6d710D87bb",
        "0xb91A659E88B51474767CD97EF3196A3e7cEDD2c8",
        "0xC5D3466aA484B040eE977073fcF337f2c00071c1"
    ]
}
RESERVES = RESERVES_ALL[NETWORK]

# currently unused
'''
def query_oracle_anchor_configs(w3_comp: Web3Liquidation):
    price_oracle = w3_comp.gen_price_oracle()
    upper_bound_anchor_ratio = price_oracle.functions.upperBoundAnchorRatio().call()
    lower_bound_anchor_ratio = price_oracle.functions.lowerBoundAnchorRatio().call()
    anchor_period = price_oracle.functions.anchorPeriod().call()
'''


def load_provider(provider_type):
    if provider_type == 'ipc':
        provider = Web3.IPCProvider(CONNECTION[NETWORK]['ipc'])
    elif provider_type == 'http':
        provider = Web3.HTTPProvider(CONNECTION[NETWORK]['http'])
    else:
        provider = Web3.WebsocketProvider(CONNECTION[NETWORK]['ws'])

    return provider
