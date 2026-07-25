import os
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

ABI_PATH = BASE_DIR / "Feedback.abi.json"

WEB3_PROVIDER = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:7545")
OWNER_ADDRESS = os.getenv("WEB3_OWNER_ADDRESS")
OWNER_PRIVATE_KEY = os.getenv("WEB3_OWNER_PRIVATE_KEY")
CONTRACT_ADDRESS = os.getenv("FEEDBACK_CONTRACT_ADDRESS")
NON_OWNER_PRIVATE_KEY = os.getenv("NON_OWNER_PRIVATE_KEY", None) 

if not (OWNER_ADDRESS and OWNER_PRIVATE_KEY and CONTRACT_ADDRESS):
    raise SystemExit("Set WEB3_OWNER_ADDRESS, WEB3_OWNER_PRIVATE_KEY, FEEDBACK_CONTRACT_ADDRESS in .env")

w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER))
if not w3.is_connected():
    raise SystemExit(f"Cannot connect to provider: {WEB3_PROVIDER}")

abi = json.loads(Path(ABI_PATH).read_text(encoding="utf-8"))
contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)

def sha256_bytes32(text: str) -> bytes:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return bytes.fromhex(h)

def print_receipt(label: str, receipt):
    gas_used = int(receipt.get("gasUsed") if isinstance(receipt, dict) else getattr(receipt, "gasUsed", 0))
    effective_gas_price = receipt.get("effectiveGasPrice") if isinstance(receipt, dict) else getattr(receipt, "effectiveGasPrice", None)
    gas_price = int(effective_gas_price or w3.eth.gas_price)
    cost_wei = gas_used * gas_price
    cost_eth = Web3.from_wei(cost_wei, "ether")
    txhash = (receipt.get("transactionHash").hex() if isinstance(receipt, dict) else getattr(receipt, "transactionHash").hex())
    status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    print(f"{label}: tx={txhash} status={status} gas_used={gas_used} gas_price={gas_price} wei cost={cost_wei} (~{cost_eth} ETH)")

def _extract_txhash_from_exception(exc) -> str | None:
    try:
        if isinstance(exc, dict):
            data = exc.get("data") or exc
        else:

            data = exc.args[0] if getattr(exc, "args", None) else exc

        if isinstance(data, dict):
            if "hash" in data and isinstance(data["hash"], str):
                return data["hash"]
            nested = data.get("data") or data
            if isinstance(nested, dict):
                for k, v in nested.items():
                    if isinstance(k, str) and k.startswith("0x") and len(k) > 10:
                        return k
                    if isinstance(v, dict) and "hash" in v and isinstance(v["hash"], str):
                        return v["hash"]
        if isinstance(exc, str) and "0x" in exc:
            for part in exc.split():
                if part.startswith("0x") and len(part) > 10:
                    return part
    except Exception:
        pass
    return None

def send_signed_function_tx(signer_address: str, signer_private_key: str, fn, args=(), gas=300_000, label="tx"):
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(signer_address))
    tx = fn(*args).build_transaction({
        "from": Web3.to_checksum_address(signer_address),
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price,
    })

    # Estimate gas if not provided
    try:
        if gas is None:
            estimated = w3.eth.estimate_gas(tx)
            # add small headroom (5-10%) to avoid OOG
            tx["gas"] = int(estimated * 1.05)
        else:
            tx["gas"] = gas
    except Exception:
        # fallback to a safe upper bound if estimate fails
        tx["gas"] = gas or 300_000

    signed = w3.eth.account.sign_transaction(tx, private_key=signer_private_key)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)

    try:
        txh = w3.eth.send_raw_transaction(raw_tx)
    except Exception as exc:
        txhash = _extract_txhash_from_exception(exc)
        if txhash:
            txhash_hex = txhash.hex() if isinstance(txhash, (bytes, bytearray)) else txhash
            try:
                receipt = w3.eth.get_transaction_receipt(txhash_hex)
                print_receipt(label + " (reverted on send)", receipt)
                return receipt
            except Exception as fetch_exc:
                print(f"{label}: failed to fetch receipt for tx {txhash_hex} after exception: {fetch_exc}")
                return None
        print(f"{label}: send error (no txhash): {str(exc)[:200]}")
        return None

    try:
        receipt = w3.eth.wait_for_transaction_receipt(txh)
        print_receipt(label, receipt)
        return receipt
    except Exception as exc:
        try:
            txhash_hex = txh.hex() if isinstance(txh, (bytes, bytearray)) else str(txh)
            receipt = w3.eth.get_transaction_receipt(txhash_hex)
            print_receipt(label + " (reverted on receipt)", receipt)
            return receipt
        except Exception:
            print(f"{label}: failed to fetch receipt after wait error: {exc}")
            return None

def send_unlocked_tx(from_addr: str, tx_dict, label="unlocked"):
    txh = w3.eth.send_transaction(tx_dict)
    receipt = w3.eth.wait_for_transaction_receipt(txh)
    print_receipt(label, receipt)
    return receipt

def is_hash_stored(hash_bytes: bytes) -> bool:
    """call the new view function added to the contract."""
    return contract.functions.isHashStored(hash_bytes).call()

def main():
    print("Connected:", w3.is_connected())
    print("Contract owner (on-chain):", contract.functions.owner().call())
    print("Env owner:", OWNER_ADDRESS)
    print("--- Running 3 function tests ---")

    # Test 1: owner -> storeFeedbackHash 
    print("\nTest 1: owner storeFeedbackHash (success)")
    payload1 = "function-test-owner-1"
    data32 = sha256_bytes32(payload1)
    send_signed_function_tx(OWNER_ADDRESS, OWNER_PRIVATE_KEY, contract.functions.storeFeedbackHash, args=(data32,), label="Test1-owner-store")

    # Test 2: owner -> getCount via signed transaction (view function sent as tx to measure gas)
    print("\nTest 2: owner getCount sent as transaction (measures gas)")
    try:
        count = contract.functions.getCount().call({"from": Web3.to_checksum_address(OWNER_ADDRESS)})
        print("getCount (call):", count)
    except Exception as e:
        print("getCount call failed:", e)
    try:
        tx_for_est = contract.functions.getCount().build_transaction({
            "from": Web3.to_checksum_address(OWNER_ADDRESS),
            "nonce": w3.eth.get_transaction_count(Web3.to_checksum_address(OWNER_ADDRESS)),
        })
        est = w3.eth.estimate_gas(tx_for_est)
        print("Estimated gas for getCount tx (simulation):", est)
    except Exception:
        pass

    # Test 3: non-owner attempt to storeFeedbackHash (should revert and consume gas)
    print("\nTest 3: non-owner attempt storeFeedbackHash (expect revert / gas used)")
    payload3 = "function-test-non-owner"
    data3 = sha256_bytes32(payload3)

    if NON_OWNER_PRIVATE_KEY:
        acct = w3.eth.account.from_key(NON_OWNER_PRIVATE_KEY)
        try:
            send_signed_function_tx(acct.address, NON_OWNER_PRIVATE_KEY, contract.functions.storeFeedbackHash, args=(data3,), label="Test3-nonowner-signed")
        except Exception as e:
            print("Test3 non-owner signed tx exception:", e)
    else:
        accounts = w3.eth.accounts
        non_owner = next((a for a in accounts if a.lower() != OWNER_ADDRESS.lower()), None)
        if non_owner is None:
            print("No non-owner account available for Test 3")
            return
        data = contract.encodeABI(fn_name="storeFeedbackHash", args=[data3])
        tx_dict = {
            "from": Web3.to_checksum_address(non_owner),
            "to": Web3.to_checksum_address(CONTRACT_ADDRESS),
            "data": data,
            "gas": 300_000,
        }
        try:
            send_unlocked_tx(non_owner, tx_dict, label="Test3-nonowner-unlocked")
        except Exception as e:
            print("Test3 non-owner unlocked tx exception:", e)

if __name__ == "__main__":
    main()