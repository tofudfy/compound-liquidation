import json


def json_file_load(file_path):
    f = open(file_path)
    js = json.load(f)
    f.close()
    return js



