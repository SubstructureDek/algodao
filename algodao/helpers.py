import base64
import logging
import os

import algosdk
import pyteal
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from pyteal import Mode

log = logging.getLogger(__name__)


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


def algodclient_purestake() -> AlgodClient:
    algod_address = "https://mainnet-algorand.api.purestake.io/ps2"
    token = os.getenv('PURESTAKE_API_TOKEN')
    headers = {
        'X-API-Key': token,
    }
    return AlgodClient(token, algod_address, headers=headers)


def indexer_client() -> IndexerClient:
    """Instantiate and return Indexer client object."""
    indexer_address = "http://localhost:8980"
    indexer_token = 'a' * 64
    return IndexerClient(indexer_token, indexer_address)


def indexer_purestake() -> IndexerClient:
    indexer_address = 'https://mainnet-algorand.api.purestake.io/idx2'
    headers = {
        'X-API-Key': os.getenv('PURESTAKE_API_TOKEN')
    }
    return IndexerClient('', indexer_address, headers)


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


def add_transaction(
        client: AlgodClient,
        sender: str,
        receiver: str,
        privkey: str,
        amount: int,
        note: str
):
    """Create and sign transaction from provided arguments.

    Returned non-empty tuple carries field where error was raised and description.
    If the first item is None then the error is non-field/integration error.
    Returned two-tuple of empty strings marks successful transaction.
    """
    params = client.suggested_params()
    unsigned_txn = transaction.PaymentTxn(
        sender,
        params,
        receiver,
        amount,
        None,
        note.encode()
    )
    signed_txn = unsigned_txn.sign(privkey)
    transaction_id = client.send_transaction(signed_txn)
    wait_for_confirmation(client, transaction_id)
    return transaction_id


def int2bytes(num: int) -> bytes:
    return num.to_bytes(8, "big")


def optinapp(algod: AlgodClient, private_key: str, addr: str, appid: int):
    """Opt-in to an application"""
    log.info(f"Opting {addr} into application {appid}")
    params = algod.suggested_params()
    txn = transaction.ApplicationOptInTxn(addr, params, appid)
    signed = txn.sign(private_key)
    txid = algod.send_transaction(signed)
    wait_for_confirmation(algod, txid)
    # transaction_response = algod.pending_transaction_info(txid)
    # log.info("OptIn to app-id:", transaction_response["txn"]["txn"]["apid"])


def writedryrun(algod, signed, fname):
    drr = transaction.create_dryrun(algod, [signed])
    with open(fname, 'wb') as fp:
        fp.write(base64.b64decode(algosdk.encoding.msgpack_encode(drr)))


def transferasset(
        algod: AlgodClient,
        sendaddr: str,
        sendprivkey: str,
        recvaddr: str,
        assetid: int,
        amount: int
):
    params = algod.suggested_params()
    txn = algosdk.future.transaction.AssetTransferTxn(
        sendaddr,
        params,
        recvaddr,
        amount,
        assetid
    )
    signed = txn.sign(sendprivkey)
    txid = algod.send_transaction(signed)
    wait_for_confirmation(algod, txid)


def optinasset(
        algod: AlgodClient,
        recvaddr: str,
        recvprivkey: str,
        assetid: int
):
    transferasset(algod, recvaddr, recvprivkey, recvaddr, assetid, 0)

