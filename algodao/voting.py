# This example is provided for informational purposes only and has not been
# audited for security.
import enum
import logging
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

import algosdk.account
import algosdk.logic
import pyteal
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from pyteal import Int, Expr, Return, Bytes, App, Assert, InnerTxnBuilder
from pyteal import Txn, Btoi, Global, Seq, And, TxnField, Concat, TxnType
from pyteal import Gtxn, Cond, OnComplete, Mode, InnerTxn

import algodao.deploy
import algodao.helpers
from algodao.contract import CreateContract, DeployedContract, GlobalVariables
from algodao.types import AssetBalances, ApplicationInfo
from algodao.assets import ElectionToken, GovernanceToken, TokenDistributionTree

log = logging.getLogger(__name__)


class Proposal:
    class GlobalInts(GlobalVariables):
        RegBegin = enum.auto()
        RegEnd = enum.auto()
        VoteBegin = enum.auto()
        VoteEnd = enum.auto()
        VoteAssetId = enum.auto()
        NumOptions = enum.auto()

    class GlobalBytes(GlobalVariables):
        Name = enum.auto()

    class CreateProposal(CreateContract):
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

        def approval_program(self) -> Expr:
            GlobalInts = Proposal.GlobalInts
            GlobalBytes = Proposal.GlobalBytes
            expected_args = 7
            on_creation = Seq([
                Assert(Txn.application_args.length() == Int(expected_args)),
                GlobalBytes.Name.put(Txn.application_args[0]),
                GlobalInts.VoteAssetId.put(Btoi(Txn.application_args[1])),
                GlobalInts.RegBegin.put(Btoi(Txn.application_args[2])),
                GlobalInts.RegEnd.put(Btoi(Txn.application_args[3])),
                GlobalInts.VoteBegin.put(Btoi(Txn.application_args[4])),
                GlobalInts.VoteEnd.put(Btoi(Txn.application_args[5])),
                GlobalInts.NumOptions.put(Btoi(Txn.application_args[6])),
                Return(Int(1)),
            ])
            on_register = Return(
                And(
                    Global.round() >= GlobalInts.RegBegin.get(),
                    Global.round() <= GlobalInts.RegEnd.get(),
                )
            )
            is_creator = Txn.sender() == Global.creator_address()
            on_optintoken = Seq([
                Assert(is_creator),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.xfer_asset: Btoi(Txn.application_args[1]),
                    TxnField.asset_amount: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                Return(Int(1)),
            ])
            on_setvotetoken = Seq([
                Assert(is_creator),
                Assert(GlobalInts.VoteAssetId.get() == Int(0)),
                GlobalInts.VoteAssetId.put(Btoi(Txn.application_args[1])),
                Return(Int(1)),
            ])
            option = Txn.application_args[1]
            globalname = Concat(Bytes("AllVotes"), option)
            votes = Gtxn[1].asset_amount()
            on_vote = Seq([
                Assert(And(
                    Global.round() >= GlobalInts.VoteBegin.get(),
                    Global.round() <= GlobalInts.VoteEnd.get(),
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(0),
                    Gtxn[1].xfer_asset() == GlobalInts.VoteAssetId.get(),
                    Gtxn[1].asset_receiver() == Global.current_application_address(),
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
                [Txn.application_args[0] == Bytes("setvotetoken"), on_setvotetoken],
            )
            return program

        def clear_program(self) -> Expr:
            return Return(Int(1))

        def createapp_args(self) -> List[bytes]:
            return [
                self._name.encode(),
                algodao.helpers.int2bytes(self._token.asset_id),
                algodao.helpers.int2bytes(self._regbegin),
                algodao.helpers.int2bytes(self._regend),
                algodao.helpers.int2bytes(self._start_vote),
                algodao.helpers.int2bytes(self._end_vote),
                algodao.helpers.int2bytes(self._num_options),
            ]

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(
                len(Proposal.GlobalInts) + self._num_options,
                len(Proposal.GlobalBytes)
            )

        def local_schema(self) -> transaction.StateSchema:
            local_ints = self._num_options
            local_bytes = 0
            return transaction.StateSchema(local_ints, local_bytes)

    class DeployedProposal(DeployedContract):
        def __init__(self, algod: AlgodClient, appid: int):
            appinfo: ApplicationInfo = algod.application_info(appid)
            self._assetid = algodao.helpers.readintfromstore(
                appinfo['params']['global-state'],
                Proposal.GlobalInts.VoteAssetId.name.encode()
            )
            self._num_options = algodao.helpers.readintfromstore(
                appinfo['params']['global-state'],
                Proposal.GlobalInts.NumOptions.name.encode()
            )
            super(Proposal.DeployedProposal, self).__init__(appid)

        def call_optintoken(self, algod: AlgodClient, addr: str, privkey: str, assetid: int):
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

        def call_vote(self, algod: AlgodClient, privkey: str, addr: str, option: int, amount: int):
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
                self._assetid,
            )
            groupid = transaction.calculate_group_id([txn1, txn2])
            txn1.group = groupid
            txn2.group = groupid
            signed1 = txn1.sign(privkey)
            signed2 = txn2.sign(privkey)
            txid = algod.send_transactions([signed1, signed2])
            algodao.helpers.wait_for_confirmation(algod, txid)

    @classmethod
    def deploy(cls, algod: AlgodClient, createprop: CreateProposal, privkey: str):
        appid = createprop.deploy(algod, privkey)
        return Proposal.DeployedProposal(algod, appid)


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
        return TokenDistributionTree.CreateTree(
            self._vote_token,
            votedist,
            self._beginreg,
            self._endreg
        )

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



