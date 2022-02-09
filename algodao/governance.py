"""
Top-level contracts for deploying the DAO
"""
from __future__ import annotations

import enum
from typing import List, Optional

import algosdk.logic
from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from pyteal import Seq, Assert, App, Return, Int, Btoi, Txn, Expr, Bytes
from pyteal import Cond, Gtxn, Global, Len, Concat, OnComplete, And, Or, Not
from pyteal import InnerTxnBuilder, TxnField, TxnType, If, Subroutine, TealType
from pyteal import InnerTxn, AssetHolding, ScratchVar, For, Substring

import algodao.helpers
from algodao.committee import is_member, current_committee_size_ex, set_asset_freeze, send_asset
from algodao.committee import Committee
from algodao.contract import CreateContract, DeployedContract, GlobalVariables
from algodao.contract import LocalVariables
from algodao.helpers import readintfromstore, appaddr
from algodao.voting import Proposal, ProposalType, proposal_payment_amount, proposal_payment_address
from algodao.voting import VoteType
from algodao.types import ApplicationInfo

RULE_LEN = 16
PROPOSAL_RULE_LEN = 24


@Subroutine(TealType.uint64)
def proposal_trusted(proposal_appid: Expr, trust_assetid: Expr):
    """
    Check that the proposal is trusted (has been assigned a Trust token)
    """
    trusted = AssetHolding.balance(appaddr(proposal_appid), trust_assetid)
    return Seq([
        trusted,
        Return(And(trusted.hasValue(), trusted.value() > Int(0)))
    ])


@Subroutine(TealType.bytes)
def find_rule(proposal_rules: Expr, proposal_type: Expr):
    """
    Find the rule that applies to the specified proposal type
    """
    index = ScratchVar(TealType.uint64)
    return Seq([
        For(
            index.store(Int(0)),
            index.load() < Len(proposal_rules),
            index.store(index.load() + Int(PROPOSAL_RULE_LEN))
        ).Do(
            If(
                Btoi(Substring(proposal_rules, index.load(), index.load() + Int(8))) == proposal_type,
                Return(Substring(
                    proposal_rules,
                    index.load() + Int(8),
                    index.load() + Int(PROPOSAL_RULE_LEN)
                )),
            )
        ),
        # proposal type not found in rules
        Assert(Int(0)),
        # previous assert will always fail by TEAL still requires a Return
        Return(Bytes('')),
    ])


@Subroutine(TealType.uint64)
def satisfies_rule(proposal_appid: Expr, rule: Expr):
    """
    Check that the given Proposal satisfies the specified rule
    """
    vtype_data = App.globalGetEx(proposal_appid, Proposal.GlobalBytes.VoteTypeData.bytes)
    return Seq([
        vtype_data,
        Assert(vtype_data.hasValue()),
        Return(rule == vtype_data.value()),
    ])


@Subroutine(TealType.uint64)
def proposal_meets_criteria(proposal_appid: Expr, proposal_rules: Expr):
    """
    Check that the proposal meets the criteria specified by the DAO for this
    type of proposal.
    """
    proposal_type = App.globalGetEx(proposal_appid, Proposal.GlobalInts.ProposalType.bytes)
    rule = ScratchVar(TealType.bytes)
    return Seq([
        proposal_type,
        Assert(proposal_type.hasValue()),
        rule.store(find_rule(proposal_rules, proposal_type.value())),
        Return(satisfies_rule(proposal_appid, rule.load())),
    ])


@Subroutine(TealType.uint64)
def proposal_passed(proposal_appid: Expr):
    passed = App.globalGetEx(proposal_appid, Proposal.GlobalInts.Passed.bytes)
    return Seq([
        passed,
        Return(And(passed.hasValue(), passed.value()))
    ])


@Subroutine(TealType.none)
def implement_proposal(proposal_appid: Expr):
    proposal_type = App.globalGetEx(proposal_appid, Proposal.GlobalInts.ProposalType.bytes)
    addl_data = App.globalGetEx(proposal_appid, Proposal.GlobalBytes.AdditionalData.bytes)
    return Seq([
        proposal_type,
        addl_data,
        Assert(And(proposal_type.hasValue(), addl_data.hasValue())),
        If(
            proposal_type.value() == Int(ProposalType.PAYMENT.value),
            Seq([
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: proposal_payment_address(addl_data.value()),
                    TxnField.amount: proposal_payment_amount(addl_data.value()),
                }),
                InnerTxnBuilder.Submit(),
            ])

        )
        # TODO: implement other proposal types
    ])


class AlgoDao:
    """
    The top-level contract representing the DAO.
    """
    class GlobalInts(GlobalVariables):
        Finalized = enum.auto()
        Closed = enum.auto()
        TrustAsset = enum.auto()

    class GlobalBytes(GlobalVariables):
        Name = enum.auto()
        Committees = enum.auto()
        ProposalRules = enum.auto()

    class CreateDao(CreateContract):
        def __init__(self, name: str, trust_assetid: int):
            self._name: str = name
            self._trust_assetid: int = trust_assetid

        def createapp_args(self) -> List[bytes]:
            return [
                self._name.encode(),
                algodao.helpers.int2bytes(self._trust_assetid)
            ]

        def approval_program(self) -> Expr:
            GlobalBytes = AlgoDao.GlobalBytes
            GlobalInts = AlgoDao.GlobalInts
            on_creation = Seq([
                Assert(Txn.application_args.length() == Int(2)),
                GlobalBytes.Name.put(Txn.application_args[0]),
                GlobalInts.TrustAsset.put(Btoi(Txn.application_args[1])),
                GlobalBytes.Committees.put(Bytes(b'')),
                GlobalInts.Finalized.put(Int(0)),
                GlobalInts.Closed.put(Int(0)),
                GlobalBytes.ProposalRules.put(Bytes(b'')),
                Return(Int(1)),
            ])
            setup_phase_approved = And(
                Not(GlobalInts.Finalized.get()),
                Txn.sender() == Global.creator_address()
            )
            on_addcommittee = Seq([
                Assert(setup_phase_approved),
                Assert(Txn.application_args.length() == Int(2)),
                Assert(Len(Txn.application_args[1]) == Int(8)),
                GlobalBytes.Committees.put(Concat(
                    GlobalBytes.Committees.get(),
                    Txn.application_args[1]
                )),
                Return(Int(1)),
            ])
            on_addrule = Seq([
                Assert(setup_phase_approved),
                Assert(Txn.application_args.length() == Int(2)),
                Assert(Len(Txn.application_args[1]) == Int(PROPOSAL_RULE_LEN)),
                GlobalBytes.ProposalRules.put(Concat(
                    GlobalBytes.ProposalRules.get(),
                    Txn.application_args[1]
                )),
                Return(Int(1)),
            ])
            on_finalize = Seq([
                Assert(setup_phase_approved),
                Assert(Txn.application_args.length() == Int(1)),
                GlobalInts.Finalized.put(Int(1)),
                Return(Int(1)),
            ])
            proposal_appid = Gtxn[1].application_id()
            on_implementproposal = Seq([
                Assert(GlobalInts.Finalized.get()),
                Assert(Global.group_size() == Int(2)),
                Assert(Txn.group_index() == Int(0)),
                Assert(Txn.application_args.length() == Int(1)),
                Assert(Gtxn[1].application_args[0] == Bytes('setimplemented')),
                Assert(proposal_trusted(proposal_appid, GlobalInts.TrustAsset.get())),
                Assert(proposal_meets_criteria(proposal_appid, GlobalBytes.ProposalRules.get())),
                Assert(proposal_passed(proposal_appid)),
                implement_proposal(proposal_appid),
                Return(Int(1)),
            ])
            can_delete = Seq([
                Return(Or(
                    # DAO has not been finalized and sender is attempting to delete
                    setup_phase_approved,
                    # or, DAO has been closed out by the specified closure process,
                    And(
                        GlobalInts.Closed.get(),
                        Txn.sender() == Global.creator_address()
                    )
                ))
            ])
            # TODO: add ability to change governance structure via proposal
            can_update = Return(Int(0))
            return Cond(
                [Txn.application_id() == Int(0), on_creation],
                [Txn.on_completion() == OnComplete.DeleteApplication, can_delete],
                [Txn.on_completion() == OnComplete.UpdateApplication, can_update],
                [Txn.application_args[0] == Bytes('addcommittee'), on_addcommittee],
                [Txn.application_args[0] == Bytes('addrule'), on_addrule],
                [Txn.application_args[0] == Bytes('finalize'), on_finalize],
                [Txn.application_args[0] == Bytes('implementproposal'), on_implementproposal]
            )

        def clear_program(self) -> Expr:
            return Return(Int(1))

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(len(AlgoDao.GlobalInts), len(AlgoDao.GlobalBytes))

        def local_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(0, 0)

    class DeployedDao(DeployedContract):
        def __init__(self, algod: AlgodClient, appid: int):
            info: ApplicationInfo = algod.application_info(appid)
            self._trust_assetid = readintfromstore(
                info['params']['global-state'],
                AlgoDao.GlobalInts.TrustAsset.name.encode()
            )
            super(AlgoDao.DeployedDao, self).__init__(appid)

        @property
        def trust_assetid(self):
            return self._trust_assetid

        def call_addcommittee(self, algod, addr, privkey, committee_id):
            return self.call_method(
                algod,
                addr,
                privkey,
                b'addcommittee',
                [
                    algodao.helpers.int2bytes(committee_id),
                ],
            )

        def call_addrule(
                self,
                algod,
                addr,
                privkey,
                proposal_type: ProposalType,
                vote_type: VoteType,
                win_pct: int,
        ):
            if win_pct < 0 or win_pct > 100:
                raise ValueError(win_pct)
            rule = (
                algodao.helpers.int2bytes(proposal_type.value)
                + algodao.helpers.int2bytes(vote_type.value)
                + algodao.helpers.int2bytes(win_pct)
            )
            return self.call_method(
                algod,
                addr,
                privkey,
                b'addrule',
                [
                    rule,
                ],
            )

        def call_finalize(self, algod, addr, privkey):
            return self.call_method(
                algod,
                addr,
                privkey,
                b'finalize',
                [],
            )

        def call_implementproposal(
                self,
                algod: AlgodClient,
                proposal: Proposal.DeployedProposal,
                addr: str,
                privkey: str,
                accounts: List[str],
        ):
            params = algod.suggested_params()
            txn1 = transaction.ApplicationNoOpTxn(
                addr,
                params,
                self.appid,
                [
                    b'implementproposal',
                ],
                foreign_assets=[self.trust_assetid],
                accounts=[algosdk.logic.get_application_address(proposal.appid), *accounts],
                foreign_apps=[proposal.appid],
            )
            txn2 = transaction.ApplicationNoOpTxn(
                addr,
                params,
                proposal.appid,
                [
                    b'setimplemented',
                ]
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
                algodao.helpers.writedryrun(algod, [signed1, signed2], 'failed_txn')
                raise

    @classmethod
    def deploy(cls, algod, createdao: CreateDao, privkey):
        appid = createdao.deploy(algod, privkey)
        return AlgoDao.DeployedDao(algod, appid)


class PreapprovalGate:
    """
    A statically deployed smart contract (i.e., one that is created when the
    DAO is created and that all subsequent proposals pass through) that allows
    the Trusted committee to ensure submitted proposals (which are new smart
    contracts) are trustworthy (i.e., that they are implemented with the
    approved TEAL code).

    This is needed because TEAL does not provide a way for smart contracts to
    deploy their own contracts, or to verify that other contracts are
    implemented in a specific way. When the committee verifies that a given
    proposal is legitimate (e.g., by checking the hash of the deployed contract)
    this contract passes along a single Trusted ASA token to indicate to the
    governance contract that it should be followed.
    """
    class GlobalInts(GlobalVariables):
        Initialized = enum.auto()
        ConsideredAppId = enum.auto()
        YesVotes = enum.auto()
        NoVotes = enum.auto()
        CommitteeId = enum.auto()
        VotingStartRound = enum.auto()
        VoteInProgress = enum.auto()
        TrustAssetId = enum.auto()
        MinRoundsPerProposal = enum.auto()

    class GlobalBytes(GlobalVariables):
        ConsideredAppAddr = enum.auto()
        CommitteeAddr = enum.auto()

    class LocalInts(LocalVariables):
        VotedAppId = enum.auto()
        Vote = enum.auto()

    class LocalBytes(LocalVariables):
        pass

    class CreateGate(CreateContract):
        def __init__(
                self,
                committee_id: int,
                minrounds: int,
        ):
            self._committee_id: int = committee_id
            self._committee_addr: str = algosdk.logic.get_application_address(committee_id)
            self._minrounds: int = minrounds

        def createapp_args(self) -> List[bytes]:
            return [
                algodao.helpers.int2bytes(self._committee_id),
                algosdk.encoding.decode_address(self._committee_addr),
                algodao.helpers.int2bytes(self._minrounds),
            ]

        def approval_program(self):
            GlobalInts = PreapprovalGate.GlobalInts
            GlobalBytes = PreapprovalGate.GlobalBytes
            LocalInts = PreapprovalGate.LocalInts
            on_creation = Seq([
                GlobalInts.Initialized.put(Int(0)),
                GlobalInts.ConsideredAppId.put(Int(0)),
                GlobalBytes.ConsideredAppAddr.put(Bytes(b'')),
                GlobalInts.YesVotes.put(Int(0)),
                GlobalInts.NoVotes.put(Int(0)),
                GlobalInts.CommitteeId.put(Btoi(Txn.application_args[0])),
                # TODO: necessary to save both the app id and the address?
                GlobalBytes.CommitteeAddr.put(Txn.application_args[1]),
                GlobalInts.VotingStartRound.put(Int(0)),
                GlobalInts.VoteInProgress.put(Int(0)),
                GlobalInts.TrustAssetId.put(Int(0)),
                GlobalInts.MinRoundsPerProposal.put(Btoi(Txn.application_args[2])),
                Return(Int(1)),
            ])
            on_inittoken = Seq([
                Assert(Not(GlobalInts.Initialized.get())),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_total: Btoi(Txn.application_args[1]),
                    TxnField.config_asset_unit_name: Txn.application_args[2],
                    TxnField.config_asset_name: Txn.application_args[3],
                    TxnField.config_asset_url: Txn.application_args[4],
                    TxnField.config_asset_manager: Global.current_application_address(),
                    # TxnField.config_asset_default_frozen: Int(1),
                    TxnField.config_asset_freeze: Global.current_application_address(),
                    TxnField.config_asset_clawback: Global.current_application_address(),
                    TxnField.config_asset_reserve: Global.current_application_address(),
                    TxnField.config_asset_decimals: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                GlobalInts.TrustAssetId.put(InnerTxn.created_asset_id()),
                GlobalInts.Initialized.put(Int(1)),
                Return(Int(1)),
            ])
            assetid = App.globalGetEx(
                GlobalInts.CommitteeId.get(),
                Committee.GlobalInts.AssetId.bytes,
            )
            committeesize = current_committee_size_ex(
                GlobalInts.CommitteeId.get(),
                GlobalBytes.CommitteeAddr.get(),
            )
            on_assessproposal = Seq([
                # Any committee member can submit a proposal for consideration.
                # If another contract is being considered, it can be replaced
                # without a definite conclusion. This allows thet committee to move
                # on to another contract if there is uncertainty. However a
                # certain number of rounds must have passed before moving on to
                # another contract. This prevents a single member from spamming
                # the contract and preventing other contracts from being
                # considered.
                assetid,
                Assert(And(
                    assetid.hasValue(),
                    is_member(assetid.value(), Txn.sender())
                )),
                If(
                    GlobalInts.VoteInProgress.get(),
                    Assert(
                        Global.round() > GlobalInts.VotingStartRound.get()
                           + GlobalInts.MinRoundsPerProposal.get()
                    )
                ),
                GlobalInts.VoteInProgress.put(Int(1)),
                GlobalInts.VotingStartRound.put(Global.round()),
                GlobalInts.ConsideredAppId.put(Btoi(Txn.application_args[1])),
                GlobalBytes.ConsideredAppAddr.put(Txn.application_args[2]),
                Return(Int(1)),
            ])
            on_vote = Seq([
                assetid,
                Assert(And(
                    assetid.hasValue(),
                    is_member(assetid.value(), Txn.sender()))
                ),
                # check that the application ID the member is attempting to vote
                # on is in fact the applicatoin ID under consideration
                Assert(GlobalInts.ConsideredAppId.get() == Btoi(Txn.application_args[1])),
                # check that the vote is in fact in progress
                Assert(GlobalInts.VoteInProgress.get()),
                If(
                    LocalInts.VotedAppId.get(Txn.sender()) == GlobalInts.ConsideredAppId.get(),
                    # user has already voted on this proposal; first rescind their
                    # previous vote
                    If(
                        LocalInts.Vote.get(Txn.sender()),
                        GlobalInts.YesVotes.put(GlobalInts.YesVotes.get() - Int(1)),
                        GlobalInts.NoVotes.put(GlobalInts.NoVotes.get() - Int(1))
                    )
                ),
                LocalInts.VotedAppId.put(Txn.sender(), GlobalInts.ConsideredAppId.get()),
                LocalInts.Vote.put(Txn.sender(), Btoi(Txn.application_args[2])),
                If(
                    LocalInts.Vote.get(Txn.sender()),
                    GlobalInts.YesVotes.put(GlobalInts.YesVotes.get() + Int(1)),
                    GlobalInts.NoVotes.put(GlobalInts.NoVotes.get() + Int(1))
                ),
                # if this vote leads to a definitive result, immediately close the
                # vote and execute on the result
                If(
                    # TODO: allow approval method other than majority vote
                    GlobalInts.YesVotes.get() > committeesize / Int(2),
                    Seq([
                        set_asset_freeze(
                            Global.current_application_address(),
                            GlobalInts.TrustAssetId.get(),
                            Int(0)
                        ),
                        send_asset(
                            GlobalBytes.ConsideredAppAddr.get(),
                            GlobalInts.TrustAssetId.get()
                        ),
                        set_asset_freeze(
                            GlobalBytes.ConsideredAppAddr.get(),
                            GlobalInts.TrustAssetId.get(),
                            Int(1),
                        ),
                        GlobalInts.VoteInProgress.put(Int(0)),
                    ])
                ),
                If(
                    GlobalInts.NoVotes.get() > committeesize / Int(2),
                    Seq([
                        GlobalInts.VoteInProgress.put(Int(0)),
                    ])
                ),
                Return(Int(1)),
            ])
            on_closeout = self.clear_program()
            return Cond(
                [Txn.application_id() == Int(0), on_creation],
                [Txn.on_completion() == OnComplete.UpdateApplication, Return(Int(0))],
                [Txn.on_completion() == OnComplete.DeleteApplication, Return(Int(0))],
                [Txn.on_completion() == OnComplete.OptIn, Return(Int(1))],
                [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
                [Txn.application_args[0] == Bytes('inittoken'), on_inittoken],
                [Txn.application_args[0] == Bytes('assessproposal'), on_assessproposal],
                [Txn.application_args[0] == Bytes('vote'), on_vote],
            )

        def clear_program(self):
            GlobalInts = PreapprovalGate.GlobalInts
            LocalInts = PreapprovalGate.LocalInts
            return Seq([
                If(
                    And(
                        GlobalInts.VoteInProgress.get(),
                        LocalInts.VotedAppId.get(Txn.sender()) == GlobalInts.ConsideredAppId.get()
                    ),
                    If(
                        LocalInts.Vote.get(Txn.sender()),
                        GlobalInts.YesVotes.put(GlobalInts.YesVotes.get() - Int(1)),
                        GlobalInts.NoVotes.put(GlobalInts.NoVotes.get() - Int(1))
                    )
                ),
                Return(Int(1)),
            ])

        def local_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(
                len(PreapprovalGate.LocalInts),
                len(PreapprovalGate.LocalBytes),
            )

        def global_schema(self) -> transaction.StateSchema:
            return transaction.StateSchema(
                len(PreapprovalGate.GlobalInts),
                len(PreapprovalGate.GlobalBytes),
            )

    class DeployedGate(DeployedContract):
        def __init__(
                self,
                algod: AlgodClient,
                appid: int,
        ):
            appinfo: ApplicationInfo = algod.application_info(appid)
            self._committee_id: int = readintfromstore(
                appinfo['params']['global-state'],
                b'CommitteeId'
            )
            committeeinfo: ApplicationInfo = algod.application_info(self._committee_id)
            self._committee_asset_id: int = readintfromstore(
                committeeinfo['params']['global-state'],
                b'AssetId'
            )
            # self._committee_asset_id: int = committee_asset_id
            self._committee_addr: str = algosdk.logic.get_application_address(self._committee_id)
            self._trust_asset_id: Optional[int] = None
            super(PreapprovalGate.DeployedGate, self).__init__(appid)

        @property
        def trust_assetid(self):
            return self._trust_asset_id

        def call_inittoken(
                self,
                algod: AlgodClient,
                addr: str,
                privkey: str,
                asset_total: int,
                asset_unit_name: str,
                asset_name: str,
                asset_url: str
        ):
            info = self.call_method(
                algod,
                addr,
                privkey,
                b'inittoken',
                [
                    algodao.helpers.int2bytes(asset_total),
                    asset_unit_name.encode(),
                    asset_name.encode(),
                    asset_url.encode(),
                ]
            )
            self._trust_asset_id = info['inner-txns'][0]['asset-index']
            return info

        def call_assessproposal(
                self,
                algod: AlgodClient,
                addr: str,
                privkey: str,
                considered_appid: int
        ):
            considered_appaddr = algosdk.logic.get_application_address(considered_appid)
            return self.call_method(
                algod,
                addr,
                privkey,
                b'assessproposal',
                [
                    algodao.helpers.int2bytes(considered_appid),
                    algosdk.encoding.decode_address(considered_appaddr),
                ],
                foreign_apps=[self._committee_id],
                foreign_assets=[self._committee_asset_id],
            )

        def call_vote(
                self,
                algod: AlgodClient,
                addr: str,
                privkey: str,
                considered_appid: int,
                vote: int
        ):
            considered_appaddr = algosdk.logic.get_application_address(considered_appid)
            return self.call_method(
                algod,
                addr,
                privkey,
                b'vote',
                [
                    algodao.helpers.int2bytes(considered_appid),
                    algodao.helpers.int2bytes(vote)
                ],
                foreign_apps=[self._committee_id],
                foreign_assets=[self._committee_asset_id, self._trust_asset_id],
                accounts=[self._committee_addr, considered_appaddr],
            )

    @classmethod
    def deploy(cls, algod: AlgodClient, creategate: PreapprovalGate.CreateGate, privkey: str):
        appid = creategate.deploy(algod, privkey)
        return PreapprovalGate.DeployedGate(algod, appid)



class QuorumRequirement(enum.Enum):
    """
    Specify a requirement for a quorum; not implemented.
    """
    MINIMUM_VOTES = 0


class ApprovalMechanism(enum.Enum):
    """
    Specify an approval mechanism for a proposal; not implemented (all
    supported proposals are up/down votes with a required win percentage
    specified as a proposal rule).
    """
    PERCENTAGE_CUTOFF = 0
    TOP_VOTE_GETTERS = 1

