import os
import math
from web3 import Web3
from typing import List, Dict
from itertools import permutations

from configs.config import NETWORK, SELECTOR, PROVIDER_TYPE, ADDRESS_ZERO, load_provider
from configs.utils import json_file_load
from configs.tokens import CtokenInfos, new_ctokens_infos
from configs.protocol import Web3CompoundVenues, Web3CompoundV3, complete_ctokens_configs_info

Q96 = 2**96
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

COMPS_NOT_DEBT_COL_AT_SAME = {
    'Ethereum': [
        '0x0D8775F648430679A709E98d2b0Cb6250d2887EF', # '0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E',
        '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', # '0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5',
        '0x1985365e9f78359a9B6AD760e32412f4a445E862', # '0x158079Ee67Fce2f58472A96584A73C7Ab9AC95c1',
        '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', # '0x39AA39c021dfbaE8faC545936693aC917d5E7563',
        '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599', # '0xC11b1268C1A384e55C48c2391d8d480264A3A7F4',
        '0xE41d2489571d322189246DaFA5ebDe1F4699F498', # '0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407',
        '0x89d24A6b4CcB1B6fAA2625fE562bDD9a23260359', # '0xF5DCe57282A584D2746FaF1593d3121Fcac444dC'
    ],
    'BSC': []
}
COMP_NOT_DEBT_COL_AT_SAME = COMPS_NOT_DEBT_COL_AT_SAME[NETWORK] 


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
        self.quoter = json_file_load(path + os.sep + 'contracts/QuoterV3.json')['abi']


class Pool(object):
    def __init__(self, pair: List, pool_addr: str, liquidity: int, fee: int):
        self.pair = pair
        self.pool_addr = pool_addr
        self.liquidity = liquidity
        self.fee = fee

    def check_liquidity(self, amount_out, token_index):
        if amount_out > self.liquidity[token_index]:
            return True
        else:
            return False


ROUTS_TOKENS = {
    "Ethereum": [
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    ]
}


class Routs(object):
    def __init__(self, token_in, token_out) -> None:
        self.token_in = token_in
        self.token_out = token_out
        self.rout_tokens = ROUTS_TOKENS[NETWORK]
        self.paths: List[Pool] = []

        if self.token_in in self.rout_tokens: 
            self.rout_tokens.remove(self.token_in)

        if self.token_out in self.rout_tokens: 
            self.rout_tokens.remove(self.token_out)
    
    # if token_in == token_out, the pool is None
    def single_rout_simulation(self, token_in, token_out, amount_out, swap_simulation, pools):
        key, token_in_index = gen_pool_key(token_in, token_out)
        token_out_index = 1 - token_in_index 
        pool: Pool = pools.get(key, None)

        if pool is not None: # and pool.check_liquidity(amount_out, debt_token_index):
            try:
                amount_in = swap_simulation(pool, amount_out, token_out_index)
            except:
                amount_in = -1
        else:
            amount_in = -1

        return amount_in, pool

    def find_routs(self, final_out, pools, swap_simulation, d):
        final_in = -1
        paths = []
        for depth in range(2, d, 1):
            insert = depth - 2
            amount_out = final_out
            paths_temp = []
            perm = list(permutations(self.rout_tokens, insert))
            for res in perm:
                path = (self.token_out,) + res + (self.token_in,)
                for j in range(len(path)-1):
                    token_out = path[j]
                    token_in = path[j+1]
                    amount_in, pool = self.single_rout_simulation(token_in, token_out, amount_out, swap_simulation, pools)
                    if amount_in == -1:
                        break
                    else:
                        paths_temp.append(pool)
                        amount_out = amount_in
                
                if amount_in != -1 and (amount_in < final_in or final_in == -1):
                    final_in = amount_in 
                    paths = paths_temp 
          
        return final_in, paths

    def print_routs(self) -> Dict:
        print_dict = {}
        index = 0
        for path in self.paths:
            print_dict[index] = path.__dict__
            index += 1

        return print_dict


class RoutsCompV2(Routs):
    def __init__(self, token_in, token_out) -> None:
        super().__init__(token_in, token_out)
    
    def find_routs(self, final_out, pools, swap_simulation, d):
        if (self.token_out == self.token_in) and (self.token_out in COMP_NOT_DEBT_COL_AT_SAME):
            return -1, []
        elif self.token_out == self.token_in:
            return final_out, []
        else:
            return super().find_routs(final_out, pools, swap_simulation, d)


def gen_new_routs(token_in, token_out):
    if NETWORK == "Ethereum" and SELECTOR == "v2":
        return RoutsCompV2(token_in, token_out)
    else:
        return Routs(token_in, token_out)


class Web3Swap(object):
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
            token0_index = 0
        else:
            key = token1+token0
            token0_index = 1

        return key, token0_index


class SwapV2(Web3Swap):
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
        key, token0_index = self.gen_pool_key(*pair)
        pool = self.query_max_liq_pool([pair[token0_index], pair[1-token0_index]], identifier)

        self.pools[key] = pool
    
    def get_liq_pool(self, pair) -> Pool:
        key, _ = self.gen_pool_key(*pair) 
        return self.pools.get(key, None) 

    def print_liq_pool(self):
        res = {}
        for k, v in self.pools.items():
            if v is None:
                continue
            res[k] = v.__dict__
        return res

    def swap_simulation(self, pool: Pool, amount: int, debt_token_index: int):
        x = pool.liquidity[debt_token_index] 
        y = pool.liquidity[1-debt_token_index]
        if x < amount:
            return -1

        swap_tokens = y * amount * 10000 // ((x - amount) * 9975) + 1
        return swap_tokens


def price_to_tick(p):
    return math.floor(math.log(p, 1.0001))


def price_to_sqrtp(p):
    return int(math.sqrt(p) * Q96)


def cal_amount_out(liq, sqrtp_cur, amount_in):
    price_next = int((liq * Q96 * sqrtp_cur) // (liq * Q96 + amount_in * sqrtp_cur))


class SwapV3(Web3Swap):
    def __init__(self, abi: ABIUniV3, provider_type=PROVIDER_TYPE):
        super().__init__(abi, provider_type)
        self.fees = [100, 500, 3000, 10000] 
        self.pools: Dict[str, Pool] = {}

    def gen_quoter(self):
        return self.w3.eth.contract(address=self.abi.quoter_addr, abi=self.abi.quoter)

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
        key, token0_index = self.gen_pool_key(*pair)
        pool = self.query_max_liq_pool([pair[token0_index], pair[1-token0_index]], identifier=identifier)

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

    # def swap_simulation(self, pool: Pool, amount: int, debt_token_index: int):
    #     return 0

    def swap_simulation(self, pool: Pool, amount_out: int, token_out_index: int):
        quoter = self.gen_quoter()
        pair = pool.pair
        fee = pool.fee
        token_in = pair[1-token_out_index]
        token_out = pair[token_out_index]

        if amount_out > 0:
            try:
                output = quoter.functions.quoteExactOutputSingle(
                    token_in,
                    token_out,
                    fee,
                    amount_out,
                    0
                ).call()
            except Exception as e:
                raise Exception(f'quote pool failed:{{"error": {e}, "simulation": {[pair, fee, amount_out]}}}')
        else:
            try:
                output = quoter.functions.quoteExactInputSingle(
                    token_in,
                    token_out,
                    fee,
                    -amount_out,
                    0
                ).call()
            except Exception as e:
                raise Exception(f'quote pool failed:{{"error": {e}, "simulation": {[pair, fee, amount_out]}}}')

        return output


def init_router_pools(w3_rout: SwapV3, reserves: List, ctoken_configs: Dict[str, CtokenInfos], identifier="latest"):  # -> Dict[str, Pool]:
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
        token0_index = 0
    else:
        key = token1+token0
        token0_index = 1

    return key, token0_index


def init_router_pools_test():
    # w3_liq = Web3CompoundVenues()
    w3_liq = Web3CompoundV3()
    reserves = w3_liq.query_markets_list()
    ctokens = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens, w3_liq, reserves)

    # routers = SwapV2(ABIUniV2('pancakge_v2'))
    routers = SwapV3(ABIUniV3())

    init_router_pools(routers, reserves, ctokens)
    print(routers.print_liq_pool())
    # key, _ = routers.gen_pool_key("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c")
    # print(routers.pools[key].__dict__)


def swap_simulation_test():
    routers = SwapV3(ABIUniV3())

    pair = [
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"   # WETH
    ]
    pool = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
    # SWAP 2 WETH to (3635.449270) USDC
    amount = routers.swap_simulation(Pool(pair, pool, None, 500), 2 * 10**18, 1)
    print(amount)


if __name__ == '__main__':
    # init_router_pools_test()
    swap_simulation_test()
