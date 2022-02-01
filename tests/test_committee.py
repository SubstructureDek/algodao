import algosdk.logic
import pytest

import algodao.committee
import algodao.helpers
import tests.helpers


def test_resign():
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)
    pk1, member1 = tests.helpers.add_standalone_account()
    pk2, member2 = tests.helpers.add_standalone_account()
    pk3, member3 = tests.helpers.add_standalone_account()
    initialmembers = [member1, member2, member3]
    pks = [pk1, pk2, pk3]
    committee = algodao.committee.Committee(
        "My Committee",
        4,
        1,
        []
    )
    appid = committee.deploycontract(algod, creatorprivkey)
    appaddr = algosdk.logic.get_application_address(appid)
    tests.helpers.fund_account(algod, appaddr)
    assetid = committee.call_inittoken(algod, creatorprivkey, creatoraddr)
    for member, pk in zip(initialmembers, pks):
        tests.helpers.fund_account(algod, member)
        algodao.helpers.optinasset(algod, member, pk, assetid)
    committee.call_setmembers(algod, creatorprivkey, creatoraddr, initialmembers)
    committee.call_checkmembership(algod, pk3, member3)
    committee.call_resign(algod, pk3, member3)
    with pytest.raises(algosdk.error.AlgodHTTPError, match='transaction rejected by ApprovalProgram'):
        committee.call_checkmembership(algod, pk3, member3)
