import json
import os
import time
from web3 import Web3


def json_file_load(file_path):
    f = open(file_path)
    js = json.load(f)
    f.close()
    return js


def json_write_to_file(data, abs_path, file_path):
    json_object = json.dumps(data, indent=4)
    with open(abs_path + os.sep + file_path, "w") as outfile:
        outfile.write(json_object)


def data_cache_hook(obj, count: int):
    if count >= 100:
        obj.cache()
        count = 0

    return count


def empty_hook(obj, count):
    time.sleep(1)
    return 0


def query_events_loop(w3: Web3, obj, filt, target_block, hook=empty_hook):
    counter = 0
    while obj.last_update < target_block:
        from_block = obj.last_update + 1
        to_block = from_block + 1999
        if to_block > target_block:
            to_block = target_block

        filt['fromBlock'] = hex(from_block)
        filt['toBlock'] = hex(to_block)

        try:
            logs = w3.eth.get_logs(filt)
        except Exception as e:
            # raise Exception(f"get logs failed, error: {e}")
            print(f"get logs failed at {from_block}, error: {e}")
            break

        for log in logs:
            obj.update(log)
        obj.last_update = to_block

        counter += 1
        counter = hook(obj, counter)
