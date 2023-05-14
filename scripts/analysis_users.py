import re

from analysis_utils import data_plot_hist, draw_histogram, line_json_parser
from configs.web3_liq import Web3Liquidation
from configs.users import reload_states, sync_states
from configs.tokens import complete_ctokens_configs_info, complete_ctokens_risks
from configs.signals import init_signals, complete_ctokens_price_info
from configs.comet import init_comet_configs
from configs.config import RESERVES

DESIRE_PROF = 1


class User:
    def __init__(self, name, hf, v_col, v_debt):
        self.name = name
        self.hf = hf
        self.v_col = v_col
        self.v_debt = v_debt


def read_and_parse(file):
    f = open(file)
    iter_f = iter(f)

    targets = [
        "=============================== ",
        "hf calculation result: "
    ]

    patterns = []
    for s in targets:
        patterns.append(re.compile('.*' + s + '(.*)', re.S))

    users_dict = {}
    reserve = ""
    for line in iter_f:
        if line.find(targets[0]) > -1:
            res_js = line_json_parser(line, patterns[0])

            total_user = res_js.get('total_users', None)
            if total_user is not None:
                continue

            reserve = res_js.get('aggregator', None)
            if reserve is None:
                continue

            if users_dict.get(reserve, None) is None:
                users_dict[reserve] = {}

        if line.find(targets[1]) > -1:
            res_js = line_json_parser(line, patterns[1])

            user = res_js['user']
            hf = res_js['healthFactor']
            col_eth = res_js['sumCollateral']/10**18
            debt_eth = res_js['sumBorrow']/10**18
            users_dict[reserve][user] = User(user, hf, col_eth, debt_eth)

    return users_dict


def main():
    # reload users and token infos and sync to latest block
    # w3_liq = Web3Liquidation(provider_type='http3')
    w3_liq = Web3Liquidation()
    reserves_init = RESERVES # w3_liq.query_markets_list()
    states = reload_states(reserves_init)
    # sync_states(states, w3_liq, reserves_init)
    identifier = states.last_update

    complete_ctokens_configs_info(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_risks(states.ctokens, w3_liq, reserves_init)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_init)
    comet = init_comet_configs(w3_liq, reserves_init)
    signals = init_signals(w3_liq, reserves_init, states.ctokens)

    users_all = list(states.users_states.keys())
    print(f'=============================== {{ "total_users": {len(users_all)}, "height":{identifier}}}')
    
    symbols = {}
    for aggr in list(signals.signal_token_map.keys()):
        tokens_addr, _ = signals.get_tokens_from_aggr(aggr)
        users = states.users_filtering(tokens_addr)
        # print(f'=============================== {{"aggregator": "{aggr}", "users":{len(users)}}}')
        
        symbol = ""
        aggr_infos = signals.signal_token_map[aggr]
        for token_infos in aggr_infos:
            symbol += token_infos.pair_symbols[0]
        symbols[aggr] = symbol

        # for usr in users:
        #     calculate_health_factor(usr, states.users_states[usr].reserves, states.ctokens, comet)

        # write_health_factor(results)
        # states.cache()
    
    print(symbols)


def process():
    file_path = "./analysis_users.log"
    results, reserves, total_user = read_and_parse(file_path)

    res = [[] for j in range(6)]
    duplicate = {}
    for reserve, users in results.items():
        count_lst1 = [0 for j in range(6)]
        count_lst2 = [0 for j in range(6)]
        hist = []
        for k, data in users.items():
            duplicate[k] = duplicate.get(k, 0) + 1
            if duplicate[k] != 1:
                continue

            hf = data.hf
            if hf > 1.1:
                index = 0
            elif hf > 1.01:
                index = 1
            elif hf > 1.0:
                index = 2
            elif hf > 0.9:
                index = 3
            elif hf > 0.00001:
                index = 4
            else:
                index = 5

            volume = data.v_debt
            if volume < DESIRE_PROF:
                count_lst1[index] += 1
                continue
            else:
                count_lst2[index] += 1
                res[index].append(volume)

                if hf < 2:
                    hist.append(hf)

        labels = [
            f"debt volume < {DESIRE_PROF}",
            f"debt volume > {DESIRE_PROF}"
        ]
        draw_histogram(count_lst1, count_lst2, f"Reserve {symbols[reserve]}, Total user {len(users)} \n Health factor distribution", labels)
        data_plot_hist(hist, f"Reserve {symbols[reserve]}, Total user {len(users)} \n Health factor distribution", 0)


if __name__ == '__main__':
    main()
    # process()

