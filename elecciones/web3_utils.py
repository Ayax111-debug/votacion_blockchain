"""
Web3 utilities for Blockchain integration with Polygon Amoy testnet.
Handles commitment generation and on-chain vote storage.
"""

import os
from pathlib import Path
from web3 import Web3
from eth_utils import keccak
from typing import Tuple, Dict, Any
import time

# Load .env at module level to ensure environment variables are available
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass


class VotingBlockchain:
    """
    Handles all blockchain operations for the voting system.
    Commits votes as keccak256 hashes on Polygon Amoy testnet.
    """
    
    def __init__(self, rpc_url: str, private_key: str, contract_address: str, contract_abi: list):
        """
        Initialize blockchain connection and contract interface.
        
        Args:
            rpc_url: Polygon Amoy RPC endpoint
            private_key: Server wallet private key (hex string, no '0x' prefix)
            contract_address: Deployed VotingRegistry contract address
            contract_abi: Contract ABI (JSON)
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to RPC: {rpc_url}")
        
        self.private_key = private_key if private_key.startswith('0x') else f'0x{private_key}'
        self.account = self.w3.eth.account.from_key(self.private_key)
        self.contract_address = Web3.to_checksum_address(contract_address)
        self.contract = self.w3.eth.contract(address=self.contract_address, abi=contract_abi)
        self.chain_id = self.w3.eth.chain_id
    
    @staticmethod
    def generate_commitment(voter_secret: str, evento_id: str, candidato_id: str, server_salt: str = "VOTING_SALT_2025") -> str:
        """
        Generate a keccak256 commitment hash for the vote.
        Privacy-preserving: voter secret is never stored, only its commitment.
        
        Args:
            voter_secret: Secret string known only to voter (e.g., 6-digit PIN)
            evento_id: UUID of the election event
            candidato_id: UUID of the candidate receiving the vote
            server_salt: Server-side salt for additional entropy
        
        Returns:
            0x-prefixed keccak256 hex hash string
        """
        # Concatenate all components
        combined = f"{voter_secret}:{evento_id}:{candidato_id}:{server_salt}"
        
        # Compute keccak256
        commitment_hash = keccak(text=combined)
        
        # Return as 0x-prefixed hex string (66 chars including 0x)
        return "0x" + commitment_hash.hex()
    
    def send_commitment_to_chain(self, commitment: str, wait_for_receipt: bool = True, timeout: int = 120) -> Dict[str, Any]:
        """
        Send commitment to blockchain via VotingRegistry.storeCommitment.
        Transaction is signed with server wallet.
        
        Args:
            commitment: Keccak256 commitment hash (0x-prefixed)
            wait_for_receipt: If True, wait for confirmation before returning
            timeout: Max seconds to wait for receipt
        
        Returns:
            Dict with tx_hash, block_number, gas_used, status ('success'/'failed'), and receipt
        
        Raises:
            ValueError: If commitment is invalid format
            Exception: If transaction fails or times out
        """
        if not commitment.startswith('0x') or len(commitment) != 66:
            raise ValueError(f"Invalid commitment format. Expected 66 chars (0x...), got {len(commitment)}")
        
        try:
            # Get current nonce and gas price
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            gas_price = self.w3.eth.gas_price
            
            # Build transaction to call storeCommitment
            tx = self.contract.functions.storeCommitment(commitment).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': 100000,  # Estimated for storeCommitment call
                'chainId': self.chain_id,
            })
            
            # Sign transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)

            # Compatibility: web3.py v5 used 'rawTransaction', v6 uses 'raw_transaction'
            raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)
            if raw_tx is None:
                raise Exception("SignedTransaction object missing raw transaction bytes")

            # Send transaction
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            print(f"✓ Transaction sent: {tx_hash.hex()}")
            
            if not wait_for_receipt:
                return {
                    'tx_hash': tx_hash.hex(),
                    'block_number': None,
                    'gas_used': None,
                    'status': 'sent',
                    'receipt': None
                }
            
            # Wait for receipt (confirmation)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            print(f"✓ Receipt confirmed at block {receipt['blockNumber']}")

            status = 'success' if receipt['status'] == 1 else 'failed'

            if status == 'failed':
                # Decode logs if available
                decoded_logs = []
                for log in receipt['logs']:
                    try:
                        decoded_log = self.contract.events.CommitmentStored().process_log(log)
                        decoded_logs.append(decoded_log)
                    except Exception as e:
                        print(f"✗ Failed to decode log: {str(e)}")

                # Log raw logs if decoding fails
                raw_logs = [log for log in receipt['logs']]
                print(f"✗ Failed to decode logs. Raw logs: {raw_logs}")

                print(f"✗ Transaction failed with receipt: {receipt}, decoded_logs: {decoded_logs}")

            return {
                'tx_hash': receipt['transactionHash'].hex(),
                'block_number': receipt['blockNumber'],
                'gas_used': receipt['gasUsed'],
                'status': status,
                'receipt': receipt
            }
        
        except Exception as e:
            print(f"✗ Transaction failed: {str(e)}")
            raise
    
    def verify_commitment_onchain(self, commitment: str) -> Tuple[bool, int]:
        """
        Verify if a commitment exists on-chain and get its block number.
        
        Args:
            commitment: Keccak256 commitment hash (0x-prefixed)
        
        Returns:
            Tuple (exists: bool, block_number: int)
        """
        try:
            exists = self.contract.functions.hasCommitment(commitment).call()
            
            if exists:
                block_number = self.contract.functions.getCommitmentBlock(commitment).call()
                return (True, block_number)
            else:
                return (False, None)
        
        except Exception as e:
            print(f"Error verifying commitment: {str(e)}")
            return (False, None)
    
    def get_account_address(self) -> str:
        """Get the server wallet public address."""
        return self.account.address
    
    def get_balance(self) -> Dict[str, Any]:
        """Get server wallet balance in MATIC and wei."""
        wei_balance = self.w3.eth.get_balance(self.account.address)
        matic_balance = self.w3.from_wei(wei_balance, 'ether')
        return {
            'wei': wei_balance,
            'matic': float(matic_balance)
        }


# Contract ABI (placeholder - will be replaced with actual compiled ABI)
VOTING_REGISTRY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "commitment",
                "type": "bytes32"
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "blockNumber",
                "type": "uint256"
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "sender",
                "type": "address"
            }
        ],
        "name": "CommitmentStored",
        "type": "event"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32"
            }
        ],
        "name": "commitmentBlock",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32"
            }
        ],
        "name": "commitmentSender",
        "outputs": [
            {
                "internalType": "address",
                "name": "",
                "type": "address"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32"
            }
        ],
        "name": "committed",
        "outputs": [
            {
                "internalType": "bool",
                "name": "",
                "type": "bool"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "c",
                "type": "bytes32"
            }
        ],
        "name": "getCommitmentBlock",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "c",
                "type": "bytes32"
            }
        ],
        "name": "getCommitmentSender",
        "outputs": [
            {
                "internalType": "address",
                "name": "",
                "type": "address"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "c",
                "type": "bytes32"
            }
        ],
        "name": "hasCommitment",
        "outputs": [
            {
                "internalType": "bool",
                "name": "",
                "type": "bool"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "c",
                "type": "bytes32"
            }
        ],
        "name": "storeCommitment",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


def create_voting_blockchain() -> VotingBlockchain:
    """
    Factory function to create VotingBlockchain instance from environment variables.
    
    Required environment variables:
    - BLOCKCHAIN_RPC_URL: Polygon Amoy RPC endpoint
    - BLOCKCHAIN_PRIVATE_KEY: Server wallet private key
    - VOTING_REGISTRY_ADDRESS: Deployed contract address
    
    Returns:
        VotingBlockchain instance
    """
    rpc_url = os.getenv('BLOCKCHAIN_RPC_URL', 'https://polygon-rpc.com')
    private_key = os.getenv('BLOCKCHAIN_PRIVATE_KEY')
    contract_address = os.getenv('VOTING_REGISTRY_ADDRESS')
    
    if not private_key:
        raise ValueError("BLOCKCHAIN_PRIVATE_KEY environment variable not set")
    if not contract_address:
        raise ValueError("VOTING_REGISTRY_ADDRESS environment variable not set")
    
    return VotingBlockchain(rpc_url, private_key, contract_address, VOTING_REGISTRY_ABI)
