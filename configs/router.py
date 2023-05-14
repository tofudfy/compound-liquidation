import os
from web3 import Web3
from typing import List, Dict

from configs.config import PROVIDER_TYPE, ADDRESS_ZERO, load_provider
from configs.utils import json_file_load
from configs.tokens import CtokenInfos, new_ctokens_infos
from configs.protocol import Web3CompoundVenues, complete_ctokens_configs_info

SWAP_CONTRACTS = {
    'v2': {
        'factory': "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        'router': "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    },
    'v3': {
        'factory': "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        'router': "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        'quoter': "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
    },
    'pancakge_v2': {
        'factory': "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
        'router': "0xE592427A0AEce92De3Edee1F18E0157C05861564" 
    }
}


class ABIUniV2(object):
    def __init__(self, selector: str):
        current_file = os.path.abspath(__file__)
        path = os.path.dirname(current_file)

        self.factory_addr = SWAP_CONTRACTS[selector]['factory']
        self.router_addr = SWAP_CONTRACTS[selector]['router']
    
        self.factory = json_file_load(path + os.sep + 'contracts/Univ2Factory.json')['abi']
        self.pool = json_file_load(path + os.sep + 'contracts/Univ2Pair.json')['abi']
        # self.router = json_file_load(path + os.sep + 'contracts/UniswapV2Router02.json')


class ABIUniV3(object):
    def __init__(self):
        current_file = os.path.abspath(__file__)
        path = os.path.dirname(current_file)

        self.factory_addr = SWAP_CONTRACTS['v3']['factory']
        self.quoter_addr = SWAP_CONTRACTS['v3']['quoter']

        self.factory = json_file_load(path + os.sep + 'contracts/Univ3Factory.json')['abi']
        self.pool = json_file_load(path + os.sep + 'contracts/UniswapV3Pool.json')['abi']
        self.quoter = json_file_load(path + os.sep + 'contracts/QuoterV3.json')


class Pool(object):
    def __init__(self, pair: List, pool_addr: str, liquidity, fee: int):
        self.pair = pair
        self.pool_addr = pool_addr
        self.liquidity = liquidity
        self.fee = fee


class Web3Router(object):
    def __init__(self, abi, provider_type=PROVIDER_TYPE):
        self.abi = abi
        self.w3 = Web3(load_provider(provider_type))

    def gen_factory(self):
        return self.w3.eth.contract(address=self.abi.factory_addr, abi=self.abi.factory)

    def gen_pool(self, pair_addr):
        return self.w3.eth.contract(address=pair_addr, abi=self.abi.pool)

    def gen_pool_key(self, token0, token1):
        is_token0 = token0 < token1
        if is_token0:
            key = token0+token1
        else:
            key = token1+token0

        return key, is_token0


class RouterV2(Web3Router):
    def __init__(self, abi: ABIUniV2, provider_type=PROVIDER_TYPE):
        super().__init__(abi, provider_type)
        self.pools: Dict[str, Pool] = {}

    def query_max_liq_pool(self, pair, identifier="latest") -> Pool:
        factory = self.gen_factory()
        pair_addr = factory.functions.getPair(pair[0], pair[1]).call(block_identifier=identifier)
        if pair_addr == ADDRESS_ZERO:
            return None
        
        pool_sc = self.gen_pool(pair_addr)
        res = pool_sc.functions.getReserves().call()
        return Pool(pair, pair_addr, res, 0)
    
    def add_liq_pool(self, pair, identifier="latest"):
        pool = self.query_max_liq_pool(pair, identifier)
        key, _ = self.gen_pool_key(*pair)
        self.pools[key] = pool
    
    def get_liq_pool(self, pair) -> Pool:
        key = self.gen_pool_key(*pair) 
        return self.pools.get(key, None) 

    def print_liq_pool(self):
        res = {}
        for k, v in self.pools.items():
            if v is None:
                continue
            res[k] = v.__dict__
        return res

    def swap_simulation(self, pool: Pool, amount: int):
        pass

class RouterV3(Web3Router):
    def __init__(self, abi: ABIUniV3, provider_type=PROVIDER_TYPE):
        super().__init__(abi, provider_type)
        self.fees = [100, 500, 3000, 10000] 

    def gen_quoter(self):
        return self.w3.eth.contract(address=self.abi.quoter_addr, abi=self.quoter)

    def query_liquidity(self, pair_addr):
        pool_sc = self.gen_pool(pair_addr)
        return pool_sc.functions.liquidity().call()

    def query_max_liq_pool(self, pair, identifier="latest") -> Pool:
        factory = self.gen_factory()
        max_liq = 0
        temp_pool = None 
        for fee in self.fees:
            pair_addr = factory.functions.getPool(pair[0], pair[1], fee).call(block_identifier=identifier)
            if pair_addr == ADDRESS_ZERO:
                continue
            else:
                liq = self.query_liquidity(pair_addr)
                if liq > max_liq:
                    max_liq = liq
                    temp_pool = Pool(pair, pair_addr, max_liq, fee) 

        return temp_pool

    def add_liq_pool(self, pair, identifier="latest"):
        pool = self.query_max_liq_pool(pair, identifier=identifier)
        key, _ = self.gen_pool_key(*pair)
        self.pools[key] = pool

    def get_liq_pool(self, pair) -> Pool:
        key = self.gen_pool_key(*pair) 
        return self.pools.get(key, None) 
    
    def swap_simulation(self, pool: Pool, amount: int):
        quoter = self.gen_quoter()
        pair = pool.pair
        fee = pool.fee

        try:
            output = quoter.functions.quoteExactInputSingle(
                pair[0],
                pair[1],
                fee,
                amount,
                0
            ).call()
        except Exception as e:
            raise Exception(f'quote pool failed:{{"error": {e}, "simulation": {[pair, fee, amount]}}}')

        return output


def init_router_pools(w3_rout: RouterV3, reserves: List, ctoken_configs: Dict[str, CtokenInfos], identifier="latest"):  # -> Dict[str, Pool]:
    for i in range(len(reserves)):
        for j in range(len(reserves)):
            if j <= i:
                continue
            
            token0 = ctoken_configs[reserves[i]].configs.underlying
            token1 = ctoken_configs[reserves[j]].configs.underlying
            w3_rout.add_liq_pool([token0, token1], identifier=identifier)


def gen_pool_key(token0, token1):
    is_token0 = token0 < token1
    if is_token0:
        key = token0+token1
    else:
        key = token1+token0

    return key, is_token0


if __name__ == '__main__':
    w3_liq = Web3CompoundVenues()
    reserves = w3_liq.query_markets_list()
    ctokens = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens, w3_liq, reserves)

    routers = RouterV2(ABIUniV2('pancakge_v2'))
    init_router_pools(routers, reserves, ctokens)

    print(routers.print_liq_pool())

    # key, _ = routers.gen_pool_key("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c")
    # print(routers.pools[key].__dict__)

    # test 2
    # pair = ["0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"]
    # amount = w3_rout.swap_simulation(w3_rout, Pool(pair, 500), 2 * 10**18)
    # print(amount)
