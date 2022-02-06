import algosdk.logic

import algodao.helpers
import tests.helpers
from algodao.committee import Committee
from algodao.governance import PreapprovalGate
from algodao.voting import Proposal, ElectionToken


def test_approvalgate():
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)
    committee = Committee.CreateCommittee("Trusted", 5)
    deployedcommittee = Committee.deploy(algod, committee, creatorprivkey)
    committee_addr = algosdk.logic.get_application_address(deployedcommittee.appid)
    tests.helpers.fund_account(algod, committee_addr)
    deployedcommittee.call_inittoken(algod, creatorprivkey, creatoraddr)
    algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, deployedcommittee.assetid)
    deployedcommittee.call_setmembers(algod, creatorprivkey, creatoraddr, [creatoraddr])
    creategate = PreapprovalGate.CreateGate(deployedcommittee.appid, 1)
    gate = PreapprovalGate.deploy(algod, creategate, creatorprivkey)
    algodao.helpers.optinapp(algod, creatorprivkey, creatoraddr, gate.appid)
    gate_addr = algosdk.logic.get_application_address(gate.appid)
    tests.helpers.fund_account(algod, gate_addr)
    gate.call_inittoken(
        algod,
        creatoraddr,
        creatorprivkey,
        100,
        "Trusted",
        "TRUST",
        'http://localhost/abcd'
    )
    lastround = algod.status()['last-round']
    proposal = Proposal.CreateProposal(
        "Test Proposal",
        ElectionToken(10),
        lastround,
        lastround+1000,
        lastround,
        lastround+1000,
        2
    )
    deployedproposal = Proposal.deploy(algod, proposal, creatorprivkey)
    tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployedproposal.appid))
    deployedproposal.call_optintoken(algod, creatoraddr, creatorprivkey, gate._trust_asset_id)
    gate.call_assessproposal(algod, creatoraddr, creatorprivkey, deployedproposal.appid)
    gate.call_vote(algod, creatoraddr, creatorprivkey, deployedproposal.appid, 1)

