import os
from web3 import Web3
from web3.middleware import geth_poa_middleware

from configs.config import PROVIDER_TYPE, EVENT_LOG_LEVEL, P_ALIAS, SELECTOR, load_provider
from configs.utils import json_file_load
from logger import Logger
from typing import Dict


# compound ABIs

class ABICompound(object):
    def __init__(self):
        current_file = os.path.abspath(__file__)
        self.path = os.path.dirname(current_file)
        self.cerc20_interface = json_file_load(self.path + "/contracts/CErc20.json")['abi']
        self.comptroller_interface = json_file_load(self.path + "/contracts/Unitroller.json")['abi']
        self.aggregator_interface = json_file_load(self.path + '/contracts/AccessControlledOffchainAggregator.json')['abi']


class ABICompoundV3(ABICompound):
    def __init__(self):
        super().__init__()
        self.price_interface = json_file_load(self.path + "/contracts/UniswapAnchoredView.json")['abi']
        self.source_interface = json_file_load(self.path + "/contracts/ValidatorProxy.json")['abi']


class ABICompoundVenues(ABICompound):
    def __init__(self):
        super().__init__()
        self.price_interface = json_file_load(self.path + "/contracts/VenusChainlinkOracle.json")['abi']
        self.source_interface = json_file_load(self.path + "/contracts/EACAggregatorProxy.json")['abi']
        self.vai_controller = json_file_load(self.path + "/contracts/VAIController.json")['abi']
        self.proxy_liquidator = json_file_load(self.path + '/contracts/Liquidator.json')['abi'] 
        self.bot = json_file_load(self.path + '/contracts/VenusFlashLiquidatorBot.json')['abi']


# currently is designed for compound specifically
class Web3Liquidation(object):
    def __init__(self, provider_type=PROVIDER_TYPE, abi=ABICompound()):
        self.abi = abi
        self.w3 = Web3(load_provider(provider_type))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    def gen_comptroller(self):
        return self.w3.eth.contract(address=P_ALIAS['comet'], abi=self.abi.comptroller_interface)

    # ctoken and underlying token share some of the APIs such as symbol, decimals, etc.
    def gen_ctokens(self, token_addr):
        return self.w3.eth.contract(address=token_addr, abi=self.abi.cerc20_interface)

    def gen_aggregator(self, aggregator):
        return self.w3.eth.contract(address=aggregator, abi=self.abi.aggregator_interface)

    def query_markets_list(self, identifier="latest"):
        comptroller = self.gen_comptroller()
        return comptroller.functions.getAllMarkets().call(block_identifier=identifier)
    
    '''
    # deprecated: init by query_ctokens_configs()
    def query_ctoken_underlying(self, reserves) -> Dict:
        ctoken_underlying_mapping = {}
        for reserve in reserves:
            ctoken_sc = self.gen_ctokens(reserve)
            try:
                ctoken_underlying = ctoken_sc.functions.underlying().call()
            except Exception as e:
                print(f'get ctoken {reserve} underlying error: {e}')
            
            ctoken_underlying_mapping[reserve] = ctoken_underlying
        
        return ctoken_underlying_mapping 
    '''

    # lending_pool_aave.functions.getUserAccountData(usr).call(block_identifier=block_num)
    def is_belowe_health_factor(self, user, identifier="latest"):
        comptroller = self.gen_comptroller()
        usr = Web3.toChecksumAddress(user)
        res = comptroller.functions.getAccountLiquidity(usr).call(block_identifier=identifier)
        liquidity = res[1]
        shortfall = res[2]
        if shortfall > 0:
            return True
        else:
            return False


class ConfigsLiquidation(object):
    def __init__(self):
        self.w3_liq = Web3Liquidation()
        self.log_v2 = Logger(
            log_file_name=P_ALIAS['log_file']['event'][0],
            log_level=EVENT_LOG_LEVEL,
            logger_name=P_ALIAS['log_file']['event'][1]
        ).get_log()


if __name__ == '__main__':
    w3_liq = Web3Liquidation()
    block_num = "0x1a078d7"
    index = 7
    tx = w3_liq.w3.eth.get_transaction_by_block(block_num, index)
    print(tx)
    