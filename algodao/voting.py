# This example is provided for informational purposes only and has not been
# audited for security.
import abc
from collections import OrderedDict
from typing import Callable, Dict, List, Tuple

import pyteal
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from pyteal import *

from algodao.types import AssetBalances
from algodao.merkle import MerkleTree


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


class Token(abc.ABC):
    @property
    @abc.abstractmethod
    def asset_id(self) -> int:
        """Returns the associated asset ID"""
        pass


class ElectionToken(Token):
    def __init__(self, asset_id):
        self._asset_id = asset_id

    @property
    def asset_id(self) -> int:
        return self._asset_id


class GovernanceToken(Token):
    def __init__(self, asset_id):
        self._asset_id = asset_id

    @property
    def asset_id(self) -> int:
        return self._asset_id


class TokenDistributionTree:
    def __init__(self, token: Token, addr2count: OrderedDict[str, int]):
        self._token = token
        self._addr2count = addr2count
        inputs: List[bytes] = [
            f'{address}:{count}'.encode('utf-8')
            for address, count in self._addr2count.items()
        ]
        self._tree = MerkleTree(inputs)

    def createcontract(self, algod: AlgodClient):
        pass

    def claimtokenscontract(self):
        # creation arguments: RootHash, RegBegin, RegEnd
        # Claim arguments: address, vote count, Merkle index, Merkle proof
        on_creation = Seq([
            Assert(Txn.application_args.length() == 3),
            App.globalPut(Bytes("RootHash"), Btoi(Txn.application_args[0])),
            App.globalPut(Bytes("RegBegin"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("RegEnd"), Btoi(Txn.application_args[2])),
            Return(Int(1)),
        ])
        is_creator = Txn.sender() == Global.creator_address()
        on_closeout = Seq([])
        on_register = Return(
            And(
                Global.round() >= App.globalGet(Bytes("RegBegin")),
                Global.round() <= App.globalGet(Bytes("RegEnd")),
            )
        )
        address = Txn.application_args[1]  # bytes
        count = Txn.application_args[2]  # uint64
        index = Txn.application_args[3]  # uint64
        proof = Txn.application_args[4]  # bytes
        roothash = App.globalGet(Bytes("RootHash"))  # bytes
        hash = ScratchVar(TealType.bytes)
        on_claim = Seq([
            Assert(
                And(
                    Txn.application_args.length() == 3,
                    Global.round() >= App.globalGet(Bytes("RegBegin")),
                    Global.round() <= App.globalGet(Bytes("RegEnd")),
                )
            ),
            hash.store(Sha256(Concat(address, Bytes(':'), Itob(count)))),
            self.verifymerkle(index, proof, hash, roothash),
            Return(Int(1)),
        ])
        program = Cond(
            [Txn.application_id() == Int(0), on_creation],
            [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
            [Txn.on_completion() == OnComplete.OptIn, on_register],
            [Txn.application_args[0] == Bytes("claim"), on_claim],
        )
        return program

    def verifymerkle(self, index, proof, hash: ScratchVar, roothash):
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
                        hash.store(Sha256(Concat(
                            Substring(proof, i.load(), i.load() + Int(32)),
                            hash.load())))
                        ,
                        hash.store(Sha256(Concat(
                            hash.load(),
                            Substring(proof, i.load(), i.load() + Int(32))))
                        )
                    ),
                    levelindex.store(levelindex.load() / Int(2)),
                ])
            ),
            Assert(hash == roothash)
        ])



class Election:
    def __init__(
            self,
            indexer: IndexerClient,
            governence_token: GovernanceToken,
            vote_token: ElectionToken,
            governance2votes: Callable[[int], int]
    ):
        self._governance_token: GovernanceToken = governence_token
        self._vote_token: ElectionToken = vote_token
        self._indexer: IndexerClient = indexer
        self._gov2votes = governance2votes

    def builddistribution(self):
        balance_dict: Dict[str, int] = self.gettokencounts()
        votedist: OrderedDict[str, int] = OrderedDict(
            (address, self._gov2votes(govcount))
            for address, govcount in balance_dict
        )
        return TokenDistributionTree(self._vote_token, votedist)

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
