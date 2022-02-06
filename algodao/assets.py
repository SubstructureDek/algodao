import abc
import binascii
import enum
import json
import base64
import hashlib
import logging
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Union

import pyteal
import algosdk.logic
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from pyteal import App, Seq, Bytes, Btoi, Txn, Int, Assert, Return, AssetHolding
from pyteal import Cond, Global, Mode, InnerTxnBuilder, TxnField, TxnType
from pyteal import InnerTxn, And, ScratchVar, TealType, Sha256, Concat
from pyteal import OnComplete, Len, For, If, Substring, Expr

import algodao.deploy
from algodao.contract import CreateContract, DeployedContract, GlobalVariables, LocalVariables
from algodao.helpers import wait_for_confirmation
from algodao.merkle import MerkleTree
from algodao.types import PendingTransactionInfo, AccountInfo

log = logging.getLogger(__name__)


class Token(abc.ABC):
    @property
    @abc.abstractmethod
    def asset_id(self) -> int:
        """Returns the associated asset ID"""
        pass


class ElectionToken(Token):
    def __init__(self, asset_id: int):
        self._asset_id: int = asset_id

    @property
    def asset_id(self) -> int:
        return self._asset_id


class GovernanceToken(Token):
    def __init__(self, asset_id: int):
        self._asset_id: int = asset_id

    @property
    def asset_id(self) -> int:
        return self._asset_id


class TokenDistributionTree:
    class GlobalInts(GlobalVariables):
        RegBegin = enum.auto()
        RegEnd = enum.auto()
        AssetId = enum.auto()

    class GlobalBytes(GlobalVariables):
        RootHash = enum.auto()

    class CreateTree(CreateContract):
        def __init__(
                self,
                token: Token,
                addr2count: OrderedDict[str, int],
                beginreg: int,
                endreg: int,
        ):
            self._token = token
            self._addr2count = addr2count
            # note that for simplicity in the teal contract, the count here is
            # represented in its uint64 bytes representation rather than a human
            # readable representation; e.g., if address 'abcd' is assigned a
            # count of 8, the leaf value that is hashed is:
            # b'abcd:\x00\x00\x00\x00\x00\x00\x00\x10'
            inputs: List[bytes] = [
                f'{address}:'.encode('utf-8') + algodao.helpers.int2bytes(count)
                for address, count in self._addr2count.items()
            ]
            self._tree = MerkleTree(inputs)
            self._beginreg: int = beginreg
            self._endreg: int = endreg
            super(TokenDistributionTree.CreateTree, self).__init__()

        def local_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(0, 0)

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(
                len(TokenDistributionTree.GlobalInts),
                len(TokenDistributionTree.GlobalBytes)
            )

        def createapp_args(self) -> List[bytes]:
            return [
                self._tree.roothash,
                algodao.helpers.int2bytes(self._beginreg),
                algodao.helpers.int2bytes(self._endreg),
            ]

        def approval_program(self) -> Expr:
            # creation arguments: RootHash, RegBegin, RegEnd
            # Claim arguments: address, vote count, Merkle index, Merkle proof
            GlobalInts = TokenDistributionTree.GlobalInts
            GlobalBytes = TokenDistributionTree.GlobalBytes
            on_creation = Seq([
                Assert(Txn.application_args.length() == Int(3)),
                GlobalBytes.RootHash.put(Txn.application_args[0]),
                GlobalInts.RegBegin.put(Btoi(Txn.application_args[1])),
                GlobalInts.RegEnd.put(Btoi(Txn.application_args[2])),
                GlobalInts.AssetId.put(Int(0)),
                Return(Int(1)),
            ])
            is_creator = Txn.sender() == Global.creator_address()
            on_optintoken = Seq([
                Assert(is_creator),
                Assert(Txn.application_args.length() == Int(2)),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.xfer_asset: Btoi(Txn.application_args[1]),
                    TxnField.asset_amount: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                GlobalInts.AssetId.put(Int(self._token.asset_id)),
                Return(Int(1)),
            ])
            on_inittoken = Seq([
                Assert(is_creator),
                Assert(Txn.application_args.length() == Int(5)),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_total: Btoi(Txn.application_args[1]),
                    TxnField.config_asset_unit_name: Txn.application_args[2],
                    TxnField.config_asset_name: Txn.application_args[3],
                    TxnField.config_asset_url: Txn.application_args[4],
                    TxnField.config_asset_manager: Global.current_application_address(),
                }),
                InnerTxnBuilder.Submit(),
                GlobalInts.AssetId.put(InnerTxn.created_asset_id()),
                Return(Int(1)),
            ])
            on_closeout = Return(Int(1))
            on_register = Return(
                And(
                    Global.round() >= App.globalGet(Bytes("RegBegin")),
                    Global.round() <= App.globalGet(Bytes("RegEnd")),
                )
            )
            address = Txn.application_args[1]  # bytes
            count = Txn.application_args[2]  # bytes representation of a uint64
            index = Btoi(Txn.application_args[3])  # uint64
            proof = Txn.application_args[4]  # bytes
            runninghash = ScratchVar(TealType.bytes)
            on_claim = Seq([
                Assert(
                    And(
                        Txn.application_args.length() == Int(5),
                        Global.round() >= GlobalInts.RegBegin.get(),
                        Global.round() <= GlobalInts.RegEnd.get(),
                    )
                ),
                runninghash.store(Sha256(Concat(address, Bytes(':'), count))),
                self.verifymerkle(index, proof, runninghash, GlobalBytes.RootHash.get()),
                self.transferelectiontokens(Btoi(count)),
                Return(Int(1)),
            ])
            program = Cond(
                [Txn.application_id() == Int(0), on_creation],
                [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_creator)],
                [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_creator)],
                [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
                [Txn.on_completion() == OnComplete.OptIn, on_register],
                [Txn.application_args[0] == Bytes("claim"), on_claim],
                [Txn.application_args[0] == Bytes('inittoken'), on_inittoken],
                [Txn.application_args[0] == Bytes('optintoken'), on_optintoken],
            )
            return program

        def clear_program(self) -> Expr:
            return Return(Int(1))

        def verifymerkle(self, index: Expr, proof: Expr, runninghash: ScratchVar, roothash: Expr):
            i = ScratchVar(TealType.uint64)
            levelindex = ScratchVar(TealType.uint64)
            return Seq([
                Assert(Len(proof) % Int(32) == Int(0)),
                levelindex.store(index),
                For(
                    i.store(Int(0)),
                    i.load() < Len(proof),
                    i.store(i.load() + Int(32))
                ).Do(
                    Seq([
                        If(
                            levelindex.load() % Int(2) == Int(0),
                            runninghash.store(Sha256(Concat(
                                runninghash.load(),
                                Substring(proof, i.load(), i.load() + Int(32)),
                            ))),
                            runninghash.store(Sha256(Concat(
                                Substring(proof, i.load(), i.load() + Int(32)),
                                runninghash.load()
                            )))
                        ),
                        levelindex.store(levelindex.load() / Int(2)),
                    ])
                ),
                Assert(runninghash.load() == roothash)
            ])

        def transferelectiontokens(self, count) -> Expr:
            return Seq([
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: App.globalGet(Bytes("AssetId")),
                    TxnField.asset_receiver: Txn.sender(),
                    TxnField.asset_amount: count,
                }),
                InnerTxnBuilder.Submit(),
            ])

    class DeployedTree(DeployedContract):
        def __init__(self, appid: int, addr2count: OrderedDict[str, int], tree: MerkleTree):
            self._addr2count = addr2count
            self._tree = tree
            super(TokenDistributionTree.DeployedTree, self).__init__(appid)

        def call_inittoken(
                self,
                algod: AlgodClient,
                addr: str,
                privkey: str,
                assetcount: int,
                unitname: str,
                assetname: str,
                asseturl: str
        ) -> int:
            info = self.call_method(
                algod,
                addr,
                privkey,
                b'inittoken',
                [
                    algodao.helpers.int2bytes(assetcount),
                    unitname.encode(),
                    assetname.encode(),
                    asseturl.encode(),
                ],
            )
            self._token = ElectionToken(info['inner-txns'][0]['asset-index'])
            return self._token.asset_id
    
        def call_optintoken(self, algod: AlgodClient, addr: str, privkey: str) -> dict:
            return self.call_method(
                algod,
                addr,
                privkey,
                b'optintoken',
                [
                    algodao.helpers.int2bytes(self._token.asset_id),
                ],
                foreign_assets=[self._token.asset_id]
            )

        def call_claim(self, algod: AlgodClient, addr: str, privkey: str):
            assert addr in self._addr2count
            index = list(self._addr2count.keys()).index(addr)
            proof: List[bytes] = self._tree.createproof(index)
            count: int = self._addr2count[addr]
            # concatenate all the proof hashes together. the contract will index
            # into the byte array as appropriate while stepping through the proof
            proof_bytes: bytes = b''.join(proof)
            return self.call_method(
                algod,
                addr,
                privkey,
                b'claim',
                [
                    addr.encode('utf-8'),
                    algodao.helpers.int2bytes(count),
                    algodao.helpers.int2bytes(index),
                    proof_bytes
                ],
                foreign_assets=[self._token.asset_id],
            )

    @classmethod
    def deploy(cls, algod: AlgodClient, createtree: CreateTree, privkey: str):
        appid = createtree.deploy(algod, privkey)
        return TokenDistributionTree.DeployedTree(appid, createtree._addr2count, createtree._tree)


class NftCheckProgram:
    def approval_program(self) -> Expr:
        on_creation = Seq(
            [
                Assert(Txn.application_args.length() == Int(1)),
                App.globalPut(Bytes("AssetId"), Btoi(Txn.application_args[0])),
                Return(Int(1)),
            ]
        )
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
    txn = transaction.AssetConfigTxn(
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
    ptx: PendingTransactionInfo = client.pending_transaction_info(txid)
    log.info(ptx)
    assetid = ptx['asset-index']
    return assetid


def hasasset(client: AlgodClient, addr: str, assetid: int):
    info: AccountInfo = client.account_info(addr)
    for asset in info['assets']:
        if asset['asset-id'] == assetid:
            return True
    return False
