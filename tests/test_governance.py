import algosdk.logic

import algodao.helpers
import tests.helpers
from algodao.committee import Committee
from algodao.governance import CreateStaticPreapprovalGate, DeployedStaticPreapprovalGate


def test_approvalgate():
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)
    committee = Committee("Trusted", 5)
    committee_id = committee.deploycontract(algod, creatorprivkey)
    committee_addr = algosdk.logic.get_application_address(committee_id)
    tests.helpers.fund_account(algod, committee_addr)
    committee.call_inittoken(algod, creatorprivkey, creatoraddr)
    algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, committee.assetid)
    committee.call_setmembers(algod, creatorprivkey, creatoraddr, [creatoraddr])
    creategate = CreateStaticPreapprovalGate(algod, committee_id, 1)
    appid = creategate.deploy(algod, creatorprivkey)
    gate = DeployedStaticPreapprovalGate(appid)
    gate_addr = algosdk.logic.get_application_address(appid)
    tests.helpers.fund_account(algod, gate_addr)
    gate.call_inittoken(algod, creatoraddr, creatorprivkey, 100, "Trusted", "TRUST", 'http://localhost/abcd')

