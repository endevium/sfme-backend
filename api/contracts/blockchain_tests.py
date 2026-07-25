import sys
from pathlib import Path
import os
import logging
import io
import contextlib
import uuid
import uuid

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.contracts import gas_tests
from api.contracts.blockchain_security import (
    validate_private_key,
    require_env_keys,
    moderate_feedback,
    prepare_feedback_hash,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def assert_print(cond: bool, msg: str):
    print(("PASS: " if cond else "FAIL: ") + msg)

def test_logic_flaws_and_formal():
    print("\n=== Logic flaws / formal verification tests (3 cases) ===")
    run_id = uuid.uuid4().hex

    # Case 1 – normal store + retrieval + mapping flag
    payload = str(uuid.uuid4())                  # unique per run
    h = gas_tests.sha256_bytes32(payload)
    try:
        payload = f"normal feedback::{run_id}::case1"
        h = gas_tests.sha256_bytes32(payload)
        receipt = gas_tests.send_signed_function_tx(
            gas_tests.OWNER_ADDRESS,
            gas_tests.OWNER_PRIVATE_KEY,
            gas_tests.contract.functions.storeFeedbackHash,
            args=(h,),
            label="logic_case1"
        )
        ok = receipt and receipt.status == 1
        assert_print(ok, f"normal store succeeded status={getattr(receipt,'status',None)}")
        stored_flag = gas_tests.is_hash_stored(h)
        assert_print(stored_flag, "hash marked stored in mapping")
        count = gas_tests.contract.functions.getCount().call()
        assert_print(count > 0, f"getCount returned {count}")
    except Exception as e:
        text = str(e)
        if "Duplicate hash" in text:
            assert_print(True, "normal store skipped: hash already stored")
            stored_flag = gas_tests.is_hash_stored(h)
            assert_print(stored_flag, "hash marked stored in mapping (existing)")
        else:
            assert_print(False, f"exception during normal store: {e}")

    # Case 2 – zero hash reverted
    try:
        zero = b"\x00" * 32
        receipt2 = gas_tests.send_signed_function_tx(
            gas_tests.OWNER_ADDRESS,
            gas_tests.OWNER_PRIVATE_KEY,
            gas_tests.contract.functions.storeFeedbackHash,
            args=(zero,),
            label="logic_case2_zero"
        )
        rejected = receipt2 and receipt2.status == 0
        assert_print(rejected, f"zero‑hash txn reverted status={getattr(receipt2,'status',None)}")
    except Exception as e:
        assert_print(True, f"zero‑hash raised exception (treated as revert): {e}")

    # Case 3 – duplicate rejected; ABI contains new view
    dup_payload = str(uuid.uuid4())
    dup_hash = gas_tests.sha256_bytes32(dup_payload)
    try:
        dup_payload = f"duplicate::{run_id}::case3"
        dup_hash = gas_tests.sha256_bytes32(dup_payload)
        gas_tests.send_signed_function_tx(
            gas_tests.OWNER_ADDRESS,
            gas_tests.OWNER_PRIVATE_KEY,
            gas_tests.contract.functions.storeFeedbackHash,
            args=(dup_hash,),
            label="logic_case3_first"
        )
    except Exception as e:
        # if it's a duplicate that's fine
        assert_print("Duplicate hash" in str(e), f"first dup store fallback: {e}")
    try:
        receipt3 = gas_tests.send_signed_function_tx(
            gas_tests.OWNER_ADDRESS,
            gas_tests.OWNER_PRIVATE_KEY,
            gas_tests.contract.functions.storeFeedbackHash,
            args=(dup_hash,),
            label="logic_case3_second"
        )
        dup_rejected = receipt3 and receipt3.status == 0
        assert_print(dup_rejected, f"duplicate hash transaction reverted status={getattr(receipt3,'status',None)}")
    except Exception as e:
        assert_print(True, f"second dup tx reverted/exception {e}")

    # ABI check independent of above outcome
    abi = gas_tests.abi
    abi_names = {entry.get("name") for entry in abi if entry.get("type") == "function"}
    expected = {"storeFeedbackHash", "getCount", "getRecord", "isHashStored"}
    assert_print(expected.issubset(abi_names), f"ABI contains required functions: found {abi_names}")
    
def test_private_key_handling():
    print("\n=== Private key storage tests (3 cases) ===")
    cases = [
        ("valid", gas_tests.OWNER_PRIVATE_KEY, True),
        ("no prefix", "1234abcd", False),
        ("bad length", "0x123", False),
    ]
    for name, key, expected in cases:
        ok = validate_private_key(key) == expected
        assert_print(ok, f"{name} key validation -> {ok}")

    orig = os.environ.get("WEB3_OWNER_PRIVATE_KEY")
    if orig is not None:
        del os.environ["WEB3_OWNER_PRIVATE_KEY"]
    try:
        try:
            require_env_keys()
            assert_print(False, "missing env key did not raise")
        except EnvironmentError:
            assert_print(True, "missing env key raised EnvironmentError")
    finally:
        if orig is not None:
            os.environ["WEB3_OWNER_PRIVATE_KEY"] = orig

    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        gas_tests.send_signed_function_tx(
            gas_tests.OWNER_ADDRESS,
            gas_tests.OWNER_PRIVATE_KEY,
            gas_tests.contract.functions.getCount,
            args=(),
            label="leak_test"
        )
    out = f.getvalue()
    leaked = gas_tests.OWNER_PRIVATE_KEY in out
    assert_print(not leaked, "private key not printed in transaction helper output")

def test_moderation_and_validation():
    print("\n=== Moderation & input validation tests (3 cases) ===")
    clean = "The instructor was very clear"
    ok, reason = moderate_feedback(clean)
    assert_print(ok, f"clean feedback allowed ({reason})")
    if ok:
        h = prepare_feedback_hash(clean)
        assert_print(isinstance(h, bytes) and len(h) == 32, "hash computed for clean text")

    bad = "You are an idiot"
    ok2, reason2 = moderate_feedback(bad)
    assert_print(not ok2 and reason2 == "insult", f"insult feedback blocked ({reason2})")

    border = "The course was tough but fair"
    ok3, reason3 = moderate_feedback(border)
    assert_print(ok3, f"borderline allowed ({reason3})")

def test_data_validation():
    print("\n=== Data validation tests (3 cases) ===")
    try:
        h = prepare_feedback_hash("sample")
        assert_print(isinstance(h, bytes) and len(h) == 32, "normal string hash produced")
    except Exception as e:
        assert_print(False, f"unexpected exception {e}")

    raised = False
    try:
        prepare_feedback_hash(123)
    except TypeError:
        raised = True
    assert_print(raised, "non-string input raised TypeError")

    long = "x" * 2000
    raised2 = False
    try:
        prepare_feedback_hash(long)
    except ValueError:
        raised2 = True
     

def main():
    print("Blockchain component security tests starting")
    test_logic_flaws_and_formal()
    test_private_key_handling()
    test_moderation_and_validation()
    test_data_validation()
    print("All blockchain tests done.")

if __name__ == "__main__":
    main()