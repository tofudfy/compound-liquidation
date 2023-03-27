import os
from web3 import Web3

from configs.config import PROVIDER_TYPE, EVENT_LOG_LEVEL, P_ALIAS, SELECTOR, load_provider
from configs.utils import json_file_load
from logger import Logger


# compound ABIs
class ABICompound(object):
    def __init__(self, selector: str):
        current_file = os.path.abspath(__file__)
        path = os.path.dirname(current_file)
        self.cerc20_interface = json_file_load(path + "/contracts/CErc20.json")['abi']
        self.comptroller_interface = json_file_load(path + "/contracts/Unitroller.json")['abi']

        if selector == 'v3':
            self.price_interface = json_file_load(path + "/contracts/UniswapAnchoredView.json")['abi']
            self.source_interface = json_file_load(path + "/contracts/ValidatorProxy.json")['abi']
        elif selector == 'venus':
            self.price_interface = json_file_load(path + "/contracts/VenusChainlinkOracle.json")['abi']
            self.source_interface = json_file_load(path + "/contracts/EACAggregatorProxy.json")['abi']

        self.aggregator_interface = json_file_load(path + '/contracts/AccessControlledOffchainAggregator.json')['abi']


class Web3Liquidation(object):
    def __init__(self, provider_type=PROVIDER_TYPE, selector=SELECTOR):
        self.selector = selector
        self.abi = ABICompound(selector)
        self.w3 = Web3(load_provider(provider_type))

    def gen_comptroller(self):
        return self.w3.eth.contract(address=P_ALIAS['comet'], abi=self.abi.comptroller_interface)

    def gen_price_oracle(self):
        comet = self.gen_comptroller()
        price_oracle = comet.functions.oracle().call()
        return self.w3.eth.contract(address=price_oracle, abi=self.abi.price_interface)

    def gen_tokens(self, token_addr):
        return self.w3.eth.contract(address=token_addr, abi=self.abi.cerc20_interface)

    def gen_source(self, source):
        return self.w3.eth.contract(address=source, abi=self.abi.source_interface)

    def gen_aggregator(self, aggregator):
        return self.w3.eth.contract(address=aggregator, abi=self.abi.aggregator_interface)

    def query_markets_list(self, identifier="latest"):
        comptroller = self.gen_comptroller()
        return comptroller.functions.getAllMarkets().call(block_identifier=identifier)


class ConfigsLiquidation(object):
    def __init__(self):
        self.w3_liq = Web3Liquidation()
        self.log_v2 = Logger(
            log_file_name=P_ALIAS['log_file']['event'][0],
            log_level=EVENT_LOG_LEVEL,
            logger_name=P_ALIAS['log_file']['event'][1]
        ).get_log()
