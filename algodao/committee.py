"""
Methods for creating and managing committees in the DAO. Committees are defined
to have certain privileges, such as the ability to approve proposals and
distribute treasury funds.
"""
import logging
from typing import List

import algosdk.encoding
import pyteal
from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from pyteal import Expr, Seq, Assert, App, Bytes, Btoi, Return, Int, Txn, And
from pyteal import Len, Gt, Or, Lt, Subroutine, TealType, For, ScratchVar
from pyteal import Substring, If, Concat, Cond, OnComplete, Mode, Break
from pyteal import InnerTxnBuilder, TxnField, TxnType, Global, InnerTxn
from pyteal import AssetHolding, Gtxn


import algodao.deploy
import algodao.helpers

log = logging.getLogger(__name__)


@Subroutine(TealType.uint64)
def is_member(address: Expr) -> Expr:
    assetbalance = AssetHolding.balance(address, App.globalGet(Bytes("AssetId")))
    return Seq([
        assetbalance,
        Return(And(
            assetbalance.hasValue(),
            assetbalance.value() > Int(0))
        )
    ])


@Subroutine(TealType.none)
def set_asset_freeze(address: Expr, frozen: Expr) -> Expr:
    return Seq([
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetFreeze,
            TxnField.freeze_asset_account: address,
            TxnField.freeze_asset_frozen: frozen,
            TxnField.freeze_asset: App.globalGet(Bytes("AssetId")),
        }),
        InnerTxnBuilder.Submit(),
    ])


# @Subroutine(TealType.none)
def send_asset(address):
    return Seq([
       InnerTxnBuilder.Begin(),
       InnerTxnBuilder.SetFields({
           TxnField.type_enum: TxnType.AssetTransfer,
           TxnField.asset_receiver: address,
           TxnField.xfer_asset: App.globalGet(Bytes("AssetId")),
           TxnField.asset_amount: Int(1),
       }),
       InnerTxnBuilder.Submit(),
    ])

# @Subroutine(TealType.none)
def add_member(address: Expr) -> Expr:
    return Seq([
        send_asset(address),
        set_asset_freeze(address, Int(1)),
    ])

# @Subroutine(TealType.none)
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
    def __init__(
            self,
            name: str,
            maxsize: int,
            minsize: int,
            members: List[bytes],
    ):
        self._name = name
        self._maxsize = maxsize
        self._minsize = minsize
        # assert len(members) >= minsize
        self._members = members

    def approval_program(self) -> Expr:
        on_creation = Seq([
            Assert(Txn.application_args.length() == Int(2)),
            App.globalPut(Bytes("CommitteeName"), Txn.application_args[0]),
            App.globalPut(Bytes("MaxMembers"), Btoi(Txn.application_args[1])),
            Return(Int(1)),
        ])
        on_register = Return(Int(1))
        on_inittoken = Seq([
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetConfig,
                TxnField.config_asset_total: App.globalGet(Bytes("MaxMembers")),
                TxnField.config_asset_unit_name: Bytes("CMT"),
                TxnField.config_asset_name: Concat(
                    App.globalGet(Bytes("CommitteeName")),
                    Bytes(" Membership")
                ),
                TxnField.config_asset_url: Txn.application_args[1],
                TxnField.config_asset_freeze: Global.current_application_address(),
                TxnField.config_asset_clawback: Global.current_application_address(),
                TxnField.config_asset_manager: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),
            App.globalPut(Bytes("AssetId"), InnerTxn.created_asset_id()),
            Return(Int(1)),
        ])
        assetbalance = AssetHolding.balance(
            Global.current_application_address(),
            App.globalGet(Bytes("AssetId"))
        )
        on_setmembers = Seq([
            # only allow arbitrary selection of members by creator when no one
            # is yet on the committee
            # TODO: allow addition and removal of committee members according
            # TODO: to DAO charter (e.g., vote)
            # Assert(Global.creator_address() == Txn.sender()),
            assetbalance,
            # Assert(
            #     And(
            #         assetbalance.hasValue(),
            #         assetbalance.value() == App.globalGet(Bytes("MaxMembers"))
            #     )
            # ),
            add_members(Txn.application_args[1]),
            Return(Int(1)),
        ])
        on_resign = Seq([
            Assert(And(
                Global.group_size() == Int(2),
                Txn.group_index() == Int(0),
                Gtxn[1].xfer_asset() == App.globalGet(Bytes("AssetId")),
                Gtxn[1].asset_amount() == Int(1),
                Gtxn[1].asset_receiver() == Global.current_application_address(),
            )),
            set_asset_freeze(Txn.sender(), Int(0)),
            Return(Int(1))
        ])
        on_checkmembership = Return(is_member(Txn.sender()))
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
        )


    def deploycontract(self, algod: AlgodClient, privkey: str):
        approval_teal = pyteal.compileTeal(self.approval_program(), Mode.Application, version=5)
        approval_compiled = algodao.deploy.compile_program(algod, approval_teal)
        clear_teal = pyteal.compileTeal(Return(Int(1)), Mode.Application, version=5)
        clear_compiled = algodao.deploy.compile_program(algod, clear_teal)
        local_ints = 0
        local_bytes = 0
        global_ints = 2
        global_bytes = 2
        global_schema = transaction.StateSchema(global_ints, global_bytes)
        local_schema = transaction.StateSchema(local_ints, local_bytes)
        app_args = [
            self._name,
            algodao.helpers.int2bytes(self._maxsize),
        ]
        self._appid = algodao.deploy.create_app(
            algod,
            privkey,
            approval_compiled,
            clear_compiled,
            global_schema,
            local_schema,
            app_args,
        )
        return self._appid

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
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            [b'checkmembership'],
            foreign_assets=[self._assetid],
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)

    def call_setmembers(self, algod: AlgodClient, privkey: str, addr: str, addresses: List[str]):
        addresses_bytes = b''.join(
            algosdk.encoding.decode_address(member)
            for member in addresses
        )
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            [b'setmembers', addresses_bytes],
            foreign_assets=[self._assetid],
            accounts=addresses,
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)

    def call_inittoken(self, algod: AlgodClient, privkey: str, addr: str):
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            [b'inittoken', b'http://localhost/my/committee/token']
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)
        info = algod.pending_transaction_info(txid)
        self._assetid = info['inner-txns'][0]['asset-index']
        log.info(f"Created asset ID for committee: {self._assetid}")
        return self._assetid
