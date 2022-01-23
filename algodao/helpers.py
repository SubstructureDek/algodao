import logging

from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient


def wait_for_confirmation(
        client: AlgodClient,
        transaction_id: str,
        timeout: int = 4
):
    """
    Wait until the transaction is confirmed or rejected, or until 'timeout'
    number of rounds have passed.
    Args:
        client (AlgodClient): an algod client
        transaction_id (str): the transaction to wait for
        timeout (int): maximum number of rounds to wait
    Returns:
        dict: pending transaction information, or throws an error if the
            transaction is not confirmed or rejected in the next timeout rounds
    """
    start_round = client.status()["last-round"] + 1
    current_round = start_round

    while current_round < start_round + timeout:
        try:
            pending_txn = client.pending_transaction_info(transaction_id)
        except Exception:
            return
        if pending_txn.get("confirmed-round", 0) > 0:
            return pending_txn
        elif pending_txn["pool-error"]:
            raise Exception("pool error: {}".format(pending_txn["pool-error"]))
        client.status_after_block(current_round)
        current_round += 1
    raise Exception(
        "pending tx not found in timeout rounds, timeout value = : {}".format(timeout)
    )


def createclient() -> AlgodClient:
    algod_address = 'http://localhost:4001'
    algod_token = 'a' * 64
    return AlgodClient(algod_token, algod_address)


def indexer_client() -> IndexerClient:
    """Instantiate and return Indexer client object."""
    indexer_address = "http://localhost:8980"
    indexer_token = 'a' * 64
    return IndexerClient(indexer_token, indexer_address)


def loggingconfig():
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)