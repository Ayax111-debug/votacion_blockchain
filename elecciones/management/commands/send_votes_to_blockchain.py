"""
Django management command to process pending votes and send them to blockchain.

Usage:
    python manage.py send_votes_to_blockchain [--count 10]
    python manage.py send_votes_to_blockchain --all
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from elecciones.models import Voto
from elecciones.web3_utils import VotingBlockchain, VOTING_REGISTRY_ABI
import os
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process pending votes and send commitments to blockchain'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=10,
            help='Number of pending votes to process (default: 10)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all pending votes'
        )
        parser.add_argument(
            '--voto-id',
            type=str,
            help='Process a specific vote by ID'
        )
    
    def handle(self, *args, **options):
        try:
            # Initialize blockchain connection
            rpc_url = os.getenv('BLOCKCHAIN_RPC_URL', 'https://polygon-rpc.com')
            private_key = os.getenv('BLOCKCHAIN_PRIVATE_KEY')
            contract_address = os.getenv('VOTING_REGISTRY_ADDRESS')
            
            if not private_key:
                raise CommandError("BLOCKCHAIN_PRIVATE_KEY environment variable not set. Add to .env file.")
            if not contract_address:
                raise CommandError("VOTING_REGISTRY_ADDRESS environment variable not set. Deploy contract first.")
            
            blockchain = VotingBlockchain(rpc_url, private_key, contract_address, VOTING_REGISTRY_ABI)
            self.stdout.write(f"✓ Connected to blockchain: {blockchain.get_account_address()}")
            balance = blockchain.get_balance()
            self.stdout.write(f"  Account balance: {balance['matic']:.6f} MATIC")
            
            # Determine which votes to process
            if options['voto_id']:
                votos = Voto.objects.filter(id=options['voto_id'], onchain_status='pending')
                if not votos.exists():
                    raise CommandError(f"Vote {options['voto_id']} not found or not pending")
            else:
                votos = Voto.objects.filter(onchain_status='pending')
                
                if options['all']:
                    count = votos.count()
                else:
                    count = options['count']
                    votos = votos[:count]
            
            total = votos.count()
            if total == 0:
                self.stdout.write("✓ No pending votes to process")
                return
            
            self.stdout.write(f"\nProcessing {total} pending vote(s)...\n")
            
            processed = 0
            failed = 0
            
            for voto in votos:
                try:
                    if not voto.commitment:
                        self.stdout.write(
                            f"  ⚠ Vote {str(voto.id)[:8]}... has no commitment, skipping"
                        )
                        continue
                    
                    self.stdout.write(
                        f"  → Sending vote {str(voto.id)[:8]}... (commitment: {voto.commitment[:10]}...)"
                    )
                    
                    # Send to blockchain
                    result = blockchain.send_commitment_to_chain(voto.commitment, wait_for_receipt=True)
                    
                    # Update vote record
                    voto.onchain_status = result['status']
                    voto.tx_hash = result['tx_hash']
                    if result['block_number']:
                        voto.block_number = result['block_number']
                    voto.save()
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ Success! Block #{result['block_number']}, "
                            f"TxHash: {result['tx_hash'][:10]}..."
                        )
                    )
                    processed += 1
                
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ✗ Failed: {str(e)}"
                        )
                    )
                    voto.onchain_status = 'failed'
                    voto.save()
                    failed += 1
            
            self.stdout.write("\n" + "="*60)
            self.stdout.write(self.style.SUCCESS(
                f"✓ Processing complete: {processed} sent, {failed} failed"
            ))
        
        except Exception as e:
            raise CommandError(f"Blockchain operation failed: {str(e)}")
