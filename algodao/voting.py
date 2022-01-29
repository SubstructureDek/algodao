# This example is provided for informational purposes only and has not been
# audited for security.
import abc
import base64
import logging
from collections import OrderedDict
from typing import Callable, Dict, List, Tuple, Optional

import pyteal
import algosdk.account
import algosdk.logic
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from pyteal import *

import algodao.helpers
from algodao.types import AssetBalances, PendingTransactionInfo
from algodao.merkle import MerkleTree

log = logging.getLogger(__name__)


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
    def __init__(
            self,
            token: Token,
            addr2count: OrderedDict[str, int],
            beginreg: int,
            endreg: int,
    ):
        self._token = token
        self._addr2count = addr2count
        # note that for simplicity in the teal contract, the count here is
        # represented in its uint64 bytes representation rather than a human
        # readable representation; e.g., if address 'abcd' is assigned a
        # count of 8, the leaf value that is hashed is:
        # b'abcd:\x00\x00\x00\x00\x00\x00\x00\x10'
        inputs: List[bytes] = [
            f'{address}:'.encode('utf-8') + algodao.helpers.int2bytes(count)
            for address, count in self._addr2count.items()
        ]
        self._tree = MerkleTree(inputs)
        self._beginreg = beginreg
        self._endreg = endreg
        self._appid: Optional[int] = None

    def createcontract(
            self,
            algod: AlgodClient,
            senderaddr: str,
            privkey: str,
    ):
        on_complete: transaction.OnComplete = transaction.OnComplete.NoOpOC
        params = algod.suggested_params()
        approval_program, clear_program = self.compile(algod)
        local_ints = 0
        local_bytes = 0
        global_ints = 3
        global_bytes = 1
        global_schema = transaction.StateSchema(global_ints, global_bytes)
        local_schema = transaction.StateSchema(local_ints, local_bytes)
        app_args = self.createappargs()
        txn = transaction.ApplicationCreateTxn(
            senderaddr,
            params,
            on_complete,
            approval_program,
            clear_program,
            global_schema,
            local_schema,
            app_args,
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)
        response: PendingTransactionInfo = algod.pending_transaction_info(txid)
        app_id = response['application-index']
        log.info(f'Created new app-id: {app_id}')
        self._appid = app_id
        return app_id

    def inittoken(self, algod: AlgodClient, addr: str, privkey: str):
        args: List[bytes] = [
            b'inittoken'
        ]
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            args,
        )
        signed = txn.sign(privkey)
        txid = algod.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(algod, txid)
        info = algod.pending_transaction_info(txid)
        self._token = ElectionToken(info['inner-txns'][0]['asset-index'])
        return self._token.asset_id

    def callapp(self, algod: AlgodClient, addr: str, privkey: str):
        assert addr in self._addr2count
        index = list(self._addr2count.keys()).index(addr)
        proof: List[bytes] = self._tree.createproof(index)
        count: int = self._addr2count[addr]
        # concatenate all the proof hashes together. the contract will index
        # into the byte array as appropriate while stepping through the proof
        proof_bytes: bytes = b''.join(proof)
        args: List[bytes] = [
            b'claim',
            addr.encode('utf-8'),
            algodao.helpers.int2bytes(count),
            algodao.helpers.int2bytes(index),
            proof_bytes
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

    def createappargs(self):
        return [
            self._tree.roothash,
            self._beginreg,
            self._endreg,
        ]

    def compile(self, algod: AlgodClient) -> Tuple[bytes, bytes]:
        approval_ast = self.claimtokenscontract()
        approval_teal = pyteal.compileTeal(approval_ast, Mode.Application, version=5)
        approval_response = algod.compile(approval_teal)
        approval_compiled = base64.b64decode(approval_response['result'])
        clear_ast = Return(Int(1))
        clear_teal = pyteal.compileTeal(clear_ast, Mode.Application, version=5)
        clear_response = algod.compile(clear_teal)
        clear_compiled = base64.b64decode(clear_response['result'])
        return approval_compiled, clear_compiled

    def claimtokenscontract(self):
        # creation arguments: RootHash, RegBegin, RegEnd
        # Claim arguments: address, vote count, Merkle index, Merkle proof
        on_creation = Seq([
            Assert(Txn.application_args.length() == Int(3)),
            App.globalPut(Bytes("RootHash"), Txn.application_args[0]),
            App.globalPut(Bytes("RegBegin"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("RegEnd"), Btoi(Txn.application_args[2])),
            App.globalPut(Bytes("AssetId"), Int(0)),
            Return(Int(1)),
        ])
        is_creator = Txn.sender() == Global.creator_address()
        on_inittoken = Seq([
            # Assert(is_creator),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetConfig,
                TxnField.config_asset_total: Int(10000),
                TxnField.config_asset_unit_name: Bytes('VOTE'),
                TxnField.config_asset_name: Bytes("Vote"),
                TxnField.config_asset_url: Bytes("https://localhost"),
                TxnField.config_asset_manager: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),
            App.globalPut(Bytes("AssetId"), InnerTxn.created_asset_id()),
            Return(Int(1)),
        ])
        on_closeout = Return(Int(1))
        on_register = Return(
            And(
                Global.round() >= App.globalGet(Bytes("RegBegin")),
                Global.round() <= App.globalGet(Bytes("RegEnd")),
            )
        )
        address = Txn.application_args[1]  # bytes
        count = Txn.application_args[2]  # bytes representation of a uint64
        index = Btoi(Txn.application_args[3])  # uint64
        proof = Txn.application_args[4]  # bytes
        roothash = App.globalGet(Bytes("RootHash"))  # bytes
        hash = ScratchVar(TealType.bytes)
        on_claim = Seq([
            Assert(
                And(
                    Txn.application_args.length() == Int(5),
                    Global.round() >= App.globalGet(Bytes("RegBegin")),
                    Global.round() <= App.globalGet(Bytes("RegEnd")),
                )
            ),
            hash.store(Sha256(Concat(address, Bytes(':'), count))),
            self.verifymerkle(index, proof, hash, roothash),
            self.transferelectiontokens(Btoi(count)),
            Return(Int(1)),
        ])
        program = Cond(
            [Txn.application_id() == Int(0), on_creation],
            [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_creator)],
            [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
            [Txn.on_completion() == OnComplete.OptIn, on_register],
            [Txn.application_args[0] == Bytes("claim"), on_claim],
            [Txn.application_args[0] == Bytes('inittoken'), on_inittoken],
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
                            hash.load(),
                            Substring(proof, i.load(), i.load() + Int(32)),
                        ))),
                        hash.store(Sha256(Concat(
                            Substring(proof, i.load(), i.load() + Int(32)),
                            hash.load()
                        )))
                    ),
                    levelindex.store(levelindex.load() / Int(2)),
                ])
            ),
            Assert(hash.load() == roothash)
        ])

    def transferelectiontokens(self, count):
        return Seq([
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(Bytes("AssetId")),  #Int(self._token.asset_id),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: count,
            }),
            InnerTxnBuilder.Submit(),
        ])

    def xferelectiontoken(self, algod: AlgodClient, amount: int, sendaddr: str, sendprivkey: str):
        appaddr = algosdk.logic.get_application_address(self._appid)
        algodao.helpers.optinasset(algod, appaddr, sendprivkey, self._token.asset_id)
        algodao.helpers.transferasset(
            algod,
            sendaddr,
            sendprivkey,
            appaddr,
            self._token.asset_id,
            amount
        )


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
