import enum

from pyteal import Seq, Assert, App, Return, Int, Btoi, Txn, Expr, Bytes
from pyteal import Cond, Gtxn, Global, Len, Concat, OnComplete, And, Or, Not


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
        can_update = Return()
        return Cond(
            [Txn.application_id == Int(0), on_creation],
            [Txn.on_completion() == OnComplete.DeleteApplication, can_delete],
            [Txn.on_completion() == OnComplete.UpdateApplication, can_update],
            [Txn.application_args[0] == Bytes('addcommittee'), on_addcommittee],
            [Txn.application_args[0] == Bytes('addrule'), on_addrule],
            [Txn.application_args[0] == Bytes('finalize'), on_finalize],
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
