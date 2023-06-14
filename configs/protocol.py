from web3 import Web3
from typing import List, Dict, Tuple
from configs.web3_liq import Web3Liquidation, ABICompoundVenues, ABICompoundV3
from configs.config import PROVIDER_TYPE, P_ALIAS, RESERVES
from configs.tokens import CtokenConfigs, CtokenRiskParams, CtokenInfos, new_ctoken_configs, new_ctokens_infos, new_ctoken_balances

class Web3CompoundVenues(Web3Liquidation):
    def __init__(self, provider_type=PROVIDER_TYPE):
        super().__init__(provider_type, ABICompoundVenues())
    
    def gen_price_oracle(self):
        comet = self.gen_comptroller()
        price_oracle = comet.functions.oracle().call()
        if price_oracle != P_ALIAS['price_oracle']:
            print("ERROR: price oracle address changed, please check further")

        return self.w3.eth.contract(address=price_oracle, abi=self.abi.price_interface)

    def gen_price_oracle_with_address(self, price_oracle):
        return self.w3.eth.contract(address=price_oracle, abi=self.abi.price_interface_ext)
    
    def gen_source(self, source):
        return self.w3.eth.contract(address=source, abi=self.abi.source_interface)

    def gen_bot(self):
        return self.w3.eth.contract(address=P_ALIAS['contract'], abi=self.abi.bot)

    def gen_proxy_liquidator(self, proxy: str):
        return self.w3.eth.contract(address=proxy, abi=self.abi.proxy_liquidator)

    def gen_vai_controller(self):
        return self.w3.eth.contract(address=P_ALIAS['vai'], abi=self.abi.vai_controller)
    
    def query_user_vai_repay(self, user):
        vai_controller = self.gen_vai_controller()
        user = Web3.toChecksumAddress(user)
        return vai_controller.functions.getVAIRepayAmount(user).call()
    
    def query_aggregator(self, source):
        ecc_aggr_proxy = self.gen_source(source)
        aggregator = ecc_aggr_proxy.functions.aggregator().call()
        return aggregator

    def query_ctokens_configs(self, ctoken_addr: str, identifier="latest") -> CtokenConfigs:
        ctoken_sc = self.gen_ctokens(ctoken_addr)
        try:
            ctoken_underlying = ctoken_underlying_ext = ctoken_sc.functions.underlying().call()
            # the API of symbol are same for both ctoken and its underlying token
            token_sc = self.gen_ctokens(ctoken_underlying)
            symbol = token_sc.functions.symbol().call()
            underlying_decimals = token_sc.functions.decimals().call() 
        except:
            if ctoken_addr == "0xA07c5b74C9B40447a954e1466938b865b6BBea36":
                ctoken_underlying = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"  # wBNB
                ctoken_underlying_ext = "0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB"
                symbol = "vBNB"  # symbol input to getFeed
                underlying_decimals = 18
            else:
                # todo: extend
                print(ctoken_addr)

        price_sc = self.gen_price_oracle()

        #  reporter = price_sc.functions.getFeed(symbol).call(block_identifier=identifier)  # deprecated
        # struct TokenConfig {
        #     /// @notice asset address
        #     address asset;
        #     /// @notice `oracles` stores the oracles based on their role in the following order:
        #     /// [main, pivot, fallback],
        #     /// It can be indexed with the corresponding enum OracleRole value
        #     address[3] oracles;
        #     /// @notice `enableFlagsForOracles` stores the enabled state
        #     /// for each oracle in the same order as `oracles`
        #     bool[3] enableFlagsForOracles;
        # }
        tuples = price_sc.functions.getTokenConfig(ctoken_addr).call(block_identifier=identifier)
        i = 0
        for res in tuples[2]:
            if res:
                break
            else:
                i += 1
        
        # debug
        if i != 0:
            print(f"{ctoken_addr} unexepected type {i}")

        oracle_addr = tuples[1][i]
        price_ext_sc = self.gen_price_oracle_with_address(oracle_addr)
        # struct TokenConfig {
        #     /// @notice Underlying token address, which can't be a null address
        #     /// @notice Used to check if a token is supported
        #     /// @notice 0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB for BNB
        #     address asset;
        #     /// @notice Chainlink feed address
        #     address feed;
        #     /// @notice Price expiration period of this asset
        #     uint256 maxStalePeriod;
        # }
        tuples = price_ext_sc.functions.tokenConfigs(ctoken_underlying_ext).call()
        reporter = tuples[1]

        return new_ctoken_configs(ctoken_addr, reporter, ctoken_underlying, underlying_decimals, symbol=symbol, decimals=8)
    

class Web3CompoundV3(Web3Liquidation):
    def __init__(self, provider_type=PROVIDER_TYPE, abi=ABICompoundV3()):
        super().__init__(provider_type, abi)

    def gen_price_oracle(self):
        comet = self.gen_comptroller()
        price_oracle = comet.functions.oracle().call()
        if price_oracle != P_ALIAS['price_oracle']:
            print("ERROR: price oracle address changed, please check further")
            
        return self.w3.eth.contract(address=price_oracle, abi=self.abi.price_interface)

    def gen_source(self, source):
        return self.w3.eth.contract(address=source, abi=self.abi.source_interface)
    
    def query_aggregator(self, source):
            validator_proxy = self.gen_source(source)
            aggregator_infos = validator_proxy.functions.getAggregators().call()
            aggregator = aggregator_infos[0]
            return aggregator

    def query_ctokens_configs(w3_comp: Web3Liquidation, ctoken_addr, identifier="latest") -> CtokenConfigs:
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
        price_oracle = w3_comp.gen_price_oracle()
        tuples: List = price_oracle.functions.getTokenConfigByCToken(ctoken_addr).call(block_identifier=identifier)

        ctoken_sc = w3_comp.gen_ctokens(ctoken_addr)
        decimals = ctoken_sc.functions.decimals().call()

        if ctoken_addr == "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5":
            token_underlying = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"  # WETH
            decimals_ua = 18
        else:
            token_underlying=tuples[1] 
            token_sc = w3_comp.gen_ctokens(token_underlying)
            decimals_ua = token_sc.functions.decimals().call()

        return CtokenConfigs(
            ctoken=tuples[0], 
            underlying=token_underlying,
            underlying_decimals=decimals_ua,
            symbol_hash='0x' + tuples[2].hex(),
            symbol="",  # todo
            decimals=decimals,
            base_units=tuples[3], 
            price_source=tuples[4], 
            price_fixed=tuples[5], 
            swap_router=tuples[6], 
            reporter=tuples[7], 
            reporter_multiplier=tuples[8], 
            is_uniswap_reversed=tuples[9])


def query_exchange_rate(w3_liq: Web3Liquidation, token_addr):
    ctoken_contract = w3_liq.gen_ctokens(token_addr)
    exchange_rate = ctoken_contract.functions.exchangeRateStored().call()
    return exchange_rate


def onchain_ctoken_risks(ctoken_addr: str, w3_liq: Web3Liquidation, identifier="latest") -> CtokenRiskParams:
    ctoken_contract = w3_liq.gen_ctokens(ctoken_addr)
    borrow_index = 1  # ctoken_contract.functions.borrowIndex().call(block_identifier=identifier)
    reserve_factor = 0  # ctoken_contract.functions.reserveFactorMantissa().call(block_identifier=identifier)
    exchange_rate = ctoken_contract.functions.exchangeRateStored().call(block_identifier=identifier)
    try:
        protocol_seized = ctoken_contract.functions.protocolSeizeShareMantissa().call(block_identifier=identifier) 
    except:
        protocol_seized = 0
    return CtokenRiskParams(
        borrow_index=borrow_index, 
        reserve_factor=reserve_factor, 
        exchange_rate=exchange_rate,
        protocol_seized=protocol_seized
    )


def backtesting_reserves(w3_liq: Web3Liquidation, reserves: List, block_num: int) -> Tuple[Dict[str, CtokenInfos], int]:
    ctokens_infos = {}
    for reserve in reserves:
        ctoken_risks = onchain_ctoken_risks(reserve, w3_liq, block_num)
        ctoken_balances = new_ctoken_balances()
        ctokens_infos[reserve] = CtokenInfos(ctoken_risks, ctoken_balances)

    return ctokens_infos


def complete_ctokens_configs_info(obj: Dict[str, CtokenInfos], w3_liq: Web3CompoundVenues, reserves: List, identifier="latest"):
    for ctoken_addr in reserves:
        '''
        # constant configs
        if w3_liq.selector == 'v3':
            ctoken_configs = query_ctokens_configs(w3_liq, ctoken_addr, identifier)
        elif w3_liq.selector == 'venus':
            ctoken_configs = gen_ctokens_configs(w3_liq, ctoken_addr, "EACAggr", identifier)
        else:
            ctoken_configs = query_ctokens_configs(w3_liq, ctoken_addr, identifier)
        '''
        ctoken_configs = w3_liq.query_ctokens_configs(ctoken_addr, identifier)
        obj[ctoken_addr].configs = ctoken_configs


def complete_ctokens_risks(obj: Dict[str, CtokenInfos], w3_liq: Web3Liquidation, reserves: List):
    for ctoken_addr in reserves:
        ctoken_contract = w3_liq.gen_ctokens(ctoken_addr)
        obj[ctoken_addr].risks.reserve_factor = ctoken_contract.functions.reserveFactorMantissa().call() # todo: block_identifier=identifier
        obj[ctoken_addr].risks.exchange_rate = ctoken_contract.functions.exchangeRateStored().call() # block_identifier=identifier

        # todo: venus protocol may have different interface
        try:
            obj[ctoken_addr].risks.protocol_seized = ctoken_contract.functions.protocolSeizeShareMantissa().call() # block_identifier=identifier
        except:
            pass


def ctokens_configs_test():
    w3_liq = Web3CompoundV3('http2')
    # reserves = w3_liq.query_markets_list()
    reserves = RESERVES

    ctokens_infos = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens_infos, w3_liq, reserves)

    for ctoken, data in ctokens_infos.items():
        print(f'ctoken:"{ctoken}", source_type: {data.configs.price_source}, reporter: "{data.configs.reporter}", price_multiplier: {data.configs.reporter_multiplier}, ctoken_decimal: {data.configs.decimals}, base_units: {data.configs.base_units}')


# June 3, 2023 https://bscscan.com/address/0x6592b5DE802159F3E74B2486b091D11a8256ab8A#code
def venus_oracle_test():
    w3_liq = Web3CompoundVenues()
    reserves = w3_liq.query_markets_list()

    results = {}
    for ctoken in reserves:
        res = w3_liq.query_ctokens_configs(ctoken)
        results[ctoken] = res.reporter

    print(results) 


if __name__ == '__main__':
    venus_oracle_test()
