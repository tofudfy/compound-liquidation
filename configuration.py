import logging

from web3 import Web3
from logger import Logger
from config_utils import json_file_load

# NOTICE: modify the argument to configure network and project
PROVIDER_TYPE = 'ipc'
NETWORK = "Ethereum"
SELECTOR = 'v3'
LIQUDATION_LOG_LEVEL = logging.DEBUG
EVENT_LOG_LEVEL = logging.DEBUG

ADDRESS_ZERO = "0x0000000000000000000000000000000000000000"
CONNECTION = {
    'Ethereum': {
        'ipc': "/data/eth/ethereum/geth.ipc",
        # 'http': "https://eth-mainnet.g.alchemy.com/v2/-rVE6Yp-pyFoYbe7wzM70zDUvN_Vlwkb",
        'http': "https://eth-mainnet.g.alchemy.com/v2/1vSGEJ78c6cVpaXsQxP3fA6D0mKVBGMs",
        # 'http': "https://eth-mainnet.g.alchemy.com/v2/hAtPgPTh1OhcpfjZq9mWz08ib4Zf_lOM",
        # 'ws': "wss://eth-mainnet.g.alchemy.com/v2/1vSGEJ78c6cVpaXsQxP3fA6D0mKVBGMs",
        'ws': "ws://176.9.111.84:58546",
        'light': {
            'url': "ws://localhost:51301",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        },
        "contract": "0x"
    },
    'Polygon': {
        'ipc': "/data/matic/.bor/data/bor.ipc",
        'http': "https://polygon-mainnet.g.alchemy.com/v2/ilY0-W2gP1BsHDtj-Of-C7IRLFe7YXRT",
        'ws': "wss://polygon-mainnet.g.alchemy.com/v2/ilY0-W2gP1BsHDtj-Of-C7IRLFe7YXRT",
        'light': {
            'url': "ws://localhost:51301",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        }
    },
    'BSC': {
        'ipc': "",
        'http': "",
        'ws': "",
        'light': {
            'url': "ws://localhost:51301",
            'auth': "085da4b6a041efcef1ef681e5c9c"
        }
    }
}

RESERVES = []
RESERVES_CONFIGS = {}
EXP_SCALE = 10 ** 18
COMPOUND = {
    'Ethereum': {
        'v3': {
            'init_block_number': 7710671,
            'comet': "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            'price_oracle': "0x65c816077C29b557BEE980ae3cC2dCE80204A0C5",
            'base_currency': "USD",
            'signals': ['aggregator'],
            'log_file': {
                'liq': ['liquidation_ethereum_compound_v3.log', 'liq_ethereum_com_v3'],
                'event': ['events_ethereum_compound_v3.log', 'eve_ethereum_com_v3'],
            },
            'ctoken_congis_file': "./users/ctoken_configs_ethereum_compound_v3.json",
            'comet_configs_file': "./users/comet_configs_ethereum_compound_v3.json",
            'users_file': "./users/users_ethereum_compound_v3.json",
            'users_file_status': 1  # 1 for continue; 0 for init from template
        }
    },
    # polygon: https://docs.aave.com/developers/v/2.0/deployed-contracts/matic-polygon-market
    'Polygon': {
    },
    'BSC': {
        'venus': {}
    }
}
COMPOUND_ALIAS = COMPOUND[NETWORK][SELECTOR]

SIGNAL_FILTER = {
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

SIGNAL_TOKEN_DICT = {
    'Ethereum': {
        'v3': {}
    },
    'BSC': {
        'venus': {}
    }
}

if PROVIDER_TYPE == 'ipc':
    provider = Web3.IPCProvider(CONNECTION[NETWORK]['ipc'])
elif PROVIDER_TYPE == 'http':
    provider = Web3.HTTPProvider(CONNECTION[NETWORK]['http'])
else:
    provider = Web3.WebsocketProvider(CONNECTION[NETWORK]['ws'])

# compound ABIs
comptroller_interface = json_file_load("./contracts/Unitroller.json")
cerc20_interface = json_file_load("./contracts/CErc20.json")
price_interface = json_file_load("./contracts/UniswapAnchoredView.json")
validator_interface = json_file_load("./contracts/ValidatorProxy.json")
aggregator_interface = json_file_load('./contracts/AccessControlledOffchainAggregator.json')

w3 = Web3(provider)
comptroller = w3.eth.contract(address=COMPOUND_ALIAS['comet'], abi=comptroller_interface['abi'])
price_oracle = w3.eth.contract(address=COMPOUND_ALIAS['price_oracle'], abi=price_interface['abi'])

log_v2 = Logger(
    log_file_name=COMPOUND_ALIAS['log_file']['event'][0],
    log_level=EVENT_LOG_LEVEL,
    logger_name=COMPOUND_ALIAS['log_file']['event'][1]
).get_log()

price_dict = {}


def query_markets_list():
    return comptroller.functions.getAllMarkets().call()


def get_reserves():
    return RESERVES


def get_reserves_configs():
    return RESERVES_CONFIGS


def get_signal_filters():
    return SIGNAL_FILTER[NETWORK][SELECTOR]['aggregator']


def token_aggregator_mapping(aggregator):
    aggregator = Web3.toChecksumAddress(aggregator)
    return SIGNAL_TOKEN_DICT[NETWORK][SELECTOR][aggregator]


def query_reserves_configs(reserves):
    """
    struct TokenConfig {
        0 address cToken;
        1 address underlying;
        2 bytes32 symbolHash;
        3 uint256 baseUnit;
        4 PriceSource priceSource;
        5 uint256 fixedPrice;
        6 address uniswapMarket;
        7 address reporter;
        8 uint256 reporterMultiplier;
        9 bool isUniswapReversed;
    }
    :param reserves:
    :return:
    """
    reserve_dic = {}
    for reserve in reserves:
        reserve_dic[reserve] = {}
        reserve_dic[reserve]['config'] = price_oracle.functions.getTokenConfigByCToken(reserve).call()

    return reserve_dic


# currently unused
def query_oracle_anchor_configs():
    upper_bound_anchor_ratio = price_oracle.functions.upperBoundAnchorRatio().call()
    lower_bound_anchor_ratio = price_oracle.functions.lowerBoundAnchorRatio().call()
    anchor_period = price_oracle.functions.anchorPeriod().call()


def aggregator_description_parse(descr):
    return descr.replace(" ", "").split("/")


def query_reserves_aggregator(reserve_configs):
    dic = {}
    unrecognized_addr = []
    aggregator_filter = []
    for reserve, infos in reserve_configs.items():
        source = infos['config'][7]
        if source == ADDRESS_ZERO:
            continue

        validator_proxy = w3.eth.contract(address=source, abi=validator_interface['abi'])

        try:
            aggregator_infos = validator_proxy.functions.getAggregators().call()
            aggregator = aggregator_infos[0]
        except Exception:
            # todo: only show newly added sources
            unrecognized_addr.append((reserve, source))
            continue

        aggregator_offchain = w3.eth.contract(address=aggregator, abi=aggregator_interface['abi'])
        descr = aggregator_offchain.functions.description().call()

        dic[aggregator] = [
            reserve,
            aggregator_description_parse(descr)
        ]

        aggregator_filter.append(
            {'to': aggregator}
        )

    return dic, unrecognized_addr, aggregator_filter


def price_scale(reserve, price):
    base_units = RESERVES_CONFIGS[reserve]['config'][3]
    return 10 ** 28 * price // base_units


def price_cache_init(reserves_configs):
    for reserve, infos in reserves_configs.items():
        ctoken = infos['config'][0]
        # current_price = price_oracle.functions.price(symbol).call()  # todo: how to get symbol?
        current_price = price_oracle.functions.getUnderlyingPrice(ctoken).call()
        price_dict[reserve] = current_price


def price_cache_write(reserve, price):
    price_dict[reserve] = price


def price_cache_read(reserve):
    reserve = Web3.toChecksumAddress(reserve)
    return price_dict[reserve]


def config_init():
    global RESERVES
    global RESERVES_CONFIGS

    RESERVES = query_markets_list()
    log_v2.info("Market reserves: {}".format(RESERVES))

    RESERVES_CONFIGS = query_reserves_configs(RESERVES)
    log_v2.info("Market reserves config: {}".format(RESERVES_CONFIGS))

    dic, unrecognized_addr, aggregator_filter = query_reserves_aggregator(RESERVES_CONFIGS)
    SIGNAL_TOKEN_DICT[NETWORK][SELECTOR].update(dic)
    log_v2.info("Unrecognized sources {}".format(unrecognized_addr))
    log_v2.info("Complete aggregator->reserve map: {}".format(SIGNAL_TOKEN_DICT[NETWORK][SELECTOR]))

    SIGNAL_FILTER[NETWORK][SELECTOR]['aggregator'].extend(aggregator_filter)
    log_v2.info("Complete aggregator filter: {}".format(SIGNAL_FILTER[NETWORK][SELECTOR]['aggregator']))

    price_cache_init(RESERVES_CONFIGS)
    log_v2.info("Reserve prices: {}".format(price_dict))


if __name__ == '__main__':
    config_init()
