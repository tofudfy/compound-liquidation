import os

PREFIX = "./"


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
        res = read_and_parse(f, targets_line, log_filter)

    return res


def read_and_parse(file, targets, log_filter):
    f = open(file)
    iter_f = iter(f)

    switch = False
    temp = ""
    for line in iter_f:
        if line.find(targets[0]) > -1:
            switch = True
            temp = ""

        if switch:
            temp += line

        if line.find(targets[1]) > -1:
            switch = False 
            print(temp)


if __name__ == '__main__':
    read_and_parse_from_folder(PREFIX, "liquidation_bsc_compound_venus_20230502.log", ["users in local cache updated: ", "user add to pre filtered: "], None)
