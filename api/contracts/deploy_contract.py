import json
import os
from pathlib import Path
from web3 import Web3
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

ABI_PATH = BASE_DIR / "Feedback.abi.json"
BYTECODE_PATH = BASE_DIR / "Feedback.bytecode.txt"

def main():
    provider_url = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:7545")
    owner_address = os.getenv("WEB3_OWNER_ADDRESS")
    owner_private_key = os.getenv("WEB3_OWNER_PRIVATE_KEY")

    if not owner_address or not owner_private_key:
        raise SystemExit("Missing WEB3_OWNER_ADDRESS or WEB3_OWNER_PRIVATE_KEY in environment")

    w3 = Web3(Web3.HTTPProvider(provider_url))
    if not w3.is_connected():
        raise SystemExit(f"Cannot connect to provider: {provider_url}")

    abi = json.loads(ABI_PATH.read_text(encoding="utf-8"))
    bytecode = BYTECODE_PATH.read_text(encoding="utf-8").strip()
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode

    acct = w3.eth.account.from_key(owner_private_key)
    owner_checksum = Web3.to_checksum_address(owner_address)

    if acct.address.lower() != owner_checksum.lower():
        raise SystemExit(
            f"Private key does not match owner address.\n"
            f"Key address: {acct.address}\n"
            f"Env address: {owner_checksum}"
        )

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    nonce = w3.eth.get_transaction_count(owner_checksum)
    tx = contract.constructor().build_transaction({
        "from": owner_checksum,
        "nonce": nonce,
        "gas": 3_000_000,
        "gasPrice": w3.eth.gas_price,
    })

    signed = w3.eth.account.sign_transaction(tx, private_key=owner_private_key)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    if raw_tx is None:
        raise SystemExit("Could not find raw signed transaction bytes on signed tx object")

    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1:
        raise SystemExit("Deployment failed (receipt.status != 1)")

    print("ENV_PATH:", ENV_PATH)
    print("WEB3_PROVIDER_URL:", os.getenv("WEB3_PROVIDER_URL"))
    print("WEB3_OWNER_ADDRESS:", os.getenv("WEB3_OWNER_ADDRESS"))
    print("WEB3_OWNER_PRIVATE_KEY set:", bool(os.getenv("WEB3_OWNER_PRIVATE_KEY")))
    print("Deployed Feedback contract")
    print("tx_hash:", tx_hash.hex())
    print("contract_address:", receipt.contractAddress)
    print("owner (deployer):", owner_checksum)
    print()
    print("Put this in your .env:")
    print(f"FEEDBACK_CONTRACT_ADDRESS={receipt.contractAddress}")

if __name__ == "__main__":
    main()