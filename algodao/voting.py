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
from pyteal import Gtxn, Cond, OnComplete, Subroutine, Or, If, Itob
from pyteal import TealType, Substring, ScratchVar

import algodao.deploy
import algodao.helpers
from algodao.contract import CreateContract, DeployedContract, GlobalVariables
from algodao.types import AssetBalances, ApplicationInfo
from algodao.assets import ElectionToken, GovernanceToken, TokenDistributionTree

log = logging.getLogger(__name__)


class ProposalType(enum.Enum):
    PAYMENT = 0
    ADD_COMMITTEE_MEMBER = 1
    CLOSE_AND_DISBURSE = 2
    EJECT_COMMITTEE_MEMBER = 3
    NEW_COMMITTEE = 4


class VoteType(enum.Enum):
    COMMITTEE = 0
    GOVERNANCE_TOKEN = 1


@Subroutine(TealType.uint64)
def is_updown_vote(votetype: Expr) -> Expr:
    return Return(Or(
        votetype == Int(ProposalType.PAYMENT.value),
        votetype == Int(ProposalType.ADD_COMMITTEE_MEMBER.value),
        votetype == Int(ProposalType.CLOSE_AND_DISBURSE.value),
        votetype == Int(ProposalType.EJECT_COMMITTEE_MEMBER.value),
        votetype == Int(ProposalType.NEW_COMMITTEE.value),
    ))


@Subroutine(TealType.bytes)
def proposal_payment_address(addl_data: Expr):
    return Return(Substring(addl_data, Int(0), Int(32)))


@Subroutine(TealType.uint64)
def proposal_payment_amount(addl_data: Expr):
    return Return(Btoi(Substring(addl_data, Int(32), Int(38))))


@Subroutine(TealType.uint64)
def minvotesneeded(vtype_data: Expr, total_votes: Expr):
    win_pct = ScratchVar(TealType.uint64)
    return Seq([
        win_pct.store(Btoi(Substring(vtype_data, Int(8), Int(16)))),
        Return(win_pct.load() * total_votes / Int(100))
    ])


class Proposal:
    class GlobalInts(GlobalVariables):
        RegBegin = enum.auto()
        RegEnd = enum.auto()
        VoteBegin = enum.auto()
        VoteEnd = enum.auto()
        VoteAssetId = enum.auto()
        NumOptions = enum.auto()
        ProposalType = enum.auto()
        Implemented = enum.auto()
        DaoId = enum.auto()
        VoteType = enum.auto()
        Passed = enum.auto()

        @classmethod
        def option(cls, num: Expr):
            return Concat(Bytes("Option"), Itob(num))

        @classmethod
        def allvotes(cls, num: Expr):
            return Concat(Bytes("AllVotes"), Itob(num))

    class GlobalBytes(GlobalVariables):
        Name = enum.auto()
        VoteTypeData = enum.auto()
        AdditionalData = enum.auto()

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
                daoid: int,
                proptype: ProposalType,
        ):
            self._name: str = name
            self._token: ElectionToken = token
            self._regbegin: int = regbegin
            self._regend: int = regend
            self._start_vote: int = start_vote
            self._end_vote: int = end_vote
            self._num_options: int = num_options
            self._proptype: ProposalType = proptype
            self._daoid: int = daoid
            self._additionaldata: bytes = b''
            self._vtypedata: bytes = b''

        def setpaymentinfo(self, receiver: str, amount: int):
            assert self._proptype == ProposalType.PAYMENT
            self._additionaldata = (
                    algosdk.encoding.decode_address(receiver)
                    + algodao.helpers.int2bytes(amount)
            )

        def setvotedata(self, votetype: VoteType, win_pct: int):
            if win_pct < 0 or win_pct > 100:
                raise ValueError(f"Invalid win percentage: {win_pct}")
            # TODO: implement committee votes
            if votetype != VoteType.GOVERNANCE_TOKEN:
                raise NotImplementedError(votetype)
            self._vtypedata = (
                    algodao.helpers.int2bytes(votetype.value)
                    + algodao.helpers.int2bytes(win_pct)
            )

        def approval_program(self) -> Expr:
            GlobalInts = Proposal.GlobalInts
            GlobalBytes = Proposal.GlobalBytes
            on_creation = Seq([
                Assert(Txn.application_args.length() == Int(11)),
                GlobalBytes.Name.put(Txn.application_args[0]),
                GlobalInts.VoteAssetId.put(Btoi(Txn.application_args[1])),
                GlobalInts.RegBegin.put(Btoi(Txn.application_args[2])),
                GlobalInts.RegEnd.put(Btoi(Txn.application_args[3])),
                GlobalInts.VoteBegin.put(Btoi(Txn.application_args[4])),
                GlobalInts.VoteEnd.put(Btoi(Txn.application_args[5])),
                GlobalInts.NumOptions.put(Btoi(Txn.application_args[6])),
                GlobalInts.ProposalType.put(Btoi(Txn.application_args[7])),
                GlobalInts.DaoId.put(Btoi(Txn.application_args[8])),
                GlobalBytes.VoteTypeData.put(Txn.application_args[9]),
                GlobalBytes.AdditionalData.put(Txn.application_args[10]),
                GlobalInts.Passed.put(Int(0)),
                GlobalInts.Implemented.put(Int(0)),
                GlobalInts.VoteType.put(Int(VoteType.GOVERNANCE_TOKEN.value)),
                If(
                    is_updown_vote(GlobalInts.ProposalType.get()),
                    Seq([
                        App.globalPut(Concat(Bytes("Option"), Itob(Int(1))), Bytes("Yes")),
                        App.globalPut(Concat(Bytes("Option"), Itob(Int(2))), Bytes("No")),
                    ]),
                    # Currently all implemented vote types are up/down votes;
                    # to support multioption proposals we could pass in the
                    # options as additional application args
                ),
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
                    Btoi(option) > Int(0),
                    Btoi(option) <= GlobalInts.NumOptions.get(),
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
            yesvotes = ScratchVar(TealType.uint64)
            novotes = ScratchVar(TealType.uint64)
            minvotes = ScratchVar(TealType.uint64)
            on_finalizevote = Seq([
                Assert(And(
                    Global.round() > GlobalInts.VoteEnd.get(),
                    Txn.application_args.length() == Int(1),
                )),
                If(
                    is_updown_vote(GlobalInts.VoteType.get()),
                    Seq([
                        Assert(And(
                            App.globalGet(GlobalInts.option(Int(1))) == Bytes("Yes"),
                            App.globalGet(GlobalInts.option(Int(2))) == Bytes("No"),
                        )),
                        yesvotes.store(App.globalGet(GlobalInts.allvotes(Int(1)))),
                        novotes.store(App.globalGet(GlobalInts.allvotes(Int(2)))),
                        minvotes.store(minvotesneeded(
                            GlobalBytes.VoteTypeData.get(),
                            yesvotes.load() + novotes.load()
                        )),
                        If(
                            yesvotes.load() >= minvotes.load(),
                            GlobalInts.Passed.put(Int(1))
                        ),
                        Return(Int(1)),
                    ]),
                ),
                Return(Int(0)),
            ])
            on_setimplemented = Seq([
                Assert(And(
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(1),
                    Txn.application_args.length() == Int(1),
                    Gtxn[0].application_id() == GlobalInts.DaoId.get(),
                    Gtxn[0].application_args[0] == Bytes("implementproposal"),
                    GlobalInts.Implemented.get() == Int(0),
                )),
                GlobalInts.Implemented.put(Int(1)),
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
                [Txn.application_args[0] == Bytes("setimplemented"), on_setimplemented],
                [Txn.application_args[0] == Bytes("finalizevote"), on_finalizevote],
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
                algodao.helpers.int2bytes(self._proptype.value),
                algodao.helpers.int2bytes(self._daoid),
                self._vtypedata,
                self._additionaldata,
            ]

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(
                len(Proposal.GlobalInts) + self._num_options,
                len(Proposal.GlobalBytes) + self._num_options,
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

        def call_vote(self, algod: AlgodClient, addr: str, privkey: str, option: int, amount: int):
            args: List[bytes] = [
                b"vote",
                algodao.helpers.int2bytes(option)
            ]
            params = algod.suggested_params()
            appaddr = algosdk.logic.get_application_address(self._appid)
            txn1 = transaction.ApplicationNoOpTxn(
                addr,
                params,
                self.appid,
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
            try:
                txid = algod.send_transactions([signed1, signed2])
                algodao.helpers.wait_for_confirmation(algod, txid)
            except Exception as exc:
                algodao.helpers.writedryrun(algod, signed1, 'failed_txn1')
                algodao.helpers.writedryrun(algod, signed2, 'failed_txn2')
                raise

        def call_finalizevote(self, algod: AlgodClient, addr: str, privkey: str):
            return self.call_method(
                algod,
                addr,
                privkey,
                b'finalizevote',
                []
            )

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



