import secrets
from typing import List
from hexbytes import HexBytes
from eth_account import Account
from eth_account.signers.local import LocalAccount
from transaction.sign_diy import sign_tx0

SECRET_KEYS = {
    "Polygon": [
        '68c857207d2cd8fdee278b8d8e69335774bb1629c683b2939709062f630408e5',  # 0x6DCdAE2FaF3D8aaa53B344C490335716AD20B716
        '365f73aa00bd53cfe6527e7804320c20d697c27902494dd30c1a7a94fb77c677',  # 0xEaF49401160dd0bca634d8E18d9DF41d3F6153Bb
        # '45575b48d22701b972f3fdc4e46860d502f68579bba9cf4d0318d4611506aa2a',  # 0x5795e3FA50eC03688Baa0F9Bc6830D084A597D91
        # 'f8667382357e23d8d2a91d6db2d42f111d8a5bec69dd31858c384de412045dec',  # 0xEAA7dc0fde5949479A5B66b883F50027539f89Ca
        # '769f5a7a1a16f4cae6f7696f5fd743ae856a2970f6fea5eefa7bc6be445308ba',  # 0x395483AabAd534F8e7D6a67DE766692d941868d5
        'a2e88e0e5517d8f4e7174746aa92acea66d1315356b7ffe7ad0741177d32fce0',  # 0x8B280bd1A681db462aD5818CdF0e9Ec65F51bDec
    ],
    "Ethereum": [
        '6eee1827f0a31530343691aacd9c6a503aec85382c0ccfc967fd81bb12942108'  # 0xA1D3d71279cB6E4f0a6C1eF5e7fE282a087bCaf0 
    ],
    "BSC": [
        "4f8580093452b5663d4ec462440907f998ea23944187454255b23961cadbcea1",  # 0x4153aEf7bf3c7833b82B8F2909b590DdcF6f8c15
        # "94643883510a28929d98b377aa9743a1f331623e8bf6a82985f4f619c133dcae",  # 0x0B8466B903951FCbb61b57316E7CCCa722e027e7
    ],
    "BNB48": [
        "15755ada41d9f255ef2fbe3e1d382ee75dea7b24fb451294c11eac90342d28a2",  # 0xFC030e374112103C889D0c9b6DBe2b9c6fC94614
    ],
    "Flash":[
        "ecfa17529a03efff8f0ea8f2e81d90228608d329cd2eef2fb82d195396b099aa",  # 0xDc808668664De216AB24E20AF3f8448FbD700EAA
    ],
    "Test": [
    
    ]
}


class AccCompound(object):
    def __init__(self, sk) -> None:
        self.account: LocalAccount = Account.from_key(sk)
        # todo: multiprocessing cannot pickle module
        # self.sk = sk
        self.nonce = 0

    def sign_tx(self, tx):
        account = self.account
        # account = Account.from_key(self.sk)
        signed_tx = account.signTransaction(tx)
        return signed_tx.rawTransaction, signed_tx.hash
    
    def sign_tx_diy(self, tx) -> HexBytes:
        account = self.account
        # account = Account.from_key(self.sk)
        return sign_tx0(tx, account)

    def get_address(self):
        account = self.account
        # account = Account.from_key(self.sk)
        return account.address


def gen_new_account() -> AccCompound:
    priv = secrets.token_hex(32)
    private_key = "0x" + priv
    print ("SAVE BUT DO NOT SHARE THIS:", private_key)
    acct = AccCompound(private_key)
    print("Address:", acct.get_address())
    
    return acct 


if __name__ == '__main__':
    gen_new_account()