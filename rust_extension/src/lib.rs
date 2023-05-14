use secp256k1::{Secp256k1, SecretKey};
use web3::types::{Transaction, Address, H256};
use web3::signing::{self, SecretKeyRef};
use std::convert::TryInto;

/* 
pub fn sign_transaction(
    nonce: u64,
    gas_price: u64,
    gas_limit: u64,
    to: Address,
    value: u64,
    data: Vec<u8>,
    chain_id: u64,
    secret_key: [u8; 32],
) -> H256 {
    let secp = Secp256k1::new();
    let secret_key = SecretKey::from_slice(&secret_key).expect("secret key from slice");
    let secret_key_ref = SecretKeyRef::new(&secret_key);
    let transaction = Transaction {
        nonce: nonce.into(),
        gas_price: gas_price.into(),
        gas: gas_limit.into(),
        to: Some(to),
        value: value.into(),
        input: data.into()
    };
    let signature = signing::sign_transaction(&transaction, &secret_key_ref, &secp).unwrap();
    let (v, r, s) = signature.rsv();
    let mut result = [0u8; 32];
    result[..32].copy_from_slice(&r.to_bytes_be());
    result[32..64].copy_from_slice(&s.to_bytes_be());
    result[31] = (v as u8) + 35 + (chain_id * 2).try_into().unwrap();
    H256::from(result)
}
*/
