use ethereum_tx_sign::LegacyTransaction;
use std::os::raw::{c_char, c_uchar};
use std::ffi::{CStr, CString};
use std::slice;
use std::mem;
use std::ptr;

#[no_mangle]
pub extern "C" fn sign_tx(to_addr: *const c_char, data: *const c_char, gas_price: u64, nonce: u64, private_key: *const c_uchar) -> *mut c_uchar {
    // Convert input parameters to Rust types
    let to_addr_str = unsafe { CStr::from_ptr(to_addr).to_str().unwrap() };
    let data_str = unsafe { CStr::from_ptr(data).to_str().unwrap() };
    let private_key_bytes = unsafe { slice::from_raw_parts(private_key, 32) };

    // Prepare transaction object
    let mut to_array: [u8; 20] = [0; 20];
    let to_addr_bytes = to_addr_str.as_bytes();
    to_array.copy_from_slice(&to_addr_bytes[0..20]);

    let data_bytes = data_str.as_bytes();
    let data_vec = data_bytes.to_vec();

    let new_transaction = LegacyTransaction {
        to: Some(to_array),
        value: 0,
        gas_price: gas_price,
        gas: 3000000,
        data: data_vec,
        nonce: nonce,
        chain: 56,
    };

    // Sign transaction with private key
    let ecdsa = new_transaction.ecdsa(&private_key_bytes);
    let transaction_bytes = new_transaction.sign(&ecdsa);

    // Convert result to C pointer and return
    let result_ptr = transaction_bytes.as_ptr() as *mut c_uchar;
    let result_len = transaction_bytes.len();
    mem::forget(transaction_bytes);
    unsafe { ptr::replace(result_ptr.offset(result_len as isize), 0) };
    result_ptr
}
