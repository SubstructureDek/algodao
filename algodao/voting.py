# This example is provided for informational purposes only and has not been
# audited for security.
import pyteal
from pyteal import *


class Proposal:
    def __init__(
            self,
            name: str,
            start_vote: int,
            end_vote: int,
            num_options: int,
    ):
        self._name: str = name
        self._start_vote: int = start_vote
        self._end_vote: int = end_vote
        self._num_options: int = num_options

    def approval_program(self):
        expected_args = 4
        on_creation = Seq([
            Assert(Txn.application_args.length() == Int(expected_args)),
            App.globalPut(Bytes("VoteBegin"), Btoi(Txn.application_args[0])),
            App.globalPut(Bytes("VoteEnd"), Btoi(Txn.application_args[1])),
            Return(Int(1)),
        ])
        is_creator = Txn.sender() == Global.creator_address()
        option = Btoi(Txn.application_args[1])
        votes = Btoi(Txn.application_args[2])
        on_vote = Seq([
            Assert(And(
                Global.round() >= App.globalGet(Bytes("VoteBegin")),
                Global.round() <= App.globalGet(Bytes("VoteEnd"))
            )),
            App.localPut(Txn.sender(), Bytes("Voted" + str(option)), votes)
        ])


class ElectionToken:
    def __init__(self, asset_id):
        self._asset_id = asset_id


class Election:
    def __init__(self, vote_token: ElectionToken):
        self._vote_token = vote_token

    def buildmerkle(self):
        pass

def approval_program():
    on_creation = Seq(
        [
            App.globalPut(Bytes("Creator"), Txn.sender()),
            Assert(Txn.application_args.length() == Int(4)),
            App.globalPut(Bytes("RegBegin"), Btoi(Txn.application_args[0])),
            App.globalPut(Bytes("RegEnd"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("VoteBegin"), Btoi(Txn.application_args[2])),
            App.globalPut(Bytes("VoteEnd"), Btoi(Txn.application_args[3])),
            Return(Int(1)),
        ]
    )

    is_creator = Txn.sender() == App.globalGet(Bytes("Creator"))

    get_vote_of_sender = App.localGetEx(Int(0), App.id(), Bytes("voted"))

    on_closeout = Seq(
        [
            get_vote_of_sender,
            If(
                And(
                    Global.round() <= App.globalGet(Bytes("VoteEnd")),
                    get_vote_of_sender.hasValue(),
                ),
                App.globalPut(
                    get_vote_of_sender.value(),
                    App.globalGet(get_vote_of_sender.value()) - Int(1),
                ),
            ),
            Return(Int(1)),
        ]
    )

    on_register = Return(
        And(
            Global.round() >= App.globalGet(Bytes("RegBegin")),
            Global.round() <= App.globalGet(Bytes("RegEnd")),
        )
    )

    choice = Txn.application_args[1]
    choice_tally = App.globalGet(choice)
    on_vote = Seq(
        [
            Assert(
                And(
                    Global.round() >= App.globalGet(Bytes("VoteBegin")),
                    Global.round() <= App.globalGet(Bytes("VoteEnd")),
                )
            ),
            get_vote_of_sender,
            If(get_vote_of_sender.hasValue(), Return(Int(0))),
            App.globalPut(choice, choice_tally + Int(1)),
            App.localPut(Int(0), Bytes("voted"), choice),
            Return(Int(1)),
        ]
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_creation],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_creator)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_creator)],
        [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
        [Txn.on_completion() == OnComplete.OptIn, on_register],
        [Txn.application_args[0] == Bytes("vote"), on_vote],
    )

    return program


def clear_state_program():
    get_vote_of_sender = App.localGetEx(Int(0), App.id(), Bytes("voted"))
    program = Seq(
        [
            get_vote_of_sender,
            If(
                And(
                    Global.round() <= App.globalGet(Bytes("VoteEnd")),
                    get_vote_of_sender.hasValue(),
                ),
                App.globalPut(
                    get_vote_of_sender.value(),
                    App.globalGet(get_vote_of_sender.value()) - Int(1),
                ),
            ),
            Return(Int(1)),
        ]
    )

    return program


if __name__ == "__main__":
    with open("vote_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=2)
        f.write(compiled)

    with open("vote_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=2)
        f.write(compiled)
