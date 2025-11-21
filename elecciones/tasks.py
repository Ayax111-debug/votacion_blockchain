"""
Celery tasks for blockchain vote submission.
"""

import os
from pathlib import Path
from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
import logging

# Load .env at module level
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_vote_to_blockchain(self, voto_id):
    """
    Async task to send a vote commitment to blockchain.
    If blockchain is not configured or RPC is unreachable,
    marks vote as 'simulated' for demo purposes.
    """
    try:
        from .models import Voto
        from .web3_utils import create_voting_blockchain
        import uuid
        
        # Fetch the vote
        try:
            voto = Voto.objects.get(id=voto_id)
        except ObjectDoesNotExist:
            logger.error(f"Vote {voto_id} not found")
            return
        
        # Skip if already processed or no commitment
        if voto.onchain_status in ('confirmed', 'sent') or not voto.commitment:
            logger.info(f"Vote {voto_id} already processed or no commitment")
            return
        
        logger.info(f"Processing vote {voto_id} with commitment {voto.commitment[:10]}...")
        
        # Try to initialize blockchain connection
        try:
            blockchain = create_voting_blockchain()
            
            # Send commitment to chain
            result = blockchain.send_commitment_to_chain(voto.commitment, wait_for_receipt=True)
            
            # Update vote with result
            voto.onchain_status = result['status']
            voto.tx_hash = result['tx_hash']
            if result.get('block_number'):
                voto.block_number = result['block_number']
            voto.save()
            
            logger.info(
                f"Vote {voto_id} sent successfully. "
                f"TxHash: {result['tx_hash']}, Block: {result.get('block_number')}"
            )
            return f"Success: {result['tx_hash']}"
            
        except ValueError as e:
            # Blockchain not configured
            logger.warning(f"Blockchain not configured: {str(e)}")
            # For demo purposes, mark as simulated
            voto.onchain_status = 'simulated'
            voto.tx_hash = f"0x{uuid.uuid4().hex[:32]}"  # Fake tx hash for demo
            voto.block_number = 999999  # Fake block number
            voto.save()
            
            logger.info(f"Vote {voto_id} marked as simulated (demo mode)")
            return "Simulated (demo mode - blockchain not configured)"
        
        except Exception as e:
            logger.warning(f"Failed to send vote {voto_id}: {str(e)}")
            # Retry with exponential backoff
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
    
    except Exception as e:
        logger.error(f"Task error for vote {voto_id}: {str(e)}")
        # Final failure: mark as failed
        try:
            from .models import Voto
            voto = Voto.objects.get(id=voto_id)
            voto.onchain_status = 'failed'
            voto.save()
        except Exception:
            pass
            pass
        raise
