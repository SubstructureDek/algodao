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
    createcommittee = algodao.committee.Committee.CreateCommittee(
        "My Committee",
        4,
    )
    deployed = algodao.committee.Committee.deploy(algod, createcommittee, creatorprivkey)
    appaddr = algosdk.logic.get_application_address(deployed.appid)
    tests.helpers.fund_account(algod, appaddr)
    assetid = deployed.call_inittoken(algod, creatorprivkey, creatoraddr)
    for member, pk in zip(initialmembers, pks):
        tests.helpers.fund_account(algod, member)
        algodao.helpers.optinasset(algod, member, pk, assetid)
    deployed.call_setmembers(algod, creatorprivkey, creatoraddr, initialmembers)
    deployed.call_checkmembership(algod, pk3, member3)
    deployed.call_resign(algod, pk3, member3)
    with pytest.raises(algosdk.error.AlgodHTTPError, match='transaction rejected by ApprovalProgram'):
        deployed.call_checkmembership(algod, pk3, member3)
