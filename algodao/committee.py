"""
Methods for creating and managing committees in the DAO. Committees are defined
to have certain privileges, such as the ability to approve proposals and
distribute treasury funds.
"""
import enum
import logging
from typing import List

import algosdk.encoding
import pyteal
from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from pyteal import Expr, Seq, Assert, App, Bytes, Btoi, Return, Int, Txn, And
from pyteal import Len, Subroutine, TealType, For, ScratchVar
from pyteal import Substring, Concat, Cond, OnComplete, Mode
from pyteal import InnerTxnBuilder, TxnField, TxnType, Global, InnerTxn
from pyteal import AssetHolding, Gtxn


import algodao.deploy
import algodao.helpers
from algodao.contract import GlobalVariables, CreateContract, DeployedContract

log = logging.getLogger(__name__)


@Subroutine(TealType.uint64)
def is_member(asset_id: Expr, address: Expr) -> Expr:
    assetbalance = AssetHolding.balance(address, asset_id)
    return Seq([
        assetbalance,
        Return(And(
            assetbalance.hasValue(),
            assetbalance.value() > Int(0))
        )
    ])


@Subroutine(TealType.uint64)
def current_committee_size_ex(app_id: Expr, app_addr: Expr):
    """
    Find the current number of committee members by subtracting
    the number of assets currently owned by the Committee contract from
    the max members allowed (i.e., the total number of assets
    created).
    """
    assetid = App.globalGetEx(app_id, Bytes("AssetId"))
    maxmembers = App.globalGetEx(app_id, Bytes("MaxMembers"))
    reservebalance = AssetHolding.balance(app_addr, assetid.value())
    return Seq([
        assetid,
        Assert(assetid.hasValue()),
        maxmembers,
        Assert(maxmembers.hasValue()),
        reservebalance,
        Assert(reservebalance.hasValue()),
        Return(maxmembers.value() - reservebalance.value())
    ])


@Subroutine(TealType.none)
def set_asset_freeze(address: Expr, assetid: Expr, frozen: Expr) -> Expr:
    return Seq([
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetFreeze,
            TxnField.freeze_asset_account: address,
            TxnField.freeze_asset_frozen: frozen,
            TxnField.freeze_asset: assetid,
        }),
        InnerTxnBuilder.Submit(),
    ])


@Subroutine(TealType.none)
def send_asset(address: Expr, assetid: Expr):
    return Seq([
       InnerTxnBuilder.Begin(),
       InnerTxnBuilder.SetFields({
           TxnField.type_enum: TxnType.AssetTransfer,
           TxnField.asset_receiver: address,
           TxnField.xfer_asset: assetid,
           TxnField.asset_amount: Int(1),
       }),
       InnerTxnBuilder.Submit(),
    ])


@Subroutine(TealType.none)
def add_member(address: Expr) -> Expr:
    return Seq([
        send_asset(address, App.globalGet(Bytes("AssetId"))),
        set_asset_freeze(address, App.globalGet(Bytes("AssetId")), Int(1)),
    ])


@Subroutine(TealType.none)
def add_members(addresses: Expr) -> Expr:
    index = ScratchVar(TealType.uint64)
    return Seq([
        Assert(Len(addresses) % Int(32) == Int(0)),
        For(
            index.store(Int(0)),
            index.load() < Len(addresses),
            index.store(index.load() + Int(32))
        ).Do(
            add_member(Substring(
                addresses,
                index.load(),
                index.load() + Int(32)
            ))
        ),
    ])


class Committee:
    class GlobalInts(GlobalVariables):
        AssetId = enum.auto()
        MaxMembers = enum.auto()

    class GlobalBytes(GlobalVariables):
        CommitteeName = enum.auto()

    class CreateCommittee(CreateContract):
        def __init__(
                self,
                name: str,
                maxsize: int,
        ):
            self._name: str = name
            self._maxsize: int = maxsize

        def approval_program(self) -> Expr:
            GlobalInts = Committee.GlobalInts
            GlobalBytes = Committee.GlobalBytes
            on_creation = Seq([
                Assert(Txn.application_args.length() == Int(2)),
                GlobalBytes.CommitteeName.put(Txn.application_args[0]),
                GlobalInts.MaxMembers.put(Btoi(Txn.application_args[1])),
                GlobalInts.AssetId.put(Int(0)),
                Return(Int(1)),
            ])
            on_register = Return(Int(1))
            on_inittoken = Seq([
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_total: GlobalInts.MaxMembers.get(),
                    TxnField.config_asset_unit_name: Bytes("CMT"),
                    TxnField.config_asset_name: Concat(
                        GlobalBytes.CommitteeName.get(),
                        Bytes(" Membership")
                    ),
                    TxnField.config_asset_url: Txn.application_args[1],
                    TxnField.config_asset_freeze: Global.current_application_address(),
                    TxnField.config_asset_clawback: Global.current_application_address(),
                    TxnField.config_asset_manager: Global.current_application_address(),
                }),
                InnerTxnBuilder.Submit(),
                GlobalInts.AssetId.put(InnerTxn.created_asset_id()),
                Return(Int(1)),
            ])
            on_optintoken = Seq([
                Assert(Txn.sender() == Global.creator_address()),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.xfer_asset: Btoi(Txn.application_args[1]),
                    TxnField.asset_amount: Int(0),
                }),
                Return(Int(1)),
            ])
            assetbalance = AssetHolding.balance(
                Global.current_application_address(),
                GlobalInts.AssetId.get(),
            )
            on_setmembers = Seq([
                # only allow arbitrary selection of members by creator when no one
                # is yet on the committee
                # TODO: allow addition and removal of committee members according
                # TODO: to DAO charter (e.g., vote)
                Assert(Global.creator_address() == Txn.sender()),
                assetbalance,
                Assert(
                    And(
                        assetbalance.hasValue(),
                        assetbalance.value() == GlobalInts.MaxMembers.get()
                    )
                ),
                add_members(Txn.application_args[1]),
                Return(Int(1)),
            ])
            on_resign = Seq([
                Assert(And(
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(0),
                    Gtxn[1].xfer_asset() == GlobalInts.AssetId.get(),
                    Gtxn[1].asset_amount() == Int(1),
                    Gtxn[1].asset_receiver() == Global.current_application_address(),
                )),
                set_asset_freeze(Txn.sender(), GlobalInts.AssetId.get(), Int(0)),
                Return(Int(1))
            ])
            on_checkmembership = Return(is_member(GlobalInts.AssetId.get(), Txn.sender()))
            return Cond(
                [Txn.application_id() == Int(0), on_creation],
                [Txn.on_completion() == OnComplete.DeleteApplication, Return(Int(0))],
                [Txn.on_completion() == OnComplete.UpdateApplication, Return(Int(0))],
                [Txn.on_completion() == OnComplete.CloseOut, Return(Int(1))],
                [Txn.on_completion() == OnComplete.OptIn, on_register],
                [Txn.application_args[0] == Bytes("resign"), on_resign],
                [Txn.application_args[0] == Bytes("checkmembership"), on_checkmembership],
                [Txn.application_args[0] == Bytes("inittoken"), on_inittoken],
                [Txn.application_args[0] == Bytes("setmembers"), on_setmembers],
                [Txn.application_args[0] == Bytes("optintoken"), on_optintoken],
            )

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(len(Committee.GlobalInts), len(Committee.GlobalBytes))

        def local_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(0, 0)

        def createapp_args(self) -> List[bytes]:
            return [
                self._name.encode(),
                algodao.helpers.int2bytes(self._maxsize),
            ]

        def clear_program(self) -> Expr:
            return Return(Int(1))

    class DeployedCommittee(DeployedContract):
        def __init__(self, appid: int):
            super(Committee.DeployedCommittee, self).__init__(appid)

        def call_resign(self, algod: AlgodClient, privkey: str, addr: str):
            params = algod.suggested_params()
            appaddr = algosdk.logic.get_application_address(self._appid)
            txn1 = transaction.ApplicationNoOpTxn(
                addr,
                params,
                self._appid,
                [b'resign'],
                foreign_assets=[self._assetid],
            )
            txn2 = transaction.AssetTransferTxn(
                addr,
                params,
                appaddr,
                1,
                self._assetid
            )
            groupid = transaction.calculate_group_id([txn1, txn2])
            txn1.group = groupid
            txn2.group = groupid
            signed1 = txn1.sign(privkey)
            signed2 = txn2.sign(privkey)
            txid = algod.send_transactions([signed1, signed2])
            algodao.helpers.wait_for_confirmation(algod, txid)

        def call_checkmembership(self, algod: AlgodClient, privkey: str, addr: str):
            return self.call_method(
                algod,
                addr,
                privkey,
                b'checkmembership',
                [],
                foreign_assets=[self.assetid],
            )

        def call_optintoken(self, algod: AlgodClient, privkey: str, addr: str, assetid: int):
            return self.call_method(
                algod,
                addr,
                privkey,
                b'optintoken',
                [
                    algodao.helpers.int2bytes(assetid),
                ],
                foreign_assets=[assetid],
            )

        def call_setmembers(self, algod: AlgodClient, privkey: str, addr: str, addresses: List[str]):
            addresses_bytes = b''.join(
                algosdk.encoding.decode_address(member)
                for member in addresses
            )
            return self.call_method(
                algod,
                addr,
                privkey,
                b'setmembers',
                [addresses_bytes],
                accounts=addresses,
                foreign_assets=[self.assetid],
            )

        def call_inittoken(self, algod: AlgodClient, privkey: str, addr: str):
            info = self.call_method(
                algod,
                addr,
                privkey,
                b'inittoken',
                [b'http://localhost/my/committee/token'],
            )
            self._assetid = info['inner-txns'][0]['asset-index']
            log.info(f"Created asset ID for committee: {self._assetid}")
            return self._assetid

        @property
        def assetid(self):
            return self._assetid

    @classmethod
    def deploy(cls, algod, createcommittee: CreateCommittee, privkey):
        appid = createcommittee.deploy(algod, privkey)
        return Committee.DeployedCommittee(appid)
