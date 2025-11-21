import os
import django
import logging
from elecciones.models import Voto
from elecciones.web3_utils import VotingBlockchain

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')
django.setup()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_vote_flow(vote_id):
    try:
        # Fetch the vote from the database
        voto = Voto.objects.get(id=vote_id)
        logger.info(f"Vote ID: {voto.id}")
        logger.info(f"Commitment: {voto.commitment}")
        logger.info(f"On-chain Status: {voto.onchain_status}")
        logger.info(f"Transaction Hash: {voto.tx_hash}")

        # Check if the vote has been sent to the blockchain
        if not voto.tx_hash:
            logger.warning("Vote has not been sent to the blockchain.")
            return False

        # Verify the vote on the blockchain
        blockchain = VotingBlockchain()
        is_verified, block_number = blockchain.verify_commitment_onchain(voto.commitment)

        if is_verified:
            logger.info(f"Vote is correctly registered on the blockchain in block {block_number}.")
            return True
        else:
            logger.error("Vote is not registered on the blockchain.")
            return False

    except Voto.DoesNotExist:
        logger.error(f"Vote with ID {vote_id} does not exist.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while checking the vote flow: {str(e)}")
        return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check the flow of a vote.")
    parser.add_argument("vote_id", type=int, help="The ID of the vote to check.")

    args = parser.parse_args()
    vote_id = args.vote_id

    if check_vote_flow(vote_id):
        logger.info("Vote flow is correct.")
    else:
        logger.error("Vote flow has issues.")