import json
import time

from typing import Dict, List, Tuple
from web3 import Web3
from web3.types import LogReceipt
from hexbytes import HexBytes

from eth_abi import decode
from configs.config import NETWORK, SELECTOR, INTVL, ADDRESS_ZERO, P_ALIAS, S_ALIAS, ST_ALIAS
from configs.web3_liq import Web3Liquidation
from configs.tokens import CtokenConfigs, CtokenInfos, new_ctokens_infos
from configs.protocol import Web3CompoundVenues, Web3CompoundV3, complete_ctokens_configs_info

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
    def __init__(self, token: str, pair_symbols: List, price_decimals: int):
        self.token = token
        self.pair_symbols = pair_symbols
        self.price_decimals = price_decimals


class Signals(object):
    def __init__(self, source_token_map: Dict[str, List[AggregatorInfos]], aggregator_source_filter: List):
        # signal is in lower case
        self.signal_token_map = source_token_map
        self.token_signal_map = self.signal_token_inverse() 
        self.signals_event_filter_light = aggregator_source_filter
        self.signals_epoch: Dict[str, int] = {}

    def get_tokens_from_aggr(self, signal) -> Tuple[List[AggregatorInfos], str]:
        tokens_infos = self.signal_token_map[signal]

        tokens_addr = []
        for inf in tokens_infos:
            tokens_addr.append(inf.token)
        return tokens_addr, signal

    def get_tokens_from_aggr_index(self, index) -> Tuple[List, str]:
        aggr_lst = list(self.signal_token_map.keys())
        index_mod = index % len(aggr_lst)
        aggr = aggr_lst[index_mod]
        
        return self.get_tokens_from_aggr(aggr)

    def signal_token_inverse(self):
        token_signal_map = {}
        for k, datas in self.signal_token_map.items():
            for data in datas:
                token_addr = data.token
                token_signal_map[token_addr] = k
        return token_signal_map
    
    def event_filter_convert(self) -> List:
        event_filter = []
        for data in self.signals_event_filter_light:
            for k, v in data.items():
                event_filter.append(v)
            
        return event_filter

    # different signal may implement different parser
    def tx_filter_and_parsing(self, tx_attribute_dict, gas_price):
        # Due to our light node design, 'to' is in lower cases
        contract_addr = tx_attribute_dict['to']
        input_str = tx_attribute_dict['input']
        call_data_bin = bytes.fromhex(input_str[2:])

        if len(call_data_bin) <= 4:
            raise Exception("call data error")

        method_signature = call_data_bin[:4]
        if method_signature != TRANSMIT_FUNC_SIG:
            raise Exception("unknown function signature")

        if tx_attribute_dict['gasPrice'] is not None:
            p = tx_attribute_dict['gasPrice']
        else:
            p = tx_attribute_dict['maxFeePerGas']
        signal_gasprice = int(p, 16)
        local_gasprice = gas_price
        if 0.9*local_gasprice > signal_gasprice:
            raise Exception(f'signal price too low: {{"local":{local_gasprice}, "signal":{signal_gasprice}}}')

        # args = decode(TRANSMIT_ARG_TYPES1, call_data_bin[4:])
        # args = decode(TRANSMIT_ARG_TYPES2, args[0])
        data = call_data_bin[4:]
        offset = int.from_bytes(data[:32], byteorder='big') + 32

        raw_report_ctx = data[offset:offset+32]
        # print(raw_report_ctx.hex())

        signal_epoch = int(raw_report_ctx[-5:].hex(), 16)
        # signals_epoch is only query and update here
        # thus the key of signals_epoch(map) is align
        local_epoch = self.signals_epoch.get(contract_addr, 0)
        if local_epoch > signal_epoch:
            raise Exception(f'signal stale report: {{"local":{local_epoch}, "signal":{signal_epoch}}}')
        else:
            self.signals_epoch[contract_addr] = signal_epoch

        array_length = int.from_bytes(data[offset+32*3:offset+32*4], byteorder='big')
        offset_next = offset+32*4
        array_args = []
        for _ in range(array_length):
            array_args.append(int.from_bytes(data[offset_next:offset_next+32], byteorder='big'))
            # print(data[offset_next:offset_next+32].hex())
            offset_next += 32
        price = array_args[len(array_args)//2]

        return contract_addr, price

    def no_name(self, aggregator, price) -> Tuple[List, str]:
        r = []
        # signal_token_map is init at line 145
        # which is initiated by `query_reserves_aggregator`
        aggr_infos = self.signal_token_map[aggregator]  # more safe implementation: aggregator.lower() 
        for aggr_info in aggr_infos: 
            token_addr = aggr_info.token
            pair_symbols = aggr_info.pair_symbols
            feed_decimals = aggr_info.price_decimals

            if pair_symbols[1] == P_ALIAS['base_currency']:
                r.append((token_addr, price, feed_decimals))
            # todo: elif
            else:
                raise Exception("unrecognize aggregators")
            
        return r, aggregator


class SignalsCompV2(Signals):
    def __init__(self, source_token_map: Dict[str, List[AggregatorInfos]], aggregator_source_filter: List):
        super().__init__(source_token_map, aggregator_source_filter)
    
    def tx_filter_and_parsing(self, tx_attribute_dict, gas_price):
        contract_addr, price = super().tx_filter_and_parsing(tx_attribute_dict, gas_price)
        if not self.is_within_anchor(price):
            raise Exception(f'signal price not in anchor: {{"price":{price}, "anchor":{0}}}')
        
        return contract_addr, price 

    def get_oracle_price(self, price: int, feed_decimals: int, cfg: CtokenConfigs):
        multiplier = cfg.reporter_multiplier
        base_units = cfg.base_units
        return int(self.price_scale(price, base_units, multiplier))

    def gen_oracle_params(self, feed_decimals: int, cfg: CtokenConfigs):
        multiplier = cfg.reporter_multiplier
        base_units = cfg.base_units
        return (base_units, multiplier)
    
    def is_within_anchor(self, price):
        return True

    def price_scale(self, price: int, base_units: int, rep_multiplier: int) -> str:
        delta = 30+rep_multiplier-base_units*2
        if delta < 0:
            delta = 0
        
        return str(price) + ("").zfill(delta)

    def price_scale_inverse(self, price: int, base_units: int, rep_multiplier: int) -> int:
        delta = 30+rep_multiplier-base_units*2
        if delta < 0:
            delta = 0

        return price / 10**delta


class SignalsCompVenues(Signals):
    def __init__(self, source_token_map: Dict[str, List[AggregatorInfos]], aggregator_source_filter: List):
        super().__init__(source_token_map, aggregator_source_filter)

    def get_oracle_price(self, price: int, feed_decimals: int, cfg: CtokenConfigs):
        decimals_ua = cfg.underlying_decimals
        return int(self.price_scale(price, decimals_ua, feed_decimals))

    def gen_oracle_params(self, feed_decimals: int, cfg: CtokenConfigs):
        decimals_ua = cfg.underlying_decimals
        return (decimals_ua, feed_decimals)

    # introduced by compound protocol
    def price_scale(self, price: int, underlying_decimals: int, feed_decimals: int) -> str:
        delta_underlying = 18-underlying_decimals
        if delta_underlying < 0:
            delta_underlying = 0

        delta_feed = 18-feed_decimals
        if delta_feed < 0:
            delta_feed = 0
        
        return str(price) + ("").zfill(delta_underlying) + ("").zfill(delta_feed)

    def price_scale_inverse(self, price: int, underlying_decimals: int, feed_decimals: int) -> int:
        delta_underlying = 18-underlying_decimals
        if delta_underlying < 0:
            delta_underlying = 0

        delta_feed = 18-feed_decimals
        if delta_feed < 0:
            delta_feed = 0
        return price / 10**delta_underlying / 10**feed_decimals


# todo
class Oracle(object):
    def __init__(self, signals: Signals) -> None:
        pass


def gen_signals_filter(signals: Signals):
    filt = json.loads(COMPOUND_V3_SIGNALS_FILTER_TEMP)
    filt['address'] = signals.event_filter_convert()
    return filt


def init_signals(w3_liq: Web3CompoundVenues, reserves: List, ctokens: Dict[str, CtokenInfos]):
    source_token_dic, aggregator_source_filter = query_reserves_aggregator(w3_liq, reserves, ctokens)

    source_token_dic.update(ST_ALIAS)
    aggregator_source_filter.extend(S_ALIAS)

    if NETWORK == "Ethereum" and SELECTOR == 'v2':
        return SignalsCompV2(source_token_dic, aggregator_source_filter)
    if NETWORK == "BSC" and SELECTOR == 'venus':
        return SignalsCompVenues(source_token_dic, aggregator_source_filter) 
    else:
        return Signals(source_token_dic, aggregator_source_filter)


# convert 'A / ETH' to [A,ETH]
def aggregator_description_parse(descr) -> List:
    return descr.replace(" ", "").split("/")


def query_reserves_aggregator(w3_liq: Web3CompoundVenues, reserves: List, ctokens: Dict[str, CtokenInfos]) -> Tuple[Dict[str, List[AggregatorInfos]], List]:
    dic = {}
    aggregator_filter = []

    for reserve in reserves:
        source = ctokens[reserve].configs.reporter
        if source == ADDRESS_ZERO:
            print(f'no source: {reserve}')
            continue

        aggregator = w3_liq.query_aggregator(source)
        aggregator_offchain = w3_liq.gen_aggregator(aggregator)
        descr = aggregator_offchain.functions.description().call()
        price_decimals = aggregator_offchain.functions.decimals().call() 
        time.sleep(0.01)

        aggr_lower = aggregator.lower()
        if dic.get(aggr_lower, None) is None:
            dic[aggr_lower] = []
        
        # to reduce the key convertion in compound
        dic[aggr_lower].append(AggregatorInfos(reserve, aggregator_description_parse(descr), price_decimals))
        # print(descr)

        aggregator_filter.append(
            {'to': aggregator}
        )

    return dic, aggregator_filter


def new_ctoken_price(price=0, last_update=0):
    return CtokenPrice(price, last_update)


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
    
    # confirmed by the events
    def confirm(self, log: LogReceipt, scale_func, args):
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

            # todo: patch
            args = (answer,) + args
            new_price = int(scale_func(*args))
            # raw_report_context = args_data[4]
            self.price_current = new_price
            self.is_comfired = True 


def init_ctoken_price(w3_comp: Web3CompoundVenues, ctoken_addr, identifier="latest") -> CtokenPrice:
    price_oracle = w3_comp.gen_price_oracle()
    # current_price = price_oracle.functions.price(symbol).call()  # todo: how to get symbol?
    current_price = price_oracle.functions.getUnderlyingPrice(ctoken_addr).call(block_identifier=identifier)
    return CtokenPrice(current_price, int(time.time()))


def complete_ctokens_price_info(obj: Dict[str, CtokenInfos], w3_liq: Web3Liquidation, reserves: List, identifier="latest"):
    for ctoken_addr in reserves:
        # update by pending tx
        ctoken_price = init_ctoken_price(w3_liq, ctoken_addr, identifier)
        obj[ctoken_addr].price = ctoken_price
        print(ctoken_addr, ctoken_price.price_current)
        time.sleep(0.01)


def tx_filter_test():
    """
    # https://etherscan.io/tx/0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375
    w3_liq = Web3Liquidation('http')
    tx = w3_liq.w3.eth.get_transaction("0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375")
    """
    # tx = {'blockHash': HexBytes('0x4d7001877d2c9a69b85b1f5ca37168f0494c3ec67dc2d90a4f4d5a6037ff131b'), 'blockNumber': 16903768, 'hash': HexBytes('0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375'), 'accessList': [], 'chainId': '0x1', 'from': '0xCF4Be57aA078Dc7568C631BE7A73adc1cdA992F8', 'gas': 740000, 'gasPrice': 16907912669, 'input': '0xc9807539000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000003200000000000000000000000000000000000000000000000000000000000000400010000010001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002800000000000000000000000f4f5545633e09805a78067ed5d8df24200050398020e05080003020c01070a040b090d0f060000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000167909a000000000000000000000000000000000000000000000000000000000167b1d8000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167bb3e000000000000000000000000000000000000000000000000000000000167bfdf000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cef6000000000000000000000000000000000000000000000000000000000167f79d000000000000000000000000000000000000000000000000000000000167fa9f00000000000000000000000000000000000000000000000000000000016820f3000000000000000000000000000000000000000000000000000000000168286c0000000000000000000000000000000000000000000000000000000000000006372bffca6271a89560dab24d3a05573b383677163783dd1353d93e1ce22169124702dddfe2697f1df818821bdc4c01e391f935ee1e29fda25d5c47940b0a058430dd021f694931840b458c82782b4e45ab536ffa73900907af4bfadd07ddf85cf8ee62ddd598afd656c27656df014730e578dd635a30e59e10ac79467e743fe8b437ec30d8f3c28dbc6b69ff7e00f6f87137a7916e605b65f14a1516de588da75ef78a22c74d7dea5c0ee1baa116773f3ecd3e244b07a5df15f3506b5d727d6b00000000000000000000000000000000000000000000000000000000000000061d1b72ec1efdd79e8fa8cac54081209cb5eeff9b7994157214004bd5dfa286234e2d074b27444faf986b114dd748cba19fbebc008911c90648dd1ab9c99be77e4e6fc84953d7a1b6f76301e1ac0fb44eae0d3d93124760a32f676509c1a021057b0e6af01fc20ee9ce2810296a3230b298dcb459623d72fc57a07c41909eb5895b957fb8394003b85ec932f32b4925b830ce22cae7946a889b28a73fe57997d7604a931844080d9393c31e96917f713689d10c07c028d8f9bd102c7aa9c860e5', 'maxFeePerGas': 53485758643, 'maxPriorityFeePerGas': 1400000000, 'nonce': 73993, 'r': HexBytes('0xba9f79adc7a61c1c074836eea935f2e6f578ef7b9d4abc7f8a1441a5da1f8cd1'), 's': HexBytes('0x51b8f1fe7fd3b12b736f45289eae5136219084c9334a3ae6deb7512d2f40f0d6'), 'to': '0xd90CA9ac986e453CF51d958071D68B82d17a47E6', 'transactionIndex': 51, 'type': '0x2', 'v': 0, 'value': 0}
    # signals = Signals({'0xd90CA9ac986e453CF51d958071D68B82d17a47E6': [AggregatorInfos('0x0D8775F648430679A709E98d2b0Cb6250d2887EF', ['BAT','USD'])]}, [])

    # case1: BSC
    # tx = {'type': '0x0', 'nonce': '0xb4225', 'gasPrice': '0x12a05f200', 'maxPriorityFeePerGas': None, 'maxFeePerGas': None, 'gas': '0x7a120', 'value': '0x0', 'input': '0xc980753900000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000320000000000000000000000000000000000000000000000000000000000000040000010100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280000000000000000000000002e9bed4b8ee20134054a7b8b22d10850003e2a80200090805040c0307010d0b0f0e02060a0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000074374a29e000000000000000000000000000000000000000000000000000000074398a58e0000000000000000000000000000000000000000000000000000000743aa38000000000000000000000000000000000000000000000000000000000743aa38000000000000000000000000000000000000000000000000000000000743b4d2d80000000000000000000000000000000000000000000000000000000743d8d4f00000000000000000000000000000000000000000000000000000000743d984980000000000000000000000000000000000000000000000000000000743f683400000000000000000000000000000000000000000000000000000000743f683400000000000000000000000000000000000000000000000000000000743f6834000000000000000000000000000000000000000000000000000000007441d1e10000000000000000000000000000000000000000000000000000000074426eb590000000000000000000000000000000000000000000000000000000744338470000000000000000000000000000000000000000000000000000000074444f16000000000000000000000000000000000000000000000000000000007448fbb440000000000000000000000000000000000000000000000000000000744cc07680000000000000000000000000000000000000000000000000000000000000006c55962b0e49430c45849abf315de3287b1b73f0597ee56ec9a9ca4c7e74300dc6880af8ba17485a1d8ee6eff1c7b9a1d0ff1e9fc2371990df65f8cd3fd02becee090bb520f80575070d0cef65b726885d0056e34b2711ad1a1f978e4d4a3a9bb8bd1a152771e1ef7e01d44af23684488ad4983d867481d6e4970495da86b15be813a649848461e74377a60205905245837324fea7a07288b02dea02e9971a79505c4449011d5bf7b11d63c03db51762a58f0dd0a6065a247d25dc3045354652e00000000000000000000000000000000000000000000000000000000000000066ed930b3bbce2fb9fd9a6164ce14ef439b5b0e0b7570a6ad89452f6d2bbbb7ea10781ac8cfee44e9be6d8926536ca642ba1ddff32fc55abfafe2a10967393b565669f3f3bd627b493d9b07ddca3abbbb223f18fc0060d6cfbeee3de66051b9f42fb482393d79ab4d3150423255adfda243e1b72006e9a324dc90774bb12edd9d43180c06934ff044dc57b59d5f020cecee1751d9cc15a64b822a8391f09d94b7575a7a24d7a2cc7756df629115238b5db6ea5047980121220a4672c15878a780', 'v': '0x94', 'r': '0x93dfbdd1d4a418da0c34791c53de219e7eda2dd0fc8278e74fbc46b1858b95d0', 's': '0x181a6ac6eac4bbba1a4a906a6a0020df6fc893358347ee8817d46f5683252428', 'to': '0x137924d7c36816e0dcaf016eb617cc2c92c05782', 'hash': '0x0f8481a96776b00a67697083a84bcc5fc7aaad50066c3a772275168fe0e35526', 'from': '0xed3a0ac63d7e48399d05d9a25925e8fcb0cd98d0'}
    # signals = Signals({'0x137924D7C36816E0DcAF016eB617Cc2C92C05782': [AggregatorInfos('0xB8c77482e45F1F44dE1745F52C74426C631bDD52', ['BNB','USD'], 8)]}, [])
    
    # case2: Ethereum
    tx = {'type': '0x2', 'nonce': '0x18e8d', 'gasPrice': None, 'maxPriorityFeePerGas': '0x77359400', 'maxFeePerGas': '0xb48f5f795', 'gas': '0xb4aa0', 'value': '0x0', 'input': '0xc9807539000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000003800000000000000000000000000000000000000000000000000000000000000480000101000001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002e00000000000000000000000240f473feb0e1acd5898d250d7a0a1f30000575f040b0c0007100803121104060a050d0e0f02010900000000000000000000000000000000000000000000000000000000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000130000000000000000000000000000000000000000000000000000009a835ec6300000000000000000000000000000000000000000000000000000009a835f3b600000000000000000000000000000000000000000000000000000009a83add0900000000000000000000000000000000000000000000000000000009a8444ddcb0000000000000000000000000000000000000000000000000000009a8a27e6e90000000000000000000000000000000000000000000000000000009a8ab60bf00000000000000000000000000000000000000000000000000000009a8ab60bf00000000000000000000000000000000000000000000000000000009a8b512c380000000000000000000000000000000000000000000000000000009a8ef1741e0000000000000000000000000000000000000000000000000000009a9129716b0000000000000000000000000000000000000000000000000000009a9772eae90000000000000000000000000000000000000000000000000000009a9772eae90000000000000000000000000000000000000000000000000000009a9d8943ef0000000000000000000000000000000000000000000000000000009a9d98243e0000000000000000000000000000000000000000000000000000009a9d98243e0000000000000000000000000000000000000000000000000000009a9ed93a800000000000000000000000000000000000000000000000000000009a9ed93a800000000000000000000000000000000000000000000000000000009aa51dc8200000000000000000000000000000000000000000000000000000009aa51dc8200000000000000000000000000000000000000000000000000000000000000007ee7e019daf7b448ae5b7049373739ffa792b6fd8175e48c6ce921cba646d01557befb88303314e3ac682856e811b58dd3f25c7c6c21ff7d95df0469e3ddc7f10b74d748ba510efff7376aaafa5a8b04b58cf3e5869a3b8f2368571c4e83f53bd111d995ad47b01860c04ecf985f95a51ed1c38f9bbc83290d8d5b6de6f19b9a00edc76ad9788ded10cf472b10a11f744d802047bd7f5cab0f49a2af0ee0e11ecd16af715cf061840e3b89c4c2e40e7792f7bfbc308b90c52b7f6fe9ff86171af485a58757b95461a0be383ba1f9908d8f23a27135529d308c3fdb138f06f7285000000000000000000000000000000000000000000000000000000000000000767f1770e1d61ff28f0127baf84bfcc6e7074ca90e787eb19474027293de690291f7a0ecc1b3edebf8fcde3634820af3dfdd3b7782721f380cd8600c4a9cf038d130f753e15b3ab1f0075740f2f6e3a893df5d3f3b4244f5ac379babedf613a7b09361e3997951987de30e4973f16e8b2df922363b19868a9a210a432f34e91ca7a6bde2a1ba0545043472fda4d862bd11cc1ac2b3a1e42ea60d74fe104508e1511d9e288fe513bf7ef1b5df35eb56ca4d0a193400d1a556ae6d1b0f8cf98051365fa556704842c01e5b783a39504c9cfc6a3d30a8ceadfc7c54f53a96e64bb36', 'v': '0x0', 'r': '0x622050e92a94a6dddf452a21135e00ecba3b7d49ea6e10112ecc146620151e8c', 's': '0x459e05e28e92595524416af8303c831db90be2a17cb184bca3c999d7741beefd', 'to': '0xcac109af977ac94929a5dd37ed8af763bad78151', 'chainId': '0x1', 'accessList': [], 'hash': '0xcf6f345dedc22cd1f9c539617085a706077eddb1d7895662fef0bf9c7983fc4e', 'from': '0xcc29be4ca92d4ecc43c8451fba94c200b83991f6'}
    signals = Signals({'0xcac109af977ac94929a5dd37ed8af763bad78151': [AggregatorInfos('0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e', ['YFI','USD'], 8)]}, [])

    res = signals.tx_filter_and_parsing(tx, 0)
    print(res)


def signals_init_test():
    w3_liq = Web3CompoundVenues('http2')
    # w3_liq = Web3CompoundV3()

    # reserves = w3_liq.query_markets_list()
    reserves = RESERVES

    ctokens_infos = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens_infos, w3_liq, reserves)

    signals = init_signals(w3_liq, reserves, ctokens_infos)

    # test1
    # print(signals.event_filter_convert())

    # test2
    dic = {}
    for aggr, tokens_list in signals.signal_token_map.items():
        for info in tokens_list:
            ctoken_addr = info.token
            dic[aggr] = ctoken_addr
    print(dic) 


def prices_setted_manually(w3_liq: Web3Liquidation, reserves: List):
    price_oracle = w3_liq.gen_price_oracle()
    res = {}
    for reserve in reserves:
        price = price_oracle.functions.assetPrices(reserve).call()
        res[reserve] = price

    return res


def prices_setted_manually_test(): 
    w3_liq = Web3CompoundVenues()
    reserves = RESERVES
    print(prices_setted_manually(w3_liq, reserves))


if __name__ == '__main__':
    # tx_filter_test()
    signals_init_test()
    # prices_setted_manually_test()
