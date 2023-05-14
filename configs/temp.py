'''
def query_priotity_fee(current_time):
    if current_time < priority_fee['last_update'] + 24:
        return priority_fee['value'] 

    url = "https://gasstation-mainnet.matic.network/v2"
    hdr = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
        'Accept-Encoding': 'none',
        'Accept-Language': 'en-US,en;q=0.8',
        'Connection': 'keep-alive'
    }

    request = urllib.request.Request(url, headers=hdr)
    try:
        context = ssl._create_unverified_context()
        reponse = urllib.request.urlopen(request, context=context).read()
        rep_json = json.loads(reponse)
        mev = int(rep_json['fast']['maxPriorityFee'] * 1.01 * 10**9) 
    except Exception as e:
        mev = priority_fee['value'] 
        logger.error("query priority fee error: {}".format(e))
    
    priority_fee['value'] = mev
    priority_fee['last_update'] = current_time
    return priority_fee['value']
'''

'''
url = "https://polygon-mainnet.g.alchemy.com/v2/Dj6K9l0FoVOaFtTXQ7fjLmuQjCYfXTYK"
payload = {
    "id": 1,
    "jsonrpc": "2.0",
    "method": "eth_maxPriorityFeePerGas"
}
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

try:
    response = requests.post(url, json=payload, headers=headers)
    rep_json = json.loads(response.text)
    mev = int(rep_json['result'], 16) * 1.01
except Exception as e:
    mev = priority_fee['value']
    logger.error("query priority fee error: {}".format(e))
'''
