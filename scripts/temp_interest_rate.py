from configs.config import RESERVES 
from configs.users import reload_states 


reserves = RESERVES
states = reload_states(reserves)
users = list(states.users_states.keys())

res = {}
for usr in users:
    for k, v in states.users_states[usr].reserves.items():
        borrow_index = states.ctokens[k].risks.borrow_index
        interest_rate = v.debt_interest
        if interest_rate == 0:
            continue

        temp = borrow_index/interest_rate
        [min, max] = res.get(k, [2, 1])
        if temp < min:
            min = temp
            
        if temp > max:
            max = temp
            
        res[k] = [min, max]

print(res)
