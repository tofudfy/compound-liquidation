import numpy as np
import json
import time

from typing import Dict, List
from web3 import Web3
from web3.types import LogReceipt
from hexbytes import HexBytes

from eth_abi import decode
from configs.config import INTVL, ADDRESS_ZERO, P_ALIAS, S_ALIAS, ST_ALIAS
from configs.web3_liq import Web3Liquidation
from configs.tokens import CtokenInfos, new_ctokens_infos, complete_ctokens_configs_info

from configs.config import RESERVES

TRANSMIT_FUNC_SIG = bytes.fromhex('c9807539')
TRANSMIT_ARG_TYPES1 = ['bytes', 'bytes32[]', 'bytes32[]', 'bytes32']
TRANSMIT_ARG_TYPES2 = ['bytes32', 'bytes32', 'int192[]']

COMPOUND_V3_SIGNALS_FILTER_TEMP = """
{
    "address": "",
    "topics": [
        [
            "0xf6a97944f31ea060dfde0566e4167c1a1082551e64b60ecb14d599a9d023d451"
        ]
    ]
}
"""

"""
NewTransmission (index_topic_1 uint32 aggregatorRoundId, int192 answer, address transmitter, int192[] observations, bytes observers, bytes32 rawReportContext)
[topic0] 0xf6a97944f31ea060dfde0566e4167c1a1082551e64b60ecb14d599a9d023d451
"""
EVENT_ABI = {
    "0xf6a97944f31ea060dfde0566e4167c1a1082551e64b60ecb14d599a9d023d451": {
        "name": "NewTransmission",
        "index_topic": ["uint32"],
        "data": ["int192", "address", "int192[]", "bytes", "bytes32"]
    }
}


class AggregatorInfos(object):
    def __init__(self, token: str, pair_symbols: List):
        self.token = token
        self.pair_symbols = pair_symbols


class Signals(object):
    def __init__(self, source_token_map: Dict[str, AggregatorInfos], aggregator_source_filter: List):
        self.signal_token_map = source_token_map
        self.signals_event_filter_light = aggregator_source_filter
        self.signals_epoch: Dict[str, int] = {}

    def get_token_from_aggr(self, signal):
        signal = Web3.toChecksumAddress(signal)
        return self.signal_token_map[signal]
    
    def event_filter_convert(self) -> List:
        event_filter = []
        for data in self.signals_event_filter_light:
            for k, v in data.items():
                event_filter.append(v)
            
        return event_filter

    def tx_filter_and_parsing(self, tx_attribute_dict, gas_price):
        sender = tx_attribute_dict['from']
        contract_addr = tx_attribute_dict['to']
        input_str = tx_attribute_dict['input']
        call_data_bin = bytes.fromhex(input_str[2:])

        if len(call_data_bin) <= 4:
            raise Exception("call data error")

        method_signature = call_data_bin[:4]
        if method_signature != TRANSMIT_FUNC_SIG:
            raise Exception("unknown function signature")

        signal_gasprice = tx_attribute_dict['gasPrice']
        local_gasprice = gas_price
        if 0.9*local_gasprice > signal_gasprice:
            raise Exception(f'signal price too low: {{"local":{local_gasprice}, "signal":{signal_gasprice}}}')

        args = decode(TRANSMIT_ARG_TYPES1, call_data_bin[4:])
        args = decode(TRANSMIT_ARG_TYPES2, args[0])

        raw_report_ctx = args[0]
        signal_epoch = int(raw_report_ctx[-5:].hex(), 16)
        local_epoch = self.signals_epoch.get(contract_addr, 0)
        if local_epoch > signal_epoch:
            raise Exception(f'signal stale report: {{"local":{local_epoch}, "signal":{signal_epoch}}}')
        else:
            self.signals_epoch[contract_addr] = signal_epoch

        a = np.array(args[2])
        price = a[len(a)//2]

        # logger.debug("parsing result: {} {}".format(contract_addr, price))
        return self.no_name(contract_addr, price)

    def no_name(self, aggregator, price) -> List:
        r = []
        aggr_infos = self.signal_token_map[aggregator]
        for aggr_info in aggr_infos: 
            token_addr = aggr_info.token
            pair_symbols = aggr_info.pair_symbols
            # logger.debug("the matched info of aggregator {} is {}".format(aggregator, aggr_infos))

            if pair_symbols[1] == P_ALIAS['base_currency']:
                r.append((token_addr, price))
            # todo: elif
            else:
                raise Exception("unrecognize aggregators")
            
        return r


def gen_signals_filter(signals: Signals):
    filt = json.loads(COMPOUND_V3_SIGNALS_FILTER_TEMP)
    filt['address'] = signals.event_filter_convert()
    return filt


def init_signals(w3_liq: Web3Liquidation, reserves: List, ctokens: Dict[str, CtokenInfos]):
    source_token_dic, aggregator_source_filter = query_reserves_aggregator(w3_liq, reserves, ctokens)

    source_token_dic.update(ST_ALIAS)
    aggregator_source_filter.extend(S_ALIAS)
    return Signals(source_token_dic, aggregator_source_filter)


# convert 'A / ETH' to [A,ETH]
def aggregator_description_parse(descr) -> List:
    return descr.replace(" ", "").split("/")


def query_reserves_aggregator(w3_liq: Web3Liquidation, reserves: List, ctokens: Dict[str, CtokenInfos]) -> (Dict[str, List[AggregatorInfos]], List):
    dic = {}
    aggregator_filter = []

    for reserve in reserves:
        source = ctokens[reserve].configs.reporter
        if source == ADDRESS_ZERO:
            print(reserve)
            continue

        source_type = ctokens[reserve].configs.reporter_type
        if source_type == "validator":
            validator_proxy = w3_liq.gen_source(source)
            aggregator_infos = validator_proxy.functions.getAggregators().call()
            aggregator = aggregator_infos[0]
        elif source_type == "EACAggr":
            ecc_aggr_proxy = w3_liq.gen_source(source)
            aggregator = ecc_aggr_proxy.functions.aggregator().call()
        else:
            raise Exception('invalid reporter type')

        aggregator_offchain = w3_liq.gen_aggregator(aggregator)
        descr = aggregator_offchain.functions.description().call()

        if dic.get(aggregator, None) is None:
            dic[aggregator] = []
        
        dic[aggregator].append(AggregatorInfos(reserve, aggregator_description_parse(descr)))

        aggregator_filter.append(
            {'to': aggregator}
        )

    return dic, aggregator_filter


def new_ctoken_price(price=0, last_update=0):
    return CtokenPrice(price, last_update)


# introduced by compound protocol
def price_scale(price, decimals):
    return 10 ** 28 * price // 10**decimals


class CtokenPrice(object):
    def __init__(self, price: int, last_update: int):
        self.price_current = price
        self.price_cache = 0
        self.last_update = last_update
        self.is_comfired = True
    
    # update by new pending signals
    def update(self, new_price, last_update):
        if self.is_comfired:
            self.price_cache = self.price_current
        
        self.price_current = new_price
        self.last_update = last_update
        self.is_comfired = False

    # revert when is not comfirmed for a long time
    def revert(self):
        if not self.is_comfired and self.last_update + INTVL * 5 < int(time.time()):
            self.price_current = self.price_cache
            self.price_cache = 0
            self.is_comfired = True
    
    # comfirmed by the events
    def comfirm(self, log: LogReceipt, decimals):
        if log.get('removed', False):
            return

        topic = log['topics'][0].hex()
        obj = EVENT_ABI.get(topic, None)
        if obj is None:
            return

        try:
            data = bytes.fromhex(log['data'][2:])
            args_data = decode(obj['data'], data)
        except:
            return

        if obj['name'] == 'NewTransmission':
            answer = args_data[0]
            new_price = price_scale(answer, decimals)
            # raw_report_context = args_data[4]

            self.price_current = new_price
            self.is_comfired = True 


def init_ctoken_price(w3_comp: Web3Liquidation, ctoken_addr, identifier="latest") -> CtokenPrice:
    price_oracle = w3_comp.gen_price_oracle()
    # current_price = price_oracle.functions.price(symbol).call()  # todo: how to get symbol?
    current_price = price_oracle.functions.getUnderlyingPrice(ctoken_addr).call(block_identifier=identifier)
    return CtokenPrice(current_price, int(time.time()))


def complete_ctokens_price_info(obj: Dict[str, CtokenInfos], w3_liq: Web3Liquidation, reserves: List, identifier="latest"):
    for ctoken_addr in reserves:
        # update by pending tx
        ctoken_price = init_ctoken_price(w3_liq, ctoken_addr, identifier)
        obj[ctoken_addr].price = ctoken_price


def tx_filter_test():
    """
    # https://etherscan.io/tx/0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375
    w3_liq = Web3Liquidation('http')
    tx = w3_liq.w3.eth.get_transaction("0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375")
    """
    tx = {'blockHash': HexBytes('0x4d7001877d2c9a69b85b1f5ca37168f0494c3ec67dc2d90a4f4d5a6037ff131b'), 'blockNumber': 16903768, 'hash': HexBytes('0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375'), 'accessList': [], 'chainId': '0x1', 'from': '0xCF4Be57aA078Dc7568C631BE7A73adc1cdA992F8', 'gas': 740000, 'gasPrice': 16907912669, 'input': '0xc9807539000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000003200000000000000000000000000000000000000000000000000000000000000400010000010001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002800000000000000000000000f4f5545633e09805a78067ed5d8df24200050398020e05080003020c01070a040b090d0f060000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000167909a000000000000000000000000000000000000000000000000000000000167b1d8000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167bb3e000000000000000000000000000000000000000000000000000000000167bfdf000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cef6000000000000000000000000000000000000000000000000000000000167f79d000000000000000000000000000000000000000000000000000000000167fa9f00000000000000000000000000000000000000000000000000000000016820f3000000000000000000000000000000000000000000000000000000000168286c0000000000000000000000000000000000000000000000000000000000000006372bffca6271a89560dab24d3a05573b383677163783dd1353d93e1ce22169124702dddfe2697f1df818821bdc4c01e391f935ee1e29fda25d5c47940b0a058430dd021f694931840b458c82782b4e45ab536ffa73900907af4bfadd07ddf85cf8ee62ddd598afd656c27656df014730e578dd635a30e59e10ac79467e743fe8b437ec30d8f3c28dbc6b69ff7e00f6f87137a7916e605b65f14a1516de588da75ef78a22c74d7dea5c0ee1baa116773f3ecd3e244b07a5df15f3506b5d727d6b00000000000000000000000000000000000000000000000000000000000000061d1b72ec1efdd79e8fa8cac54081209cb5eeff9b7994157214004bd5dfa286234e2d074b27444faf986b114dd748cba19fbebc008911c90648dd1ab9c99be77e4e6fc84953d7a1b6f76301e1ac0fb44eae0d3d93124760a32f676509c1a021057b0e6af01fc20ee9ce2810296a3230b298dcb459623d72fc57a07c41909eb5895b957fb8394003b85ec932f32b4925b830ce22cae7946a889b28a73fe57997d7604a931844080d9393c31e96917f713689d10c07c028d8f9bd102c7aa9c860e5', 'maxFeePerGas': 53485758643, 'maxPriorityFeePerGas': 1400000000, 'nonce': 73993, 'r': HexBytes('0xba9f79adc7a61c1c074836eea935f2e6f578ef7b9d4abc7f8a1441a5da1f8cd1'), 's': HexBytes('0x51b8f1fe7fd3b12b736f45289eae5136219084c9334a3ae6deb7512d2f40f0d6'), 'to': '0xd90CA9ac986e453CF51d958071D68B82d17a47E6', 'transactionIndex': 51, 'type': '0x2', 'v': 0, 'value': 0}

    signals = Signals({'0xd90CA9ac986e453CF51d958071D68B82d17a47E6': AggregatorInfos('0x0D8775F648430679A709E98d2b0Cb6250d2887EF', ['BAT','USD'])}, [])
    res = signals.tx_filter_and_parsing(tx, 16000000000)
    print(res)


def signals_init_test():
    w3_liq = Web3Liquidation(provider_type='http_ym')
    # reserves = w3_liq.query_markets_list()
    reserves = RESERVES

    ctokens_infos = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens_infos, w3_liq, reserves)

    signals = init_signals(w3_liq, reserves, ctokens_infos)
    print(signals.event_filter_convert())


if __name__ == '__main__':
    # tx_filter_test()
    signals_init_test()
