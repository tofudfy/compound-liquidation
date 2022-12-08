# importing the requests library
import requests

from configuration import query_markets_list

# api-endpoint
URL = "https://api.etherscan.io/api?module=contract"

# defining a params dict for the parameters to be sent to the API
PARAMS = {
    'action': "getsourcecode",
    'address': "",
    'apikey': "ZBP8EK62PT6IHARCBVJ3W9VS57EA5UHBC8"
}


def send_request(address):
    PARAMS['address'] = address
    r = requests.get(url=URL, params=PARAMS)
    req = r.json()
    return req


def main():
    dic = {}
    reserves = query_markets_list()

    for reserve in reserves:
        data = send_request(reserve)
        if data['result'][0]['Proxy'] == "1":
            addr = data['result'][0]['Implementation']
            data = send_request(addr)

        dic[reserve] = data['result'][0]['ContractName']

    print(dic)


if __name__ == '__main__':
    main()
