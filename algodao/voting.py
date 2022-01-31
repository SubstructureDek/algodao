# This example is provided for informational purposes only and has not been
# audited for security.
import logging
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

import algosdk.account
import algosdk.logic
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from pyteal import *

import algodao.helpers
from algodao.types import AssetBalances, PendingTransactionInfo
from algodao.assets import ElectionToken, GovernanceToken, TokenDistributionTree

log = logging.getLogger(__name__)


class Proposal:
    def __init__(
            self,
            name: str,
            token: ElectionToken,
            regbegin: int,
            regend: int,
            start_vote: int,
            end_vote: int,
            num_options: int,
    ):
        self._name: str = name
        self._token: ElectionToken = token
        self._regbegin: int = regbegin
        self._regend: int = regend
        self._start_vote: int = start_vote
        self._end_vote: int = end_vote
        self._num_options: int = num_options
        self._appid: Optional[int] = None

    def approval_program(self):
        expected_args = 4
        on_creation = Seq([
            Assert(Txn.application_args.length() == Int(expected_args)),
            App.globalPut(Bytes("RegBegin"), Btoi(Txn.application_args[0])),
            App.globalPut(Bytes("RegEnd"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("VoteBegin"), Btoi(Txn.application_args[2])),
            App.globalPut(Bytes("VoteEnd"), Btoi(Txn.application_args[3])),
            Return(Int(1)),
        ])
        on_register = Return(
            And(
                Global.round() >= App.globalGet(Bytes("RegBegin")),
                Global.round() <= App.globalGet(Bytes("RegEnd")),
            )
        )
        is_creator = Txn.sender() == Global.creator_address()
        on_optintoken = Seq([
            Assert(is_creator),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.xfer_asset: Int(self._token.asset_id),
                TxnField.asset_amount: Int(0),
            }),
            InnerTxnBuilder.Submit(),
            # App.globalPut(Bytes("AssetId"), Int(self._token.asset_id)),
            Return(Int(1)),
        ])
        option = Txn.application_args[1]
        globalname = Concat(Bytes("AllVotes"), option)
        votes = Gtxn[1].asset_amount()
        on_vote = Seq([
            Assert(And(
                Global.round() >= App.globalGet(Bytes("VoteBegin")),
                Global.round() <= App.globalGet(Bytes("VoteEnd")),
                Global.group_size() == Int(2),
                Txn.group_index() == Int(0),
                Gtxn[1].xfer_asset() == Int(self._token.asset_id),
            )),
            App.localPut(
                Txn.sender(),
                Concat(Bytes("Voted"), option),
                votes
            ),
            App.globalPut(
                globalname,
                App.globalGet(globalname) + votes
            ),
            Return(Int(1)),
        ])
        on_closeout = Return(Int(1))
        program = Cond(
            [Txn.application_id() == Int(0), on_creation],
            [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
            [Txn.on_completion() == OnComplete.OptIn, on_register],
            [Txn.application_args[0] == Bytes("vote"), on_vote],
            [Txn.application_args[0] == Bytes("optintoken"), on_optintoken],
        )
        return program

    def optintoken(self, algod: AlgodClient, addr: str, privkey: str):
        args: List[bytes] = [
            b'optintoken'
        ]
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            args,
            foreign_assets=[self._token.asset_id]
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)

    def clear_program(self):
        return Return(Int(1))

    def createappargs(self):
        return [
            algodao.helpers.int2bytes(self._regbegin),
            algodao.helpers.int2bytes(self._regend),
            algodao.helpers.int2bytes(self._start_vote),
            algodao.helpers.int2bytes(self._end_vote),
        ]

    def deploycontract(self, algod: AlgodClient, senderaddr: str, privkey: str):
        on_complete = transaction.OnComplete.NoOpOC
        params = algod.suggested_params()
        approval_compiled = algodao.helpers.compileprogram(algod, self.approval_program())
        clear_compiled = algodao.helpers.compileprogram(algod, self.clear_program())
        local_ints = self._num_options
        local_bytes = 0
        global_ints = 4 + self._num_options
        global_bytes = 0
        global_schema = transaction.StateSchema(global_ints, global_bytes)
        local_schema = transaction.StateSchema(local_ints, local_bytes)
        app_args = self.createappargs()
        txn = transaction.ApplicationCreateTxn(
            senderaddr,
            params,
            on_complete,
            approval_compiled,
            clear_compiled,
            global_schema,
            local_schema,
            app_args,
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)
        response: PendingTransactionInfo = algod.pending_transaction_info(txid)
        app_id: int = response['application-index']
        log.info(f'Created new app-id: {app_id}')
        self._appid = app_id
        return app_id

    def sendvote(self, algod: AlgodClient, privkey: str, addr: str, option: int, amount: int):
        args: List[bytes] = [
            b"vote",
            algodao.helpers.int2bytes(option)
        ]
        params = algod.suggested_params()
        appaddr = algosdk.logic.get_application_address(self._appid)
        txn1 = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            args,
        )
        txn2 = transaction.AssetTransferTxn(
            addr,
            params,
            appaddr,
            amount,
            self._token.asset_id,
        )
        groupid = transaction.calculate_group_id([txn1, txn2])
        txn1.group = groupid
        txn2.group = groupid
        signed1 = txn1.sign(privkey)
        signed2 = txn2.sign(privkey)
        txid = algod.send_transactions([signed1, signed2])
        algodao.helpers.wait_for_confirmation(algod, txid)


class Election:
    def __init__(
            self,
            indexer: IndexerClient,
            governence_token: GovernanceToken,
            vote_token: ElectionToken,
            governance2votes: Callable[[int], int],
            beginreg: int,
            endreg: int,
    ):
        self._governance_token: GovernanceToken = governence_token
        self._vote_token: ElectionToken = vote_token
        self._indexer: IndexerClient = indexer
        self._gov2votes = governance2votes
        self._beginreg = beginreg
        self._endreg = endreg

    def builddistribution(self):
        balance_dict: Dict[str, int] = self.gettokencounts()
        votedist: OrderedDict[str, int] = OrderedDict(
            (address, self._gov2votes(govcount))
            for address, govcount in balance_dict
        )
        return TokenDistributionTree(self._vote_token, votedist, self._beginreg, self._endreg)

    def gettokencounts(self) -> Dict[str, int]:
        balance_dict = {}
        balances: AssetBalances = self._indexer.asset_balances(
            self._governance_token.asset_id
        )
        for balance in balances['balances']:
            amount: int = balance['amount']
            address: str = balance['address']
            balance_dict[address] = amount
        return balance_dict

