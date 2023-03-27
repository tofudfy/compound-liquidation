from typing import Dict, List
from web3 import Web3

from configs.config import ADDRESS_ZERO, S_ALIAS, ST_ALIAS
from configs.web3_liq import Web3Liquidation
from configs.tokens import CtokenInfos, new_ctokens_infos, complete_ctokens_configs_info

from configs.config import RESERVES


class AggregatorInfos(object):
    def __init__(self, token: str, pair_symbols: List):
        self.token = token
        self.pair_symbols = pair_symbols


class Signals(object):
    def __init__(self, source_token_map: Dict[str, AggregatorInfos], aggregator_source_filter: List):
        self.signal_token_map = source_token_map
        self.signals_event_filter = aggregator_source_filter
        self.signals_epoch: Dict[str, int] = {}

    def get_token_from_aggr(self, signal):
        signal = Web3.toChecksumAddress(signal)
        return self.signal_token_map[signal]


def init_signals(w3_liq: Web3Liquidation, reserves: List, ctokens: Dict[str, CtokenInfos]):
    source_token_dic, aggregator_source_filter = query_reserves_aggregator(w3_liq, reserves, ctokens)

    source_token_dic.update(ST_ALIAS)
    aggregator_source_filter.extend(S_ALIAS)
    return Signals(source_token_dic, aggregator_source_filter)


# convert 'A / ETH' to [A,ETH]
def aggregator_description_parse(descr) -> List:
    return descr.replace(" ", "").split("/")


def query_reserves_aggregator(w3_liq: Web3Liquidation, reserves: List, ctokens: Dict[str, CtokenInfos]) -> (Dict[str, AggregatorInfos], List):
    dic = {}
    aggregator_filter = []

    for reserve in reserves:
        source = ctokens[reserve].configs.reporter
        if source == ADDRESS_ZERO:
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
        dic[aggregator] = AggregatorInfos(reserve, aggregator_description_parse(descr))

        aggregator_filter.append(
            {'to': aggregator}
        )

    return dic, aggregator_filter


if __name__ == '__main__':
    w3_liq = Web3Liquidation(provider_type='http')
    # reserves = w3_liq.query_markets_list()
    reserves = RESERVES

    ctokens_infos = new_ctokens_infos(reserves)
    complete_ctokens_configs_info(ctokens_infos, w3_liq, reserves)

    signals = init_signals(w3_liq, reserves, ctokens_infos)
    print(signals)
