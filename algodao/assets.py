import binascii
import json
import base64
import hashlib
import logging
from typing import Dict

import algosdk.future.transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.future.transaction import AssetConfigTxn
import pyteal
from pyteal import App, Seq, Bytes, Btoi, Txn, Int, Assert, Return, AssetHolding
from pyteal import Cond, Global

import algodao.deploy
from algodao.helpers import wait_for_confirmation
from algodao.types import PendingTransactionInfo, AccountInfo

log = logging.getLogger(__name__)


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
) -> int:
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
        log.info(ptx)
        assetid = ptx['asset-index']
        printcreatedasset(client, accountaddr, assetid)
        printassetholding(client, accountaddr, assetid)
    except:
        log.exception("Could not extract created asset info")
        raise
    return assetid


def hasasset(client: AlgodClient, addr: str, assetid: int):
    info: AccountInfo = client.account_info(addr)
    for asset in info['assets']:
        if asset['asset-id'] == assetid:
            return True
    return False


def printcreatedasset(client: AlgodClient, accountaddr: str, assetid: int):
    pass


def printassetholding(client: AlgodClient, accountaddr: str, assetid: int):
    pass


class NftCheckProgram:
    def approval_program(self):
        on_creation = Seq(
            [
                Assert(Txn.application_args.length() == Int(1)),
                App.globalPut(Bytes("AssetId"), Btoi(Txn.application_args[0])),
                Return(Int(1)),
            ]
        )
        is_creator = Txn.sender() == Global.creator_address()
        assetbalance = AssetHolding.balance(
            Txn.sender(),
            App.globalGet(Bytes("AssetId"))
        )
        on_run = Seq(
            assetbalance,
            Assert(assetbalance.hasValue()),
            Assert(assetbalance.value() > Int(0)),
            Return(Int(1))
        )
        program = Cond(
            [Txn.application_id() == Int(0), on_creation],
            [Int(1) == Int(1), on_run],
        )
        return program

    def deploy(self, client: AlgodClient, assetid: int, privkey: str):
        program = self.approval_program()
        teal = pyteal.compileTeal(
            program,
            mode=pyteal.Mode.Application,
            version=4
        )
        compiled = algodao.deploy.compile_program(client, teal)
        args = [assetid.to_bytes(8, 'big')]
        clear_program = Return(Int(1))
        clear_program_compiled = algodao.deploy.compile_program(
            client,
            pyteal.compileTeal(
                clear_program,
                mode=pyteal.Mode.Application,
                version=4
            )
        )
        global_schema = algosdk.future.transaction.StateSchema(1, 0)
        local_schema = algosdk.future.transaction.StateSchema(0, 0)
        appid = algodao.deploy.create_app(
            client,
            privkey,
            compiled,
            clear_program_compiled,
            global_schema,
            local_schema,
            args
        )
        return appid
