// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title VotingRegistry
 * @dev Simple contract to store vote commitments on-chain for voting application
 * Commitments are hash(voter_secret | evento_id | candidato_id | server_salt)
 * This preserves vote privacy while providing on-chain audit trail
 */
contract VotingRegistry {
    mapping(bytes32 => bool) public committed;
    mapping(bytes32 => uint256) public commitmentBlock;
    mapping(bytes32 => address) public commitmentSender;
    
    event CommitmentStored(bytes32 indexed commitment, uint256 blockNumber, address indexed sender);

    /**
     * @dev Store a vote commitment on-chain
     * @param c The commitment hash (keccak256 of vote data)
     */
    function storeCommitment(bytes32 c) public {
        require(!committed[c], "Commitment already exists");
        require(c != bytes32(0), "Invalid commitment");
        
        committed[c] = true;
        commitmentBlock[c] = block.number;
        commitmentSender[c] = msg.sender;
        
        emit CommitmentStored(c, block.number, msg.sender);
    }

    /**
     * @dev Check if a commitment exists
     * @param c The commitment hash to check
     */
    function hasCommitment(bytes32 c) public view returns (bool) {
        return committed[c];
    }

    /**
     * @dev Get block number where commitment was stored
     * @param c The commitment hash
     */
    function getCommitmentBlock(bytes32 c) public view returns (uint256) {
        return commitmentBlock[c];
    }

    /**
     * @dev Get sender address that submitted commitment
     * @param c The commitment hash
     */
    function getCommitmentSender(bytes32 c) public view returns (address) {
        return commitmentSender[c];
    }
}
