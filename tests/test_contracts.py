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


def test_distributiontree():
    amount = 1000000
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(algod, creatoraddr, amount)
    token = algodao.voting.ElectionToken(_createnft(algod, creatoraddr, creatorprivkey))
    userprivkey, useraddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(algod, useraddr, amount)
    addr2count: OrderedDict[str, int] = OrderedDict({
        useraddr: 1000,
        'b'*64: 1500,
        'c'*64: 2200,
        'd'*64: 1523,
    })
    status = algod.status()
    beginreg = status['last-round']
    # make the registration period very long for testing so that we can take
    # a dry-run and debug it for a long period if needed
    endreg = beginreg + 1000
    tree = algodao.assets.TokenDistributionTree(
        token,
        addr2count,
        beginreg,
        endreg,
    )
    appid = tree.createcontract(algod, creatorprivkey)
    appaddr = algosdk.logic.get_application_address(appid)
    tests.helpers.fund_account(algod, appaddr, 1000000)
    # tree.xferelectiontoken(algod, 10000, creatoraddr, creatorprivkey)
    # algodao.helpers.optinapp(algod, userprivkey, useraddr, appid)
    assetid = tree.inittoken(algod, useraddr, userprivkey)
    # tree.optintoken(algod, creatoraddr, creatorprivkey)
    algodao.helpers.optinasset(algod, useraddr, userprivkey, assetid)
    tree.callapp(algod, useraddr, userprivkey)
    useraccount = algod.account_info(useraddr)
    creatoraccount = algod.account_info(creatoraddr)
    appaccount = algod.account_info(appaddr)
    log.info(f'User account: {useraccount}')
    log.info(f'Creator account: {creatoraccount}')
    log.info(f'Application account: {appaccount}')


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


def _createnft(client, addr, privkey) -> int:
    count = 10000
    unitname = "MYNFT"
    assetname = "MyNFT"
    metadata = algodao.assets.createmetadata(
        assetname,
        "My NFT Asset",
        {},
        ""
    )
    url = 'https://localhost/my/nft/url'
    assetid = algodao.assets.createasset(
        client,
        addr,
        privkey,
        metadata,
        count,
        unitname,
        assetname,
        url
    )
    log.info(f"Created asset ID {assetid}")
    log.info(client.account_info(addr))
    return assetid


def test_nftcontract():
    client = algodao.helpers.createclient()
    privkey, addr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, addr, 1000000)
    program = algodao.assets.NftCheckProgram()
    assetid = _createnft(client, addr, privkey)
    appid = program.deploy(client, assetid, privkey)
    # algodao.deploy.call_app(client, privkey, appid, ['test'])
    txn = algosdk.future.transaction.ApplicationNoOpTxn(
        addr,
        client.suggested_params(),
        appid,
        ['abc'],
        foreign_assets=[assetid],
    )
    signed = txn.sign(privkey)
    txid = client.send_transaction(signed)
    algodao.helpers.wait_for_confirmation(client, txid)
    log.info("Success")
    privkey2, addr2 = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, addr2, 1000000)
    txn = algosdk.future.transaction.ApplicationNoOpTxn(
        addr2,
        client.suggested_params(),
        appid,
        ['abc'],
        foreign_assets=[assetid],
    )
    signed = txn.sign(privkey2)
    with pytest.raises(algosdk.error.AlgodHTTPError):
        txid = client.send_transaction(signed)
        algodao.helpers.wait_for_confirmation(client, txid)


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
