import logging
from collections import OrderedDict

import algosdk.logic
import pytest

import algodao.assets
import algodao.helpers
import algodao.voting
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
    createtree = algodao.assets.TokenDistributionTree.CreateTree(
        token,
        addr2count,
        beginreg,
        endreg,
    )
    deployed = algodao.assets.TokenDistributionTree.deploy(algod, createtree, creatorprivkey)
    appaddr = algosdk.logic.get_application_address(deployed.appid)
    tests.helpers.fund_account(algod, appaddr, 1000000)
    # tree.xferelectiontoken(algod, 10000, creatoraddr, creatorprivkey)
    # algodao.helpers.optinapp(algod, userprivkey, useraddr, appid)
    assetid = deployed.call_inittoken(
        algod,
        creatoraddr,
        creatorprivkey,
        100000,
        'VOTE',
        'Vote Token',
        'http://localhost/vote/token/info'
    )
    # tree.optintoken(algod, creatoraddr, creatorprivkey)
    algodao.helpers.optinasset(algod, useraddr, userprivkey, assetid)
    deployed.call_claim(algod, useraddr, userprivkey)
    useraccount = algod.account_info(useraddr)
    creatoraccount = algod.account_info(creatoraddr)
    appaccount = algod.account_info(appaddr)
    log.info(f'User account: {useraccount}')
    log.info(f'Creator account: {creatoraccount}')
    log.info(f'Application account: {appaccount}')


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
