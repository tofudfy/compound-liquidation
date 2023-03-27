from web3 import Web3
from typing import List, Dict

from configs.web3_liq import Web3Liquidation
from configs.config import PROVIDER_TYPE, ADDRESS_ZERO, load_provider
from configs.utils import json_file_load


UNISWAP_CONTRACTS = {
    'v2': {
        'factory': "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        'router': "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    },
    'v3': {
        'factory': "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        'router': "0xE592427A0AEce92De3Edee1F18E0157C05861564"
    },
}

ACCOUNT = "0xEaF49401160dd0bca634d8E18d9DF41d3F6153Bb"
FACTORY_V2 = UNISWAP_CONTRACTS['v2']['factory']
FACTORY_V3 = UNISWAP_CONTRACTS['v3']['factory']
ROUTER_V2 = UNISWAP_CONTRACTS['v2']['router']
ROUTER_V3 = UNISWAP_CONTRACTS['v3']['router']
QUOTER_V3 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
FEES = [100, 500, 3000, 10000]

# factory_v2_interface = json_file_load('./contracts/Univ2Factory.json')
# pool_v2_interface = json_file_load('./contracts/Univ2Pair.json')
# router_v2_interface = json_file_load('./contracts/UniswapV2Router02.json')
# quoter_v3_interface = json_file_load('./contracts/QuoterV3.json')

# quoter_v3 = w3.eth.contract(address=QUOTER_V3, abi=quoter_v3_interface['abi'])
# router_v2 = w3.eth.contract(address=ROUTER_V2, abi=router_v2_interface['abi'])
# factory_v2 = w3.eth.contract(address=FACTORY_V2, abi=factory_v2_interface['abi'])


class ABIUniV3(object):
    def __init__(self):
        self.factory = json_file_load('./contracts/Univ3Factory.json')['abi']
        self.factory_addr = FACTORY_V3
        self.pool = json_file_load('./contracts/UniswapV3Pool.json')['abi']


class Web3Router(object):
    def __init__(self, abi, provider_type=PROVIDER_TYPE):
        self.abi = abi
        self.w3 = Web3(load_provider(provider_type))

    def gen_factory(self):
        return self.w3.eth.contract(address=self.abi.factory_addr, abi=self.abi.factory)

    def gen_pool(self, pair_addr):
        return self.w3.eth.contract(address=pair_addr, abi=self.abi.pool)

    def cal_liquidity(self, pair_addr):
        pool_sc = self.gen_pool(pair_addr)
        return pool_sc.functions.liquidity().call()


def gen_pool_key(token0, token1):
    zero_for_one = token0 < token1
    if zero_for_one:
        key = token0+token1
    else:
        key = token1+token0

    return key, zero_for_one


class Pool(object):
    def __init__(self, pair: List, fee: int):
        self.pair = pair
        self.fee = fee


def init_router_pools(w3_rout: Web3Router, reserves: List) -> Dict[str, Pool]:
    factory = w3_rout.gen_factory()
    pools = {}
    for i in range(len(reserves)):
        for j in range(len(reserves)):
            if j <= i:
                continue

            key, zero_for_one = gen_pool_key(reserves[i], reserves[j])
            if zero_for_one:
                pair = [reserves[i], reserves[j]]
            else:
                pair = [reserves[j], reserves[i]]

            max_liq = 0
            for fee in FEES:
                pair_addr = factory.functions.getPool(pair[0], pair[1], fee).call()
                if pair_addr == ADDRESS_ZERO:
                    continue
                else:
                    liq = w3_rout.cal_liquidity(pair_addr)
                    if liq > max_liq:
                        max_liq = liq
                        pools[key] = Pool(pair, fee)

    return pools


def swap_simulation(w3_rout: Web3Router, pool: Pool, amount: int):
    quoter_v3_interface = json_file_load('./contracts/QuoterV3.json')
    quoter_v3 = w3_rout.w3.eth.contract(address=QUOTER_V3, abi=quoter_v3_interface['abi'])

    pair = pool.pair
    fee = pool.fee

    try:
        output = quoter_v3.functions.quoteExactInputSingle(
            pair[0],
            pair[1],
            fee,
            amount,  # * 10**decimals,
            0
        ).call()
    except Exception as e:
        raise Exception(f'quote pool failed:{{"error": {e}, "simulation": {[pair, fee, amount]}}}')

    return output


if __name__ == '__main__':
    w3_liq = Web3Liquidation()
    reserves = w3_liq.query_markets_list()

    w3_rout = Web3Router(ABIUniV3())
    routers = init_router_pools(w3_rout, reserves)

    # test 2
    pair = ["0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"]
    amount = swap_simulation(w3_rout, Pool(pair, 500), 2 * 10**18)
    print(amount)
