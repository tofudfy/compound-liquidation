import json
from hexbytes import HexBytes

from types_liq import LogReceiptLight, converter
from configs.web3_liq import Web3Liquidation
from configs.config import RESERVES
from configs.signals import Signals, AggregatorInfos
from configs.block import BlockInfos
from configs.comet import CometConfigs, init_comet_configs
from configs.users import backtesting_states
from configs.tokens import complete_ctokens_price_info
from compound import tx_filter_and_parsing, calculate_health_factor, liquidation_simulation

SIGNAL_MESSAGE = {'type': '0x0', 'nonce': '0x133798a', 'gasPrice': '0x78ace58d37', 'maxPriorityFeePerGas': None, 'maxFeePerGas': None, 'gas': '0x7a120', 'value': '0x0', 'input': '', 'v': '0x135', 'r': '0xe2611d8e66e2886d4fe9a3ec66a42fa9f4d541c372cf138972f0483e4f04efd4', 's': '0x52d45d82218390ac665912ec9ee85a71636e411955c8b01a035792dfb7cffd3', 'to': '0xc6d82423c6f8b0c406c1c34aee8e988b14d5f685', 'hash': '0xd845e76f1f20ec68ff18190be6bb7186731f9a9ec6c52332d0b3ecc0362c3a69', 'from': '0x250abd1d4ebc8e70a4981677d5525f827660bde4'}


def subscribe_test(callback):
    response = """
    {
        "events":[
            {
                "address": "0x7fabdd617200c9cb4dcf3dd2c41273e60552068a",
                "topics": [
                    "0xaeba5a6c40a8ac138134bff1aaa65debf25971188a58804bad717f82f0ec1316"
                ],
                "txIndex":44,
                "data": "0x",
                "transactionHash": "0x"
            }
        ],
        "blockNumber": 234,
        "blockHash": "0x",
        "type": "events",
        "id": "123"
    }
    """
    resp = json.loads(response)
    callback(resp)


def subscribe_callback(response: LogReceiptLight):
    block_num = response['blockNumber']
    block_hash = response['blockHash']
    logs = converter(response)
    comet = CometConfigs(0, 0, {}, 0)

    for log in logs:
        comet.update(log)


def tx_filter_test():
    """
    w3_liq = Web3Liquidation('http')
    # https://etherscan.io/tx/0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375
    tx = w3_liq.w3.eth.get_transaction("0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375")
    """
    tx = {'blockHash': HexBytes('0x4d7001877d2c9a69b85b1f5ca37168f0494c3ec67dc2d90a4f4d5a6037ff131b'), 'blockNumber': 16903768, 'hash': HexBytes('0x6edc7e58d4278afba0ac4183e8d2093f9cf5e1d9574f5de28516993274565375'), 'accessList': [], 'chainId': '0x1', 'from': '0xCF4Be57aA078Dc7568C631BE7A73adc1cdA992F8', 'gas': 740000, 'gasPrice': 16907912669, 'input': '0xc9807539000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000003200000000000000000000000000000000000000000000000000000000000000400010000010001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002800000000000000000000000f4f5545633e09805a78067ed5d8df24200050398020e05080003020c01070a040b090d0f060000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000167909a000000000000000000000000000000000000000000000000000000000167b1d8000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167b203000000000000000000000000000000000000000000000000000000000167bb3e000000000000000000000000000000000000000000000000000000000167bfdf000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167c590000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cd60000000000000000000000000000000000000000000000000000000000167cef6000000000000000000000000000000000000000000000000000000000167f79d000000000000000000000000000000000000000000000000000000000167fa9f00000000000000000000000000000000000000000000000000000000016820f3000000000000000000000000000000000000000000000000000000000168286c0000000000000000000000000000000000000000000000000000000000000006372bffca6271a89560dab24d3a05573b383677163783dd1353d93e1ce22169124702dddfe2697f1df818821bdc4c01e391f935ee1e29fda25d5c47940b0a058430dd021f694931840b458c82782b4e45ab536ffa73900907af4bfadd07ddf85cf8ee62ddd598afd656c27656df014730e578dd635a30e59e10ac79467e743fe8b437ec30d8f3c28dbc6b69ff7e00f6f87137a7916e605b65f14a1516de588da75ef78a22c74d7dea5c0ee1baa116773f3ecd3e244b07a5df15f3506b5d727d6b00000000000000000000000000000000000000000000000000000000000000061d1b72ec1efdd79e8fa8cac54081209cb5eeff9b7994157214004bd5dfa286234e2d074b27444faf986b114dd748cba19fbebc008911c90648dd1ab9c99be77e4e6fc84953d7a1b6f76301e1ac0fb44eae0d3d93124760a32f676509c1a021057b0e6af01fc20ee9ce2810296a3230b298dcb459623d72fc57a07c41909eb5895b957fb8394003b85ec932f32b4925b830ce22cae7946a889b28a73fe57997d7604a931844080d9393c31e96917f713689d10c07c028d8f9bd102c7aa9c860e5', 'maxFeePerGas': 53485758643, 'maxPriorityFeePerGas': 1400000000, 'nonce': 73993, 'r': HexBytes('0xba9f79adc7a61c1c074836eea935f2e6f578ef7b9d4abc7f8a1441a5da1f8cd1'), 's': HexBytes('0x51b8f1fe7fd3b12b736f45289eae5136219084c9334a3ae6deb7512d2f40f0d6'), 'to': '0xd90CA9ac986e453CF51d958071D68B82d17a47E6', 'transactionIndex': 51, 'type': '0x2', 'v': 0, 'value': 0}

    signals = Signals({'0xd90CA9ac986e453CF51d958071D68B82d17a47E6': AggregatorInfos('0x0D8775F648430679A709E98d2b0Cb6250d2887EF', ['BAT','USD'])}, [])
    block_infos = BlockInfos(0, 0, 0)
    block_infos.gas_price = 16000000000
    res = tx_filter_and_parsing(signals, block_infos, tx)
    print(res)


def cal_users_states_test():
    w3_liq = Web3Liquidation('http')
    block_num = 16883307 - 1  # liquidation height
    user = "0x5094B1E462730711C2d5227D7d8fF9A6e67F50E2"

    comet = w3_liq.gen_comptroller()
    res = comet.functions.getAccountLiquidity(user).call(block_identifier=block_num)
    print(res)

    # reserves = w3_liq.query_markets_list(block_num)
    reserves = RESERVES
    states = backtesting_states(w3_liq, user, reserves, block_num)

    reserves_trim = list(states.users_states[user].reserves.keys())
    comet = init_comet_configs(w3_liq, reserves_trim)
    complete_ctokens_price_info(states.ctokens, w3_liq, reserves_trim, block_num)

    calculate_health_factor(user, states.users_states[user].reserves, states.ctokens, comet)
    collaterals, debt = liquidation_simulation(states.users_states[user].reserves, states.ctokens, comet)
    liquidation_params = [collaterals[0][1], debt[1], user, collaterals[0][3], False]
    seized = collaterals[0][2]
    revenue = collaterals[0][0] / 10**18
    print(liquidation_params, revenue, seized)


if __name__ == '__main__':
    # subscribe_test(subscribe_callback)
    # tx_filter_test()

    cal_users_states_test()
