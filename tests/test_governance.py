from typing import Optional

import algosdk.logic

import algodao.helpers
import tests.helpers
from algodao.committee import Committee
from algodao.governance import PreapprovalGate, AlgoDao
from algodao.voting import Proposal, ElectionToken, ProposalType, VoteType
from tests.test_contracts import _createnft


def test_approvalgate():
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)
    deployedcommittee = create_trustcommittee(algod, creatoraddr, creatorprivkey)
    gate = create_preapprovalgate(algod, deployedcommittee, creatoraddr, creatorprivkey)
    token = ElectionToken(_createnft(algod, creatoraddr, creatorprivkey))
    deployedproposal = create_proposal(algod, gate, creatoraddr, creatorprivkey, token)
    preapprove_proposal(algod, gate, deployedproposal, creatoraddr, creatorprivkey)


def test_daoproposal():
    algod = algodao.helpers.createclient()
    creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)
    deployedcommittee = create_trustcommittee(algod, creatoraddr, creatorprivkey)
    gate = create_preapprovalgate(algod, deployedcommittee, creatoraddr, creatorprivkey)
    dao = AlgoDao.CreateDao("My DAO", gate.trust_assetid)
    receiverprivkey, receiveraddr = tests.helpers.create_funded(algod)
    deployeddao = AlgoDao.deploy(algod, dao, creatorprivkey)
    tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployeddao.appid))
    deployeddao.call_addrule(
        algod,
        creatoraddr,
        creatorprivkey,
        ProposalType.PAYMENT,
        VoteType.GOVERNANCE_TOKEN,
        60
    )
    deployeddao.call_finalize(algod, creatoraddr, creatorprivkey)
    token = ElectionToken(_createnft(algod, creatoraddr, creatorprivkey))
    deployedproposal = create_proposal(
        algod,
        gate,
        creatoraddr,
        creatorprivkey,
        token,
        receiveraddr,
        10000,
        voting_rounds=20,
        daoid=deployeddao.appid,
        win_pct=60,
    )
    waitforoundround = algod.status()['last-round'] + 21
    preapprove_proposal(algod, gate, deployedproposal, creatoraddr, creatorprivkey)
    algodao.helpers.optinapp(algod, creatorprivkey, creatoraddr, deployedproposal.appid)
    deployedproposal.call_vote(algod, creatoraddr, creatorprivkey, 1, 10)
    algodao.helpers.wait_for_round(algod, waitforoundround)
    deployedproposal.call_finalizevote(algod, creatoraddr, creatorprivkey)
    deployeddao.call_implementproposal(
        algod,
        deployedproposal,
        creatoraddr,
        creatorprivkey,
        accounts=[receiveraddr],
    )


def preapprove_proposal(algod, gate, deployedproposal, addr, privkey):
    gate.call_assessproposal(algod, addr, privkey, deployedproposal.appid)
    gate.call_vote(algod, addr, privkey, deployedproposal.appid, 1)


def create_proposal(
        algod,
        gate,
        addr,
        privkey,
        token: ElectionToken = None,
        payee: Optional[str] = None,
        payee_amount: Optional[int] = None,
        voting_rounds: int = 1000,
        daoid: int = 0,
        win_pct: Optional[int] = None,
) -> Proposal.DeployedProposal:
    lastround = algod.status()['last-round']
    proposal = Proposal.CreateProposal(
        "Test Proposal",
        token,
        lastround,
        lastround + voting_rounds,
        lastround,
        lastround + voting_rounds,
        2,
        daoid,
        ProposalType.PAYMENT,
    )
    if payee is not None:
        proposal.setpaymentinfo(payee, payee_amount)
    if win_pct is not None:
        proposal.setvotedata(VoteType.GOVERNANCE_TOKEN, win_pct)
    deployedproposal = Proposal.deploy(algod, proposal, privkey)
    tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployedproposal.appid))
    deployedproposal.call_optintoken(algod, addr, privkey, gate.trust_assetid)
    deployedproposal.call_optintoken(algod, addr, privkey, token.asset_id)
    return deployedproposal


def create_preapprovalgate(algod, deployedcommittee, addr, privkey) -> PreapprovalGate.DeployedGate:
    creategate = PreapprovalGate.CreateGate(deployedcommittee.appid, 1)
    gate = PreapprovalGate.deploy(algod, creategate, privkey)
    algodao.helpers.optinapp(algod, privkey, addr, gate.appid)
    gate_addr = algosdk.logic.get_application_address(gate.appid)
    tests.helpers.fund_account(algod, gate_addr)
    gate.call_inittoken(
        algod,
        addr,
        privkey,
        100,
        "Trusted",
        "TRUST",
        'http://localhost/abcd'
    )
    return gate

def create_trustcommittee(algod, addr, privkey) -> Committee.DeployedCommittee:
    committee = Committee.CreateCommittee("Trusted", 5)
    deployedcommittee = Committee.deploy(algod, committee, privkey)
    committee_addr = algosdk.logic.get_application_address(deployedcommittee.appid)
    tests.helpers.fund_account(algod, committee_addr)
    deployedcommittee.call_inittoken(algod, privkey, addr)
    algodao.helpers.optinasset(algod, addr, privkey, deployedcommittee.assetid)
    deployedcommittee.call_setmembers(algod, privkey, addr, [addr])
    return deployedcommittee

