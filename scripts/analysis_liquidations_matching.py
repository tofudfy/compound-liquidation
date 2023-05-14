import re
import os
import json
import copy
import time

from web3 import Web3
from analysis_utils import unix_to_readable, unix_time, unix_to_readable, write_file, convert_tar_to_pattern, is_hex_string, line_json_parser
from configs.config import P_ALIAS, NETWORK
from configs.utils import json_file_load
from configs.web3_liq import Web3Liquidation

HF_THRESHOLD = P_ALIAS['health_factor_threshold']

# check the ANALYSIS_LOCATION and modify "logs/XXX" everytime running the analysis
DESIRED_REVENUE = 0.01
DEBT_TO_COEVR_DELTA = 0.01
TIME_OFFSET = 0  # 本地接收消息延迟
TIME_OFFSET2 = 0  #

PREFIX = "./"
ANALYSIS_PREF = PREFIX + "outputs/"
LOG_PREFIX = "liquidation_" + NETWORK.lower() + "_v2_"  # "liquidation_"

# used when the log is incomplete
BLANK_LIST = [

]

p2 = re.compile(r'\[(.*?)\]', re.S)
not_matched = {}


def time_in_range(time):
    for ran in BLANK_LIST:
        if unix_time(ran[0]) < float(time) < unix_time(ran[1]):
            return True
    return False


def complex_dict_update(res, new_added):
    for user, debts in new_added.items():
        if res.get(user, None) is None:
            res[user] = debts
        else:
            for debt, times in debts.items():
                if res[user].get(debt, None) is None:
                    res[user][debt] = times
                else:
                    for time, data in times.items():
                        # 合并debt_to_cover相近的清算信息（即上一次清算监听未被清算）
                        # 以debt_to_cover为基准，比revenue更合理
                        old_key = list(res[user][debt].keys())[-1]
                        debt_cover = int(data['repayAmount'])
                        old_debt_cover = int(res[user][debt][old_key]['repayAmount'])
                        if abs(debt_cover - old_debt_cover)/old_debt_cover < DEBT_TO_COEVR_DELTA:
                            res[user][debt][old_key]['revenue'] = data['revenue']
                            res[user][debt][old_key]['repayAmount'] = debt_cover
                            res[user][debt][old_key]['date'] = unix_to_readable(time)
                        else:
                            res[user][debt][time] = data


def read_and_parse_from_folder(path, match_file, targets_line, log_filter):
    res = {}
    files = os.listdir(path)
    files.sort()
    for file in files:
        f = path + file
        if os.path.isdir(f):
            continue

        if not match_file in file:
            continue

        print("read file ", f)
        complex_dict_update(res, read_and_parse(f, targets_line, log_filter))

    return res


def read_and_parse(file, targets, log_filter):
    f = open(file)
    iter_f = iter(f)

    patterns = convert_tar_to_pattern(targets)

    res = {}
    block_num = 0
    for line in iter_f:
        for i in range(len(targets)):
            if line.find(targets[i]) > -1:
                date, block_num, tx_hash, user, debt, debt_cover, collateral_asset, collateral_amount, revenue, params, extral_info = log_filter(line, patterns[i])
                time = unix_time(date)

                if res.get(user, None) is None:
                    res[user] = {}

                if res[user].get(debt, None) is None:
                    res[user][debt] = {}

                # 合并debt_to_cover相近的清算信息（即上一次清算监听未被清算）
                if len(res[user][debt]) != 0:
                    old_key = list(res[user][debt].keys())[-1]
                    old_debt_cover = res[user][debt][old_key]['repayAmount']

                    if abs(debt_cover - old_debt_cover)/old_debt_cover < DEBT_TO_COEVR_DELTA:
                        res[user][debt][old_key]['blockNum'] = block_num
                        res[user][debt][old_key]['txHash'] = tx_hash
                        res[user][debt][old_key]['repayAmount'] = debt_cover
                        res[user][debt][old_key]['colAsset'] = collateral_asset
                        res[user][debt][old_key]['gainedAmount'] = collateral_amount
                        res[user][debt][old_key]['revenue'] = revenue
                        res[user][debt][old_key]['params'] = params
                        res[user][debt][old_key]['date'] = date
                        continue
                
                if len(extral_info) > 0: 
                    extral_info['blockNum'] = block_num
                    extral_info['date'] = date

                res[user][debt][time] = {
                    'blockNum': block_num,
                    'txHash': tx_hash,
                    'borrower': user,
                    'repayAmount': debt_cover,
                    'liquidator': "None",
                    'colAsset': collateral_asset,
                    'gainedAmount': collateral_amount,
                    'revenue': revenue,
                    'params': params,
                    'date': date,
                    'extraInfos': extral_info
                }

    return res


def read_and_parse_second(files, time, target):
    for file in files:
        file = PREFIX + "mine/" + file

        f = open(file)
        iter_f = iter(f)

        target2 = "start message"
        target2_temp_line = ""

        target3 = "start at"
        target3_temp_line = ""

        a = []
        temp_line = ""
        temp_line2 = ""
        temp_line3 = ""
        log_start_time = ""
        for line in iter_f:
            # 找到pending tx触发信号对应target2日志，提取
            if line.find(target2) > -1:
                log_start_time = re.findall(p2, line)[0]
                target2_temp_line = line

            if line.find(target) > -1:
                log_time = re.findall(p2, line)[0]

                # 找到与链上清算时间最接近的触发信号
                if time > log_time:
                    temp_line = line
                    if log_time > log_start_time:
                        temp_line2 = target2_temp_line
                else:
                    time_with_dev = unix_to_readable(time + TIME_OFFSET2)
                    if time_with_dev > log_time:
                        temp_line3 = line
                        continue

                    a.append(temp_line2)
                    a.append(temp_line)
                    a.append(temp_line3)
                    a.append(line)
                    return a

    return "not found"


def read_and_parse_third(files, time, target1, target2):
    a = []
    switch = True
    temp_line_target1_before = ""
    temp_line_target1_after = ""
    temp_line_target2 = ""

    for file in files:
        file = PREFIX + "mine/" + file

        f = open(file)
        iter_f = iter(f)

        for line in iter_f:
            if switch and line.find(target1) > -1:
                log_time = re.findall(p2, line)[0]
                if time > log_time:
                    temp_line_target1_before = line
                else:
                    temp_line_target1_after = line
                    switch = False

            if line.find(target2) > -1:
                log_time = re.findall(p2, line)[0]
                if time > log_time:
                    temp_line_target2 = line
                else:
                    if temp_line_target2 == "":
                        a.append(temp_line_target1_before)
                    else:
                        a.append(temp_line_target2)
                    a.append(line)
                    return a

    if temp_line_target2 == "":
        a.append(temp_line_target1_before)
    else:
        a.append(temp_line_target2)
    a.append(temp_line_target1_after)
    return a


def logs_parser_mine(line, p):
    res_js = line_json_parser(line, p)

    date = re.findall(p2, line)[0].split(".")[0]
    block_num = res_js.get('block_num', 0)  + signal_delay
    tx_hash = ''

    params = res_js['params']
    user = params[0]
    debt_token = res_js['to_addr']
    debt_cover = int(params[1])
    col_token = params[2] 
    col_amount = res_js.get('gainedAmount', 0)

    revenue = res_js['revenue']
    ex = {
        'signalHash': res_js['signal']
    }

    return date, block_num, tx_hash, user, debt_token, debt_cover, col_token, col_amount, revenue, params, ex


def logs_parser_onchain(line, p):
    res_js = line_json_parser(line, p)

    date = res_js['time']
    block_num = res_js['blockNumber']
    tx_hash = res_js['txHash']

    revenue = res_js['revenue']
    # debt_volume = res_js['revenue'][1]
    debt_volume = 0

    params = res_js['params']
    user = params[0]
    debt_token = res_js['debt']
    debt_cover = int(params[1])
    col_token = params[2]
    col_amount = res_js.get('gainedAmount', 0) 
    ex = {}

    return date, block_num, tx_hash, user, debt_token, debt_cover, col_token, col_amount, revenue, params, ex


def compare(actual_res, my_res, included):
    dic = {}
    dic_correct = {}
    for element in included:
        user = element[0]
        debt = element[1]
        my_time = element[2]
        actual_time = element[3]

        actual_debt = int(actual_res[user][debt][actual_time]['repayAmount'])
        my_debt = int(my_res[user][debt][my_time]['repayAmount'])

        delta_debt = (my_debt - actual_debt) / actual_debt
        same_collateral = False
        # for collateral in my_res[user][debt][my_time]['colAsset']:
        #     if collateral == actual_res[user][debt][actual_time]['colAsset']:
        #         same_collateral = True
        if my_res[user][debt][my_time]['colAsset'].lower() == actual_res[user][debt][actual_time]['colAsset']:
            same_collateral = True

        if not same_collateral or abs(delta_debt) > 0.011 or my_time > actual_time:
            if dic.get(user, None) is None:
                dic[user] = {}

            if dic[user].get(debt, None) is None:
                dic[user][debt] = {}

            dic[user][debt][actual_time] = {}
            dic[user][debt][actual_time]['errors'] = []
            dic[user][debt][actual_time]['blockNum'] = actual_res[user][debt][actual_time]['blockNum']
            dic[user][debt][actual_time]['revenue'] = actual_res[user][debt][actual_time]['revenue']
            dic[user][debt][actual_time]['extraInfos'] = my_res[user][debt][my_time]['extraInfos']
        else:
            if dic_correct.get(user, None) is None:
                dic_correct[user] = {}

            if dic_correct[user].get(debt, None) is None:
                dic_correct[user][debt] = {}

            dic_correct[user][debt][actual_time] = {}
            dic_correct[user][debt][actual_time]['my_time'] = my_time
            dic_correct[user][debt][actual_time]['compare'] = {
                'my': actual_res[user][debt][actual_time]['params'],
                'actual': my_res[user][debt][my_time]['params']
            }

        if not same_collateral:
            my_collateral = my_res[user][debt][my_time]['colAsset']
            actual_collateral = actual_res[user][debt][actual_time]['colAsset']

            my_gain_amount = my_res[user][debt][my_time]['gainedAmount'] 
            actual_gain_amount = actual_res[user][debt][actual_time]['gainedAmount']

            dic[user][debt][actual_time]['errors'].append(
                {
                    'is_same_collateral': same_collateral,
                    'compare': {
                        'my': [my_debt, my_collateral, my_gain_amount],
                        'actual': [actual_debt, actual_collateral, actual_gain_amount]
                    }
                }
            )
        elif abs(delta_debt) > 0.011:
            my_block_num = my_res[user][debt][my_time]['blockNum']
            actual_block_num = actual_res[user][debt][actual_time]['blockNum']
            dic[user][debt][actual_time]['errors'].append(
                {
                    'debt deviation': delta_debt, 
                    'compare': {
                        'my': [my_debt, my_block_num], 
                        'actual': [actual_debt, actual_block_num]
                    }
                }
            )
        elif my_time > actual_time:
            dic[user][debt][actual_time]['errors'].append(
                {
                    "compare": {
                        'my': my_time,
                        'actual': actual_time
                    }
                }
            )

    return dic, dic_correct


def find_intersection(actual, my):
    included = []
    not_included = {}
    not_matched = copy.deepcopy(my)
    skip = 0

    for user, debts in actual.items():
        if my.get(user, None) is None:
            for debt, times in debts.items():
                for time, data in times.items():
                    if time_in_range(time):
                        skip += 1
                    else:
                        if not_included.get(user, None) is None:
                            not_included[user] = {}
                        if not_included[user].get(debt, None) is None:
                            not_included[user][debt] = {}
                        not_included[user][debt][time] = data
        else:
            for debt, times in debts.items():
                if my[user].get(debt, None) is None:
                    for time, data in times.items():
                        if time_in_range(time):
                            skip += 1
                        else:
                            if not_included.get(user, None) is None:
                                not_included[user] = {}
                            if not_included[user].get(debt, None) is None:
                                not_included[user][debt] = {}
                            not_included[user][debt][time] = data
                else:
                    right = 0  # initial time
                    for time, data in times.items():
                        left = right
                        right = float(time)
                        target = ""
                        for my_time, my_data in my[user][debt].items():
                            if left + TIME_OFFSET < float(my_time) < right + TIME_OFFSET:  # unix_time(my_time)
                                target = my_time
                                not_matched[user][debt].pop(my_time)

                        if target != "":
                            included.append((user, debt, target, time))

                            if len(not_matched[user][debt]) == 0:
                                not_matched[user].pop(debt)
                        elif time_in_range(time):
                            skip += 1
                        else:
                            if not_included.get(user, None) is None:
                                not_included[user] = {}

                            if not_included[user].get(debt, None) is None:
                                not_included[user][debt] = {}

                            not_included[user][debt][time] = data

                    if len(not_matched[user]) == 0:
                        not_matched.pop(user)

    return not_included, included, not_matched, skip


def map_check(map, keys):
    temp = map
    for key in keys:
        if temp.get(key, None) is None:
            temp[key] = {}
        
        temp = temp[key]


def merge(actual, my):
    merged = {}
    not_matched = copy.deepcopy(my)
    skip = 0

    for user, debts in actual.items():
        if my.get(user, None) is None:
            for debt, times in debts.items():
                for time, data in times.items():
                    if time_in_range(time):
                        skip += 1
                    else:
                        map_check(merged, [user, debt])
                        merged[user][debt][time] = data
                        merged[user][debt][time]['type'] = 'not_include'
        else:
            for debt, times in debts.items():
                if my[user].get(debt, None) is None:
                    for time, data in times.items():
                        if time_in_range(time):
                            skip += 1
                        else:
                            map_check(merged, [user, debt])
                            merged[user][debt][time] = data
                            merged[user][debt][time]['type'] = 'not_include'
                else:
                    right = 0  # initial time
                    for time, data in times.items():
                        left = right
                        right = float(time)
                        target = ""
                        for my_time, my_data in my[user][debt].items():
                            if left + TIME_OFFSET < float(my_time) < right + TIME_OFFSET and (data['blockNum'] - my_data['blockNum']) <= 2:
                                target = my_time
                                not_matched[user][debt].pop(my_time)

                        if target != "":
                            map_check(merged, [user, debt])
                            merged[user][debt][time] = data
                            merged[user][debt][time]['myParams'] = my_data['params'] 
                            merged[user][debt][time]['sigHash'] = my_data['extraInfos']['signalHash'] 
                            merged[user][debt][time]['myBlockNum'] = my_data['extraInfos']['blockNum'] 
                            merged[user][debt][time]['type'] = 'included' 

                            if len(not_matched[user][debt]) == 0:
                                not_matched[user].pop(debt)
                        elif time_in_range(time):
                            skip += 1
                        else:
                            map_check(merged, [user, debt])
                            merged[user][debt][time] = data
                            merged[user][debt][time]['type'] = 'not_include' 

                    if len(not_matched[user]) == 0:
                        not_matched.pop(user)
    
    for user, debts in not_matched.items():
        for debt, times in debts.items():
            for time, data in times.items():
                map_check(merged, [user, debt])
                merged[user][debt][time] = data
                merged[user][debt][time]['type'] = 'unmatched' 

    return merged, skip


def filter_unmatch(unmatched):
    pop_list = []
    for user, debts in unmatched.items():
        for debt, times in debts.items():
            for time, data in times.items():
                if data['revenue'] <= DESIRED_REVENUE:
                    pop_list.append((user, debt, time))

    for params in pop_list:
        unmatched[params[0]][params[1]].pop(params[2])

        if len(unmatched[params[0]][params[1]]) == 0:
            unmatched[params[0]].pop(params[1])

        if len(unmatched[params[0]]) == 0:
            unmatched.pop(params[0])


def stat_elements(dic):
    c = 0
    for user, debts in dic.items():
        for debt, times in debts.items():
            c += len(times)
    return c


def stat_log_elements(dic):
    c = 0
    for user, debts in dic.items():
        c += len(debts)
    return c


def main():
    actual = read_and_parse_from_folder(PREFIX, "liquidations_onchain_20230508", ["liquidationCalls: "], logs_parser_onchain)
    write_file(actual, ANALYSIS_PREF + "analysis_raw_actual.json")

    my_res = read_and_parse_from_folder(PREFIX, "liquidation_bsc_compound_venus_20230508", ["liquidation start: ", "liquidation abandoned: "], logs_parser_mine)
    write_file(my_res, ANALYSIS_PREF + "analysis_raw_my.json")

    # my_res = json_file_load(ANALYSIS_PREF + "analysis_raw_my.json")
    # actual = json_file_load(ANALYSIS_PREF + "analysis_raw_actual.json")

    # Step2:
    not_include, included, unmatch, skipped = find_intersection(actual, my_res)
    write_file(not_include, ANALYSIS_PREF + "analysis_raw_not_include.json")

    merged, _ = merge(actual, my_res)
    write_file(merged, ANALYSIS_PREF + "analysis_raw_full.json")

    filter_unmatch(unmatch)
    print(f"unmatch with revenue filt {stat_log_elements(unmatch)}")
    write_file(unmatch, ANALYSIS_PREF + "analysis_raw_unmatch.json")

    total = stat_elements(actual)
    print(f"onchain_total {total}: included {100*len(included)/total}%, not include {100*stat_elements(not_include)/total}%, skipped {100*skipped/total}%")

    include_error, include_correct = compare(actual, my_res, included)
    write_file(include_error, ANALYSIS_PREF + "analysis_include_with_error.json")
    write_file(include_correct, ANALYSIS_PREF + "analysis_include_correct.json")
    print(f"local_listened {len(included)}: correct {100*stat_elements(include_correct)/len(included)}%, with error {100*stat_elements(include_error)/len(included)}%")


def second():
    not_include = json_file_load(ANALYSIS_PREF + "analysis_raw_not_include.json")

    result = {}
    for user, debts in not_include.items():
        index = 0
        for debt, times in debts.items():
            for time, data in times.items():
                index += 1
                key = time.split(" ")[0]
                # files = LOG_MAPPING[key]  # unused after 20221219 (included)
                files = [LOG_PREFIX + key.replace('-', '') + ".log"]
                # target = "DEBUG: user " + user.strip("\'") + " health factor"  # unused after 20230116 (included)
                target = f'hf calculation result: {{"user":{user}'
                res = read_and_parse_second(files, time, target)

                if result.get(user, None) is None:
                    result[user] = {}

                if result[user].get(index, None) is None:
                    result[user][index] = {}

                result[user][index]['actual_time'] = time
                result[user][index]['actual_blocknum'] = data['block_num']
                result[user][index]['debug_logs'] = res
                result[user][index]['actual_revenue'] = data['revenue']
                result[user][index]['actual_params'] = data['params']

    write_file(result, ANALYSIS_PREF + "analysis_not_include_details.json")


def third():
    include_with_error = json_file_load(ANALYSIS_PREF + "analysis_include_with_error.json")

    result = {}
    for user, debts in include_with_error.items():
        index = 0
        for debt, times in debts.items():
            for time, data in times.items():
                index += 1
                key = time.split(" ")[0]
                # files = LOG_MAPPING[key] # unused after 20221219 (included)
                files = [LOG_PREFIX + key.strip('-') + ".log"]
                target1 = "DEBUG: user " + user.strip("\'") + " health factor"
                target2 = "user " + user.strip("\'") + ", target debt"

                res = read_and_parse_third(files, time, target1, target2)

                if result.get(user, None) is None:
                    result[user] = {}

                if result[user].get(index, None) is None:
                    result[user][index] = {}

                result[user][index]['actual_time'] = time
                result[user][index]['errors'] = data['errors']
                result[user][index]['debug_logs'] = res
                result[user][index]['actual_params'] = data['params']
                result[user][index]['actual_revenue'] = data['revenue']

    write_file(result, ANALYSIS_PREF + "analysis_include_with_error_details.json")
    

def fourth():
    w3_liq = Web3Liquidation('http_ym')
    unmathed = json_file_load(ANALYSIS_PREF + "analysis_raw_unmatch.json")
    unmathed_detailed = {}
    
    counter = 0
    error = 0
    for user, debts in unmathed.items():
        for debt, times in debts.items():
            for time, data in times.items():
                counter += 1
                if data['revenue'] < 5 * 10**18:
                    continue

                if unmathed_detailed.get(user, None) is None:
                    unmathed_detailed[user] = {}

                if unmathed_detailed[user].get(debt, None) is None:
                    unmathed_detailed[user][debt] = {}

                unmathed_detailed[user][debt][time] = {}
                unmathed_detailed[user][debt][time]['revenue'] = data['revenue']

                # signal 1: pending tx, already +2
                # signal 2: every block
                block_num = data['blockNum']

                # we only consider the affect of hf triggered by signal
                # the affect of hf by protocol parameters are not consedered
                # thus, the hf will changed when the signal is on-chain, thus +0 should > 1 and +1/+2 should <1
                res_before = w3_liq.is_belowe_health_factor(user, identifier=block_num-1)
                res_after = w3_liq.is_belowe_health_factor(user, identifier=block_num)
                res_after2 = w3_liq.is_belowe_health_factor(user, identifier=block_num+1)
 
                unmathed_detailed[user][debt][time]['blockNum'] = block_num
                unmathed_detailed[user][debt][time]['params'] = data['params']
                unmathed_detailed[user][debt][time]['date'] = data.get('date', None)
                if not res_before and (res_after or res_after2):
                    pass
                elif not res_before and not res_after and not res_after2:
                    error += 1
                    unmathed_detailed[user][debt][time]['error'] = [
                        "invalid liquidation",
                        {
                            block_num-1: res_before,
                            block_num: res_after,
                            block_num+1: res_after2
                        }
                    ]
                else:
                    unmathed_detailed[user][debt][time]['error'] = [
                        "not found at first place",
                        {
                            block_num-1: res_before,
                            block_num: res_after,
                            block_num+1: res_after2
                        }
                    ]

    print(f"unmatch error rate: {round(100*error/counter,2)}%")
    write_file(unmathed_detailed, ANALYSIS_PREF + "analysis_unmatch_with_details.json")


if __name__ == '__main__':
    if NETWORK == 'Polygon':
        signal_delay = 2
    elif NETWORK == 'BSC':
        signal_delay = 1

    main()
    # second()
    fourth()
