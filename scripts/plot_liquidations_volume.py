import json
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from datetime import datetime
from web3 import Web3
from configs.utils import json_file_load

from scripts.analysis_liquidations_matching import ANALYSIS_PREF
from scripts.analysis_constant import DECIMALS, PRICES

def volum_calculation(data, start_time, end_time, prices, decimals, has_specif_cond=False):
    total_debt_amount_eth = 0
    tx_count = 0
    for user, debts in data.items():
        for debt, times in debts.items():
            for time, values in times.items():
                if end_time < float(time) or float(time) < start_time:
                    continue

                if has_specif_cond and len(data[user][debt][time]['txs']) == 0:
                    continue

                debt_to_cover = float(data[user][debt][time]['params'][3])
                debt_asset = data[user][debt][time]['params'][1]
                debt_checksum = Web3.toChecksumAddress(debt_asset)
                debt_amount_eth = debt_to_cover / 10**decimals[debt_checksum] * prices[debt_checksum]
                total_debt_amount_eth += debt_amount_eth
                tx_count += 1

    return total_debt_amount_eth/10**18, tx_count


def volum_calculation_per_week(data, start_date, end_date, prices, decimals, has_specif_cond=False):
    start_time = int(datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S").timestamp())
    end_time = int(datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S").timestamp())
    length = (end_time - start_time) // 86400

    debt_volum_per_week = []
    tx_count_per_week = []
    total = 0
    for i in range(length):
        debt_volum_per_day, tx_count_per_day = volum_calculation(data, start_time + i * 86400, start_time + (i+1) * 86400, prices, decimals, has_specif_cond)
        debt_volum_per_week.append(debt_volum_per_day)
        total += debt_volum_per_day
        tx_count_per_week.append(tx_count_per_day)

    debt_volum_per_week.append(total)
    return debt_volum_per_week, tx_count_per_week


def write_file_json(data, file):
    json_object = json.dumps(data, indent=4)

    with open(file, "w") as outfile:
        outfile.write(json_object)


def draw_histogram(bar_lists, bar_labels, line_lists, line_labels, x_label_names, fig_name):
    matplotlib.rc("font", family='DejaVu Sans')
    # plt.figure()
    # plt.title(fig_name)
    # plt.xlabel("date")
    fig, ax = plt.subplots(1, 1, figsize=(16, 9), dpi=100)
    ax.set_title(fig_name)
    ax.set_xlabel("date")
    ax.set_ylabel("debt_vol")
    ax2 = ax.twinx()
    ax2.set_ylabel("tx_count")

    bar_length = len(bar_lists)
    line_length = len(line_lists)

    x_length = len(bar_lists[0])
    total_width, n = 0.8, bar_length   # 柱状图总宽度，有几组数据
    x = np.arange(x_length)
    width = total_width / n   # 单个柱状图的宽度
    x_init = x - width / 2

    for i in range(bar_length):
        lst = np.array(bar_lists[i])
        x = x_init + i * width
        # plt.bar(x, lst, width=width, label=bar_labels[i])
        ax.bar(x, lst, width=width, label=bar_labels[i])

        for a, b in zip(x, lst):
            ax.text(a, b, '%.3f' % b, ha='center', va='bottom', fontsize=6)

    for i in range(line_length):
        if line_lists[i] is None:
            continue

        lst = np.array(line_lists[i])
        # x = x_init + i * width
        ax2.plot(x_init[:x_length-1], lst, label=line_labels[i])

    plt.xticks(x, x_label_names)
    # ax.legend()
    # ax2.legend()
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles = handles1 + handles2
    labels = labels1 + labels2
    plt.legend(handles, labels, loc='upper left', bbox_to_anchor=(0, 1))
    plt.show()


if __name__ == '__main__':
    my_res = json_file_load(ANALYSIS_PREF + "analysis_raw_my.json")
    actual = json_file_load(ANALYSIS_PREF + "analysis_raw_actual.json")

    start_date ="2023-03-12 00:00:00"
    end_date = "2023-03-19 00:00:00"
    dt_list = ["03-12", "03-13", "03-14", "03-15", "03-16", "03-17", "03-18", "week total"]

    network_id = 137
    prices = PRICES[network_id]
    decimals = DECIMALS[network_id]

    vol1, txs1 = volum_calculation_per_week(actual, start_date, end_date, prices, decimals)
    vol2, txs2 = volum_calculation_per_week(my_res, start_date, end_date, prices, decimals)
    vol3, txs3 = volum_calculation_per_week(my_res, start_date, end_date, prices, decimals, has_specif_cond=True)

    bar_labels = [
        "on-chain",
        "listened",
        "sent"
    ]
    line_labels = [
        "on-chain",
        "",
        "sent"
    ]
    fig_name = 'Weekly Report'

    draw_histogram([vol1, vol2, vol3], bar_labels, [txs1, None, txs3], line_labels, dt_list, fig_name)
    