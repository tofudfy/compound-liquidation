
import re
import json
import time
import matplotlib
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta


def is_hex_string(s):
    hex_pattern = re.compile("^0x[a-fA-F0-9]+$")
    return bool(hex_pattern.match(s))


def convert_tar_to_pattern(targets):
    patterns = []
    for s in targets:
        patterns.append(re.compile('.*' + s + '(.*)', re.S))

    return patterns


def write_file(data, file):
    json_object = json.dumps(data, indent=4)

    with open(file, "w") as outfile:
        outfile.write(json_object)


def unix_to_readable(block_timestamp):
    return datetime.fromtimestamp(block_timestamp, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')


def unix_time(dt):
    # 转换成时间数组
    time_array = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    # 转换成时间戳
    timestamp = time_array.timestamp()
    return timestamp


def unix_to_readable_ms(block_timestamp):
    return datetime.fromtimestamp(block_timestamp, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S.%f')


def unix_time_ms(dt):
    # 转换成时间数组
    time_array = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
    # 转换成时间戳
    timestamp = time_array.timestamp()
    return timestamp


p = re.compile(r'\[(.*?)\]', re.S)
def line_time_parser(line):
    log_time = re.findall(p, line)[0]
    return log_time


def line_json_parser(line_origin, p):
    line = line_origin.replace("None", "'None'")
    line = line.replace("\'", "\"")
    line = line.replace("False", "false")
    line = line.replace("True", "true")

    res = re.findall(p, line)[0]
    res_js = json.loads(res)
    return res_js


def data_plot_hist(array, target_time, figure_name, index):
    a = np.array(array, dtype=float)
    min_num = np.min(a)
    max_num = np.max(a)
    middle_num = np.median(a)
    ava = np.mean(a)
    sigma = np.std(a)

    plt.figure(index)
    plt.hist(a, bins=50)
    plt.title(figure_name + ' at ' + target_time + '\n Histogram : $\mu=$' + str(round(ava, 6)) + ' $\sigma=$' +
              str(round(sigma, 6)) + '\n Stats: $\min=$' + str(round(min_num, 6)) + ' $\max=$' +
              str(round(max_num, 6)) + ' $med=$' + str(round(middle_num, 6)) + ' ttl=' + str(len(array)))
    plt.show()


def draw_histogram(res1, res2, fig_name, labels):
    matplotlib.rc("font", family='DejaVu Sans')
    list1 = np.array(res1)   # 柱状图第一组数据
    list2 = np.array(res2)   # 柱状图第二组数据
    length = len(list1)
    x = np.arange(length)   # 横坐标范围
    listDate = ["inf-1.1", "1.1-1.01", "1.01-1.0", "1.0-0.9", "0.9-0", "0"]

    plt.figure()
    total_width, n = 0.8, 2   # 柱状图总宽度，有几组数据
    width = total_width / n   # 单个柱状图的宽度
    x1 = x - width / 2   # 第一组数据柱状图横坐标起始位置
    x2 = x1 + width   # 第二组数据柱状图横坐标起始位置

    plt.title(fig_name)   # 柱状图标题
    plt.xlabel("health factor")   # 横坐标label 此处可以不添加
    plt.ylabel("numbers")   # 纵坐标label
    plt.bar(x1, list1, width=width, label=labels[0])
    plt.bar(x2, list2, width=width, label=labels[1])

    for a, b in zip(x1, list1):
        plt.text(a, b, '%.0f' % b, ha='center', va='bottom', fontsize=8)

    for a, b in zip(x2, list2):
        plt.text(a, b, '%.0f' % b, ha='center', va='bottom', fontsize=8)

    plt.xticks(x, listDate)   # 用星期几替换横坐标x的值
    plt.legend()   # 给出图例
    plt.show()