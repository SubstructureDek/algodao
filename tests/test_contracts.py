import logging

import algosdk.future.transaction

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
    recvprivkey, recvaddr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(client, recvaddr, 1000000)
    assert algodao.assets.hasasset(client, addr, addr, assetid)
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
