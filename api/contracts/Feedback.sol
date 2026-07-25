// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract Feedback {
    address public immutable owner;

    struct FeedbackRecord {
        bytes32 feedbackHash;   // 32 bytes -> 1 slot
        // pack address (20 bytes) + uint32 timestamp (4 bytes) -> fits together in one slot
        address submittedBy;
        uint32 timestamp;
    }

    FeedbackRecord[] public records;

    // new mapping to prevent duplicates
    mapping(bytes32 => bool) private storedHashes;

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function storeFeedbackHash(bytes32 _hash) external onlyOwner {
        require(_hash != bytes32(0), "Invalid hash");         // validation
        require(!storedHashes[_hash], "Duplicate hash");      // logic flaw mitigation

        storedHashes[_hash] = true;
        records.push(FeedbackRecord(_hash, msg.sender, uint32(block.timestamp)));
    }

    function getCount() external view returns (uint256) {
        return records.length;
    }

    function getRecord(uint256 index) external view returns (bytes32, uint32, address) {
        FeedbackRecord storage r = records[index];
        return (r.feedbackHash, r.timestamp, r.submittedBy);
    }

    // helper added for off‑chain verification
    function isHashStored(bytes32 _hash) external view returns (bool) {
        return storedHashes[_hash];
    }
}