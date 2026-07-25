import json
from pathlib import Path
from solcx import compile_source, install_solc, set_solc_version

BASE_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = BASE_DIR / "Feedback.sol"
ABI_OUT = BASE_DIR / "Feedback.abi.json"
BYTECODE_OUT = BASE_DIR / "Feedback.bytecode.txt"

SOLC_VERSION = "0.8.19"

def main():
    install_solc(SOLC_VERSION)
    set_solc_version(SOLC_VERSION)

    source = CONTRACT_PATH.read_text(encoding="utf-8")

    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
    )

    contract_key = next(k for k in compiled.keys() if k.endswith(":Feedback"))
    contract_interface = compiled[contract_key]

    abi = contract_interface["abi"]
    bytecode = contract_interface["bin"]

    ABI_OUT.write_text(json.dumps(abi, indent=2), encoding="utf-8")
    BYTECODE_OUT.write_text(bytecode, encoding="utf-8")
    print("Saved:", ABI_OUT)
    print("Saved:", BYTECODE_OUT)

if __name__ == "__main__":
    main()