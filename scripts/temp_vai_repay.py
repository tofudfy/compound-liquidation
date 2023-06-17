import time
from configs.users import reload_states
from configs.config import RESERVES 
from configs.protocol import Web3CompoundVenues


def max_vai_repay():
    reserves = RESERVES
    states = reload_states(reserves)

    max_vai = 0
    for usr, data in states.users_states.items():
        if data.vai_repay > max_vai:
            max_vai = data.vai_repay

    print(max_vai)


def update_vai_repay():
    w3_liq = Web3CompoundVenues('http_local')
    reserves = RESERVES
    states = reload_states(reserves)
    
    for usr, _ in states.users_states.items():
        res = w3_liq.query_user_vai_repay(usr)
        states.users_states[usr].vai_repay = res
        time.sleep(0.001)

    states.cache()


if __name__ == '__main__':
    update_vai_repay() 
