import binascii
import json
import base64
import hashlib
import logging
from typing import Dict, TypedDict

from algosdk.v2client.algod import AlgodClient
from algosdk.future.transaction import AssetConfigTxn

from algodao.helpers import wait_for_confirmation

log = logging.getLogger(__name__)

PendingTransactionInfo = TypedDict(
    'PendingTransactionInfo',
    {
        'asset-index': int,
    }
)

def createmetadata(
        name: str,
        description: str,
        properties: Dict,
        extra_metadata_str: str,
):
    """Create metadata compatible with ARC-3"""
    extra_metadata = base64.b64encode(extra_metadata_str.encode())
    return {
        'name': name,
        'description': description,
        'properties': properties,
        'extra_metadata': extra_metadata.decode(),
    }

def createasset(
        client: AlgodClient,
        accountaddr: str,
        privkey: str,
        metadata: Dict,
        count: int,
        unitname: str,
        assetname: str,
        url: str,
):
    log.info(f'Creating asset {assetname}')
    params = client.suggested_params()
    metadata_str = json.dumps(metadata)
    # for our purposes, require extra_metadata to always be included and then
    # follow the ARC-3 standard, even if it's just an empty string
    # See ARC-3 python sample for including extra metadata:
    # https://github.com/algorandfoundation/ARCs/blob/main/ARCs/arc-0003.md
    try:
        extra_metadata: bytes = base64.b64decode(metadata['extra_metadata'])
    except binascii.Error:
        msg = "extra_metadata is not valid base64 encoded: {}".format(
            metadata['extra_metadata']
        )
        log.exception(msg)
        raise Exception(msg)
    except ValueError:
        msg = "extra_metadata key not found"
        log.exception(msg)
        raise Exception(msg)
    h = hashlib.new("sha512_256")
    h.update(b"arc0003/amj")
    h.update(metadata_str.encode("utf-8"))
    json_metadata_hash = h.digest()
    h = hashlib.new("sha512_256")
    h.update(b"arc0003/am")
    h.update(json_metadata_hash)
    h.update(extra_metadata)
    metadata_hash = h.digest()
    # alternative example without extra_metadata
    # (from https://replit.com/@Algorand/CreateNFTPython#main.py)
    # hash = hashlib.new("sha512_256")
    # hash.update(b"arc0003/amj")
    # hash.update(metadata_str.encode("utf-8"))
    # metadata_hash = hash.digest()
    txn = AssetConfigTxn(
        sender=accountaddr,
        sp=params,
        total=count,
        default_frozen=False,
        unit_name=unitname,
        asset_name=assetname,
        manager=accountaddr,
        reserve=None,
        freeze=None,
        clawback=None,
        strict_empty_address_check=False,
        url=url,
        metadata_hash=metadata_hash,
        decimals=0,
    )
    signed = txn.sign(privkey)
    txid = client.send_transaction(signed)
    wait_for_confirmation(client, txid)
    try:
        ptx: PendingTransactionInfo = client.pending_transaction_info(txid)
        print(ptx)
        assetid = ptx['asset-index']
        printcreatedasset(client, accountaddr, assetid)
        printassetholding(client, accountaddr, assetid)
    except:
        log.exception("Could not extract created asset info")
        raise


def printcreatedasset(client: AlgodClient, accountaddr: str, assetid: int):
    pass


def printassetholding(client: AlgodClient, accountaddr: str, assetid: int):
    pass


