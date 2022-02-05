import enum
from typing import List

import algosdk.logic
from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from pyteal import Seq, Assert, App, Return, Int, Btoi, Txn, Expr, Bytes
from pyteal import Cond, Gtxn, Global, Len, Concat, OnComplete, And, Or, Not
from pyteal import InnerTxnBuilder, TxnField, TxnType, If, ScratchVar, TealType
from pyteal import InnerTxn, OnComplete

import algodao.helpers
from algodao.committee import is_member, current_committee_size_ex, set_asset_freeze, send_asset
from algodao.contract import CreateContract, DeployedContract


class AlgoDao:
    def __init__(self):
        pass

    def algodaocontract(self) -> Expr:
        on_creation = Seq([
            Assert(Txn.application_args.length() == Int(1)),
            App.globalPut(Bytes("Name"), Txn.application_args[0]),
            App.globalPut(Bytes("Committees"), Bytes(b'')),
            App.globalPut(Bytes("Finalized"), Int(0)),
            App.globalPut(Bytes("Closed"), Int(0)),
            App.globalPut(Bytes("ProposalRules"), Bytes(b'')),
            Return(Int(1)),
        ])
        setup_phase_approved = And(
            Not(App.globalGet(Bytes("Finalized"))),
            Txn.sender() == Global.creator_address()
        )
        on_addcommittee = Seq([
            Assert(setup_phase_approved),
            Assert(Txn.application_args.length() == Int(1)),
            Assert(Len(Txn.application_args[0]) == Int(8)),
            App.globalPut(
                Bytes("Committees"),
                Concat(
                    App.globalGet(Bytes("Committees")),
                    Txn.application_args[0]
                )
            ),
            Return(Int(1)),
        ])

        on_addrule = Seq([
            Assert(setup_phase_approved),
            Assert(Txn.application_args.length() == Int(1)),
            Assert(Len(Txn.application_args[0]) == Int(8)),
            App.globalPut(
                Bytes("ProposalRules"),
                Concat(
                    App.globalGet(Bytes("ProposalRules")),
                    Txn.application_args[0]
                )
            ),
            Return(Int(1)),
        ])
        on_finalize = Seq([
            Assert(setup_phase_approved),
            Assert(Txn.application_args.length() == Int(0)),
            App.globalPut(Bytes("Finalized"), Int(1)),
            Return(Int(1)),
        ])
        can_delete = Seq([
            Return(Or(
                # DAO has not been finalized and sender is attempting to delete
                setup_phase_approved,
                # or, DAO has been closed out by the specified closure process,
                App.globalGet(Bytes("Closed")),
            ))
        ])
        # TODO: add ability to change governance structure via proposal
        can_update = Return(Int(0))
        return Cond(
            [Txn.application_id == Int(0), on_creation],
            [Txn.on_completion() == OnComplete.DeleteApplication, can_delete],
            [Txn.on_completion() == OnComplete.UpdateApplication, can_update],
            [Txn.application_args[0] == Bytes('addcommittee'), on_addcommittee],
            [Txn.application_args[0] == Bytes('addrule'), on_addrule],
            [Txn.application_args[0] == Bytes('finalize'), on_finalize],
        )


class CreateStaticPreapprovalGate(CreateContract):
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
    def __init__(
            self,
            algod: AlgodClient,
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
        on_creation = Seq([
            App.globalPut(Bytes("Initialized"), Int(0)),
            App.globalPut(Bytes("ConsideredAppId"), Int(0)),
            App.globalPut(Bytes("ConsideredAppAddr"), Bytes(b'')),
            App.globalPut(Bytes("YesVotes"), Int(0)),
            App.globalPut(Bytes("NoVotes"), Int(0)),
            App.globalPut(Bytes("CommitteeId"), Btoi(Txn.application_args[0])),
            # TODO: necessary to save both the app id and the address?
            App.globalPut(Bytes("CommitteeAddr"), Txn.application_args[1]),
            App.globalPut(Bytes("VotingStartRound"), Int(0)),
            App.globalPut(Bytes("VoteInProgress"), Int(0)),
            App.globalPut(Bytes("TrustAssetId"), Int(0)),
            App.globalPut(Bytes("MinRoundsPerProposal"), Btoi(Txn.application_args[2])),
            Return(Int(1)),
        ])
        on_inittoken = Seq([
            Assert(Not(App.globalGet(Bytes("Initialized")))),
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
            App.globalPut(Bytes("TrustAssetId"), InnerTxn.created_asset_id()),
            App.globalPut(Bytes("Initialized"), Int(1)),
            Return(Int(1)),
        ])
        assetid = App.globalGetEx(App.globalGet(Bytes("CommitteeId")), Bytes("AssetId"))
        committeesize = current_committee_size_ex(
            App.globalGet(Bytes("CommitteeId")),
            App.globalGet(Bytes("CommitteeAddr"))
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
                App.globalGet(Bytes("VoteInProgress")),
                Assert(Global.round() > App.globalGet(Bytes("VotingStartRound"))
                       + App.globalGet(Bytes("MinRoundsPerProposal")))
            ),
            App.globalPut(Bytes("VoteInProgress"), Int(1)),
            App.globalPut(Bytes("VotingStartRound"), Global.round()),
            App.globalPut(Bytes("ConsideredAppId"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("ConsideredAppAddr"), Txn.application_args[2]),
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
            Assert(App.globalGet(Bytes("ConsideredAppId")) == Btoi(Txn.application_args[1])),
            # check that the vote is in fact in progress
            Assert(App.globalGet(Bytes("VoteInProgress"))),
            If(
                App.localGet(Txn.sender(), Bytes("VotedAppId")) == App.globalGet(Bytes("ConsideredAppId")),
                # user has already voted on this proposal; first rescind their
                # previous vote
                If(
                    App.localGet(Txn.sender(), Bytes("Vote")),
                    App.globalPut(Bytes("YesVotes"), App.globalGet(Bytes("YesVotes")) - Int(1)),
                    App.globalPut(Bytes("NoVotes"), App.globalGet(Bytes("NoVotes")) - Int(1))
                )
            ),
            App.localPut(Txn.sender(), Bytes("VotedAppId"), App.globalGet(Bytes("ConsideredAppId"))),
            App.localPut(Txn.sender(), Bytes("Vote"), Btoi(Txn.application_args[2])),
            If(
                App.localGet(Txn.sender(), Bytes("Vote")),
                App.globalPut(Bytes("YesVotes"), App.globalGet(Bytes("YesVotes")) + Int(1)),
                App.globalPut(Bytes("NoVotes"), App.globalGet(Bytes("NoVotes")) + Int(1))
            ),
            # if this vote leads to a definitive result, immediately close the
            # vote and execute on the result
            If(
                # TODO: allow approval method other than majority vote
                App.globalGet(Bytes("YesVotes")) > committeesize / Int(2),
                Seq([
                    set_asset_freeze(
                        Global.current_application_address(),
                        App.globalGet(Bytes("TrustAssetId")),
                        Int(0)
                    ),
                    send_asset(
                        App.globalGet(Bytes("ConsideredAppAddr")),
                        App.globalGet(Bytes("TrustAssetId"))
                    ),
                    set_asset_freeze(
                        App.globalGet(Bytes("ConsideredAppAddr")),
                        App.globalGet(Bytes("TrustAssetId")),
                        Int(1),
                    ),
                    App.globalPut(Bytes("VoteInProgress"), Int(0)),
                ])
            ),
            If(
                App.globalGet(Bytes("NoVotes")) > committeesize / Int(2),
                Seq([
                    App.globalPut(Bytes("VoteInProgress"), Int(0)),
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
        return Seq([
            If(
                And(
                    App.globalGet(Bytes("VoteInProgress")),
                    App.localGet(Txn.sender(), Bytes("VotedAppId")) == App.globalGet(Bytes("ConsideredAppId"))
                ),
                If(
                    App.localGet(Txn.sender(), Bytes("Vote")),
                    App.globalPut(Bytes("YesVotes"), App.globalGet(Bytes("YesVotes")) - Int(1)),
                    App.globalPut(Bytes("NoVotes"), App.globalGet(Bytes("NoVotes")) - Int(1))
                )
            ),
            Return(Int(1)),
        ])

    def local_schema(self) -> transaction.StateSchema:
        return transaction.StateSchema(
            2,
            0
        )

    def global_schema(self) -> transaction.StateSchema:
        return transaction.StateSchema(
            9,
            2
        )

class DeployedStaticPreapprovalGate(DeployedContract):
    def __init__(
            self,
            appid: int,
            committee_id: int,
            committee_asset_id: int,
            committee_address: str,
    ):
        self._committee_id: int = committee_id
        self._committee_asset_id: int = committee_asset_id
        self._committee_addr: str = committee_address
        self._trust_asset_id: int = None
        super(DeployedStaticPreapprovalGate, self).__init__(appid)

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


class VoteType(enum.Enum):
    COMMITTEE = 0
    GOVERNANCE_TOKEN = 1


class QuorumRequirement(enum.Enum):
    MINIMUM_VOTES = 0


class ApprovalMechanism(enum.Enum):
    PERCENTAGE_CUTOFF = 0
    TOP_VOTE_GETTERS = 1


class ProposalType(enum.Enum):
    PAYMENT = 0
    ADD_COMMITTEE_MEMBER = 1
    CLOSE_AND_DISBURSE = 2
    EJECT_COMMITTEE_MEMBER = 3
    NEW_COMMITTEE = 4


class GovernanceType:
    def __init__(self):
        pass
