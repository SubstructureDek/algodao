import logging
from collections import OrderedDict

import algosdk.error
import algosdk.future.transaction
import pytest

import algodao.deploy
import algodao.helpers
import algodao.assets
import algodao.voting
from algodao.types import AccountInfo

import tests.helpers

log = logging.getLogger(__name__)



def test_createaccount():
    amount = 100000
    client = algodao.helpers.createclient()
    privkey, addr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, addr, amount)
    info: AccountInfo = client.account_info(addr)
    log.info(info)
    assert info['amount'] == amount


def test_nfttransfer():
    amount = 1000000
    client = algodao.helpers.createclient()
    privkey, addr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, addr, amount)
    assetid = _createnft(client, addr, privkey)
    assert algodao.assets.hasasset(client, addr, assetid)

    recvprivkey, recvaddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, recvaddr, 1000000)
    params = client.suggested_params()
    txn = algosdk.future.transaction.AssetTransferTxn(
        recvaddr,
        params,
        recvaddr,
        0,
        assetid
    )
    signed = txn.sign(recvprivkey)
    txid = client.send_transaction(signed)
    algodao.helpers.wait_for_confirmation(client, txid)
    txn = algosdk.future.transaction.AssetTransferTxn(
        addr,
        params,
        recvaddr,
        1,
        assetid,
        note="NFT transfer"
    )
    signed = txn.sign(privkey)
    txid = client.send_transaction(signed)
    algodao.helpers.wait_for_confirmation(client, txid)
    log.info(client.account_info(recvaddr))
    assert algodao.assets.hasasset(client, recvaddr, assetid)


def test_proposal():
    amount = 1000000
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(algod, creatoraddr, amount)
    token = algodao.voting.ElectionToken(_createnft(algod, creatoraddr, creatorprivkey))
    userprivkey, useraddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(algod, useraddr, amount)
    status = algod.status()
    regbegin = status['last-round']
    regend = regbegin + 1000
    votebegin = regbegin
    voteend = regend
    num_options = 3
    proposal = algodao.voting.Proposal(
        "Test Proposal",
        token,
        regbegin,
        regend,
        votebegin,
        voteend,
        num_options
    )
    appid = proposal.deploycontract(algod, creatorprivkey)
    appaddr = algosdk.logic.get_application_address(appid)
    tests.helpers.fund_account(algod, appaddr, amount)
    proposal.optintoken(algod, creatoraddr, creatorprivkey)
    algodao.helpers.optinasset(algod, useraddr, userprivkey, token.asset_id)
    algodao.helpers.transferasset(algod, creatoraddr, creatorprivkey, useraddr, token.asset_id, 10)
    algodao.helpers.optinapp(algod, userprivkey, useraddr, appid)
    proposal.sendvote(algod, userprivkey, useraddr, 2, 10)

# from pyteal import *
# from algosdk.future.transaction import StateSchema
# def test_largecontract():
#     algod = algodao.helpers.createclient()
#     privkey, addr = tests.helpers.create_funded(algod, 100000000)
#     index = ScratchVar(TealType.uint64)
#     approval_program = Cond([
#         Txn.application_id() == Int(0),
#         Seq([
#             For(
#                 index.store(Int(0)),
#                 index.load() < Int(1000),
#                 index.store(index.load() + Int(1))
#             ).Do(
#                 App.globalPut(Concat(Bytes("Var"), Itob(index.load())), index.load())
#             ),
#             Return(Int(1)),
#         ])
#     ])
#     approval_compiled = algodao.deploy.compile_program(
#         algod,
#         compileTeal(approval_program, mode=Mode.Application, version=5)
#     )
#     clear_compiled = algodao.deploy.compile_program(
#         algod,
#         compileTeal(Return(Int(1)), mode=Mode.Application, version=5)
#     )
#     local_schema = StateSchema(0, 0)
#     global_schema = StateSchema(1000, 0)
#     algodao.deploy.create_app(
#         algod,
#         privkey,
#         approval_compiled,
#         clear_compiled,
#         global_schema,
#         local_schema,
#         []
#     )
