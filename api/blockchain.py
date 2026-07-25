import json
import hashlib
from pathlib import Path
from django.conf import settings
from web3 import Web3

# Load ABI from compiled file instead of hardcoding
BASE_DIR = Path(__file__).resolve().parent
ABI_PATH = BASE_DIR / "contracts" / "Feedback.abi.json"

def _load_feedback_abi() -> list[dict]:
    return json.loads(ABI_PATH.read_text(encoding="utf-8"))

def feedback_payload(
    form_type: str,
    form_object_id: int,
    student_id: int | None,
    pseudonym: str | None,
    responses: list[dict],
) -> dict:
    return {
        "form_type": form_type,
        "form_object_id": int(form_object_id),
        "student_id": int(student_id) if student_id is not None else None,
        "pseudonym": pseudonym,
        "responses": responses,
    }

def compute_feedback_hash_hex(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def store_hash_onchain(hash_hex: str) -> str:
    provider = getattr(settings, "WEB3_PROVIDER_URL", None)
    contract_addr = getattr(settings, "FEEDBACK_CONTRACT_ADDRESS", None)
    owner_addr = getattr(settings, "WEB3_OWNER_ADDRESS", None)
    owner_pk = getattr(settings, "WEB3_OWNER_PRIVATE_KEY", None)

    if not (provider and contract_addr and owner_addr and owner_pk):
        raise RuntimeError("Missing WEB3_* settings for blockchain integration")

    w3 = Web3(Web3.HTTPProvider(provider))
    if not w3.is_connected():
        raise RuntimeError("Web3 provider not reachable")

    abi = _load_feedback_abi()
    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=abi)

    data_bytes32 = bytes.fromhex(hash_hex)

    tx = contract.functions.storeFeedbackHash(data_bytes32).build_transaction({
        "from": Web3.to_checksum_address(owner_addr),
        "nonce": w3.eth.get_transaction_count(Web3.to_checksum_address(owner_addr)),
        "gas": 200000,
        "gasPrice": w3.eth.gas_price,
    })

    signed = w3.eth.account.sign_transaction(tx, private_key=owner_pk)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    if raw_tx is None:
        raise RuntimeError("Could not find raw signed transaction bytes on signed tx object")

    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1:
        raise RuntimeError("On-chain tx failed")

    return tx_hash.hex()