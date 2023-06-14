import pandas as pd

from typing import List, Dict
from configs.config import RESERVES
from configs.tokens import CtokenInfos, new_ctokens_infos
from configs.protocol import Web3CompoundVenues, complete_ctokens_configs_info
from configs.router import SwapV2, ABIUniV2

def init_router_pools_with_balances(w3_rout: SwapV2, reserves: List, ctoken_configs: Dict[str, CtokenInfos]):
    l = len(reserves)

    array_2d = [[None for _ in range(l)] for _ in range(l)]
    for i in range(l):
        for j in range(l):
            if j <= i:
                continue
            
            token0 = ctoken_configs[reserves[i]].configs.underlying
            token1 = ctoken_configs[reserves[j]].configs.underlying

            token0_decimals = ctoken_configs[reserves[i]].configs.underlying_decimals
            token1_decimals = ctoken_configs[reserves[j]].configs.underlying_decimals

            _, token0_index = w3_rout.gen_pool_key(token0, token1)

            pool = w3_rout.query_max_liq_pool([token0, token1])
            if pool is None:
                continue

            # todo
            res = pool.liquidity
            if token0_index == 0:
                balance_i = round(res[0] / 10**token0_decimals, 2)
                balance_j = round(res[1] / 10**token1_decimals, 2)
            else:
                balance_i = round(res[1] / 10**token0_decimals, 2) 
                balance_j = round(res[0] / 10**token1_decimals, 2)
            
            array_2d[i][j] = [balance_i, balance_j]
    
    return array_2d

    
def main():
    w3_liq = Web3CompoundVenues()
    reserves = RESERVES  # w3_liq.query_markets_list()
    ctokens = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens, w3_liq, reserves)

    routers = SwapV2(ABIUniV2('pancakge_v2'))
    res = init_router_pools_with_balances(routers, reserves, ctokens)

    col_names = []
    for reserve in reserves:
        col_names.append(ctokens[reserve].configs.symbol)

    df = pd.DataFrame(res, columns=col_names, index=col_names)

    # Save DataFrame to a CSV file
    csv_file = "./outputs/pools.csv"
    df.to_csv(csv_file)


if __name__ == '__main__':
    main()
