import logging

import algosdk.error
import algosdk.future.transaction
import pytest

import algodao.deploy
import algodao.helpers
import algodao.assets
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
    assert algodao.assets.hasasset(client, addr, addr, assetid)

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
    assert algodao.assets.hasasset(client, recvaddr, addr, assetid)


def _createnft(client, addr, privkey) -> int:
    count = 100
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
