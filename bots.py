from typing import List
from web3 import Web3
from eth_abi import encode
from configs.protocol import Web3CompoundVenues
from configs.router import Path

class BSCVenusPancakeV2(object):
    def __init__(self) -> None:
        pass

    def gen(self, borrower, debt_ctoken, col_ctoken, paths: List[Path]):
        """
        address borrower, 
        address repayCToken, 
        address seizeCToken,
        Step[] memory steps

        struct Step {
            address pool;
            // 2 for univ2, 3 for univ3
            // uint8 protocol;
            // for univ2
            uint24 fee;
            bool isZeroForOne;
            address token0;
            address token1;
            uint amountOut;
        }
        """

        # varied based on the contract deployed
        intput = "0x5cf671a6"
        intput += borrower.lower()[2:].zfill(64)    # borrower
        intput += debt_ctoken.lower()[2:].zfill(64) # debt_ctoken
        intput += col_ctoken.lower()[2:].zfill(64)  # col_ctoken

        # todo 
        intput += '0x80'[2:].zfill(64)          # offset: 32 bytes
        intput += hex(len(paths))[2:].zfill(64) # lenght 

        for i in range(len(paths)-1, -1, -1):
            path = paths[i]
            intput += path.pool_addr.lower()[2:].zfill(64)  # pair
            intput += hex(path.fee)[2:].zfill(64)           # repayAmount 
            intput += str(path.is_zero_for_one).zfill(64)   # zero_for_one 
            intput += path.token0.lower()[2:].zfill(64)     # token0
            intput += path.token1.lower()[2:].zfill(64)     # token1
            intput += hex(path.amount_out)[2:].zfill(64)    # repayAmount 

        return intput


# todo
# or use tenderly to check the data
def bsc_venus_cakev2_test():
    w3_liq = Web3CompoundVenues()
    bot_sc = w3_liq.gen_bot()
    params = (
        "0x00000000219ab540356cBB839Cbe05303d7705Fa",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8",
        [
            Path(
                "0xDA9dfA130Df4dE4673b89022EE50ff26f6EA73Cf",
                25,
                0,
                "0x8315177aB297bA92A06054cE80a67Ed4DBd7ed3a",
                "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503",
                1000
            ),
            Path(
                "0x2B6eD29A95753C3Ad948348e3e7b1A251080Ffb9",
                25,
                1,
                "0x8103683202aa8DA10536036EDef04CDd865C225E",
                "0x0a4c79cE84202b03e95B7a692E5D728d83C44c76",
                20000
            )
        ]
    )

    bot = BSCVenusPancakeV2()
    

    res = bot.gen(*params)
    print(res)

    encoded_data = encode(['address', 'address', 'address', 'tuple[]'], params)
    tx = bot_sc.functions.swap(encoded_data).build_transaction({'from': "0x4153aEf7bf3c7833b82B8F2909b590DdcF6f8c15"})
    print(tx)


# Warning: incorret, do not use the function
def gen_function_sig():
    function_signature = "swap(address,address,address,tuple[])"

    # Compute the function selector
    function_hash = Web3.keccak(function_signature.encode()).hex()[:10]
    print(f"Function selector: {function_hash}")


'''
def gen_contract_data():
    """
    [2023-04-16 21:35:05.116] - [line:584] - INFO:
    liquidation start: {
        "index":"1b2af322808be0448edfe7b88ca7eb32", 
        "user":"0x9109358674f1c9a1a945a1d9880fb7ef1ddc43a3", 
        "revenue":2.656284532361661, 
        "block_num":27399446, 
        "params":['0x9109358674f1c9a1a945a1d9880fb7ef1ddc43a3', 77361501995088862, '0xfD5840Cd36d94D7229439859C0112a4185BC0255'], 
        "to_addr": "0xA07c5b74C9B40447a954e1466938b865b6BBea36", 
        "gainedAmount": 131441338183, 
        "signal":"0xf90665fe402a9db7e0ada14b8374d679181a06d335bff2dbe4c3957bc07a145f"}
    """
    params_liq = ['0x9109358674F1C9a1a945a1d9880fb7EF1DDC43a3', 77361501995088862, '0xfD5840Cd36d94D7229439859C0112a4185BC0255']
    borrower = params_liq[0]
    repay_amount = params_liq[1]
    
    debt_ctoken = "0xA07c5b74C9B40447a954e1466938b865b6BBea36"
    col_ctoken = params_liq[2]
    token0 = "0x55d398326f99059fF775485246999027B3197955" # states.ctokens[debt_ctoken].configs.underlying
    token1 = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c" # states.ctokens[col_ctoken].configs.underlying
    
    zero_for_one = True
    pool_addr = "0x1111111111111111111111111111111111111111"

    function_signature = "swap(bool,uint256,address,address,address,address,address,address)"

    # Compute the function selector
    function_hash = hashlib.sha3_256(function_signature.encode()).hexdigest()[:8]
    print(f"Function selector: {function_hash}")

    # Define input parameters
    params = (
        zero_for_one,  # zeroForOne
        repay_amount,  # amount
        pool_addr,  # pair
        token0,  # token0
        token1,  # token1
        borrower,  # borrower
        debt_ctoken,  # repayCToken
        col_ctoken,  # seizeCToken
    )

    # Encode input parameters
    encoded_params = encode(["bool", "uint256", "address", "address", "address", "address", "address", "address"], params)
    print(f"Encoded parameters: {encoded_params.hex()}")

    # Assemble the data
    data = f"0x{function_hash}{encoded_params.hex()}"
    print(f"Data: {data}")

    intput = "0x1d249383"
    intput += hex(zero_for_one)[2:].zfill(64)  # zero_for_one 
    intput += hex(-params_liq[1] & (2**256-1))[2:] # repayAmount
    intput += pool_addr.lower()[2:].zfill(64)  # pair
    intput += token0.lower()[2:].zfill(64)     # token0
    intput += token1.lower()[2:].zfill(64)     # token1
    intput += params_liq[0].lower()[2:].zfill(64)  # borrower
    intput += debt_ctoken.lower()[2:].zfill(64)    # debt_ctoken
    intput += params_liq[2].lower()[2:].zfill(64)  # col_ctoken
    print(intput)
'''


if __name__ == '__main__':
    bsc_venus_cakev2_test()
    # gen_function_sig()
