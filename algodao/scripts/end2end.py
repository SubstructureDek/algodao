"""
End-to-end example of creating a DAO, submitting a PAYMENT proposal,
successfully passing the proposal, and then implementing it using the
on-chain logic.
"""
import algosdk.logic

import algodao.assets
import algodao.helpers
import tests.helpers
from algodao.committee import Committee
from algodao.governance import PreapprovalGate, AlgoDao
from algodao.voting import ProposalType, VoteType, ElectionToken, Proposal

algodao.helpers.loggingconfig()

# set up the creator's account
algod = algodao.helpers.createclient()
creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)

# create the trust committee
committee = Committee.CreateCommittee("Trusted", 5)
deployedcommittee = Committee.deploy(algod, committee, creatorprivkey)
committee_addr = algosdk.logic.get_application_address(deployedcommittee.appid)
# the committee needs some funding in order to initialize a new token (the
# committee token, which indicates membership)
tests.helpers.fund_account(algod, committee_addr)
deployedcommittee.call_inittoken(algod, creatorprivkey, creatoraddr)
algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, deployedcommittee.assetid)
# for simplicity in this example, the creator of the DAO is the only member
# of the trust committee
deployedcommittee.call_setmembers(algod, creatorprivkey, creatoraddr, [creatoraddr])

# create the governance token
gov_count = 1000000
gov_asset_id = algodao.assets.createasset(
    algod,
    creatoraddr,
    creatorprivkey,
    algodao.assets.createmetadata(
        "My Governance Token",
        "Governance token for My DAO",
        {},
        "",
    ),
    gov_count,
    "DAOGOV",
    "MyDAO Governance",
    "https://localhost/MyDAO/tokens/governance",
)

# create the preapproval gate with a single member
creategate = PreapprovalGate.CreateGate(deployedcommittee.appid, 1)
gate = PreapprovalGate.deploy(algod, creategate, creatorprivkey)
algodao.helpers.optinapp(algod, creatorprivkey, creatoraddr, gate.appid)
gate_addr = algosdk.logic.get_application_address(gate.appid)
# the preapproval gate also needs funding to create its token (the trust token)
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

# create the DAO
dao = AlgoDao.CreateDao("My DAO", gate.trust_assetid)
deployeddao = AlgoDao.deploy(algod, dao, creatorprivkey)
# add a rule specifying that PAYMENT proposals must be passed by a governance
# vote, with a 60% approval in order to pass (no minimum vote count or quorum
# requirements are currently implemented)
deployeddao.call_addrule(
    algod,
    creatoraddr,
    creatorprivkey,
    ProposalType.PAYMENT,
    VoteType.GOVERNANCE_TOKEN,
    60
)
# fund the DAO treasury
tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployeddao.appid))
# finalize the DAO - at this point no further updates are allowed by the
# creator; all further updates must be approved by the governance rules through
# a Proposal (not yet implemented)
deployeddao.call_finalize(algod, creatoraddr, creatorprivkey)

# create the election token. the election token is distributed to governance
# token holders according to the governance2votes lambda (here we simply define
# a 1-to-1 mapping) and are deposited into the Proposal contract to
# represent votes.
lastround = algod.status()['last-round']
voting_rounds = 40
waitforround = lastround + voting_rounds + 1
beginreg = lastround
endreg = lastround + voting_rounds
indexer = algodao.helpers.indexer_client()
election = algodao.voting.Election(
    indexer,
    algodao.voting.GovernanceToken(gov_asset_id),
    None,
    lambda govvotes: govvotes,  # provide 1 election token per gov token
    beginreg,
    endreg,
)
# build the Merkle tree to distribute election tokens to governance token
# holders in accordance with a current snapshot of holding amounts
createtree = election.builddistribution()
appid = createtree.deploy(algod, creatorprivkey)
deployedtree = algodao.assets.TokenDistributionTree.DeployedTree(
    appid, createtree.addr2count, createtree.merkletree
)
# the distribution tree contract requires funds to initialize the election
# token
tests.helpers.fund_account(algod, algosdk.logic.get_application_address(appid))
election_assetid = deployedtree.call_inittoken(
    algod,
    creatoraddr,
    creatorprivkey,
    gov_count,
    "ELEC",
    "MyDao Election Token",
    "https://localhost/MyDao/tokens/election"
)

# opt into the election token and claim our share
algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, election_assetid)
deployedtree.call_claim(algod, creatoraddr, creatorprivkey)
electiontoken = ElectionToken(election_assetid)

# create the proposal (pay 10,000 microalgo to receiveraddr)
receiverprivkey, receiveraddr = tests.helpers.create_funded(algod)
amount = 10000
proposal = Proposal.CreateProposal(
    "Test Proposal",
    electiontoken,
    lastround,
    lastround + voting_rounds,
    lastround,
    lastround + voting_rounds,
    2,  # number of options; must be 2 for an up/down vote
    deployeddao.appid,
    ProposalType.PAYMENT,
)
proposal.setpaymentinfo(receiveraddr, 10000)
proposal.setvotedata(VoteType.GOVERNANCE_TOKEN, 60)
deployedproposal = Proposal.deploy(algod, proposal, creatorprivkey)
# the Proposal contract requires funds to opt into the trust token and the
# election token
tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployedproposal.appid))
deployedproposal.call_optintoken(algod, creatoraddr, creatorprivkey, gate.trust_assetid)
deployedproposal.call_optintoken(algod, creatoraddr, creatorprivkey, electiontoken.asset_id)

# have the preapproval committee assess and preapprove the proposal
gate.call_assessproposal(algod, creatoraddr, creatorprivkey, deployedproposal.appid)
gate.call_vote(algod, creatoraddr, creatorprivkey, deployedproposal.appid, 1)

# vote on the proposal
algodao.helpers.optinapp(algod, creatorprivkey, creatoraddr, deployedproposal.appid)
deployedproposal.call_vote(
    algod,
    creatoraddr,
    creatorprivkey,
    1,  # vote option 1 = Yes, 2 = No
    10  # 10 votes
)

# wait for the voting period to end
algodao.helpers.wait_for_round(algod, waitforround)
# finalize the vote (assesses whether the vote passed or not)
deployedproposal.call_finalizevote(algod, creatoraddr, creatorprivkey)

# implement the (now passed) proposal from the DAO-side. the DAO contract will
# verify that the election has ended and that the proposal has passed in
# accordance with the requirements for this proposal type set by the DAO (i.e.,
# that it was a governance vote with over 60% voting Yes)
before = algod.account_info(receiveraddr)
deployeddao.call_implementproposal(
    algod,
    deployedproposal,
    creatoraddr,
    creatorprivkey,
    accounts=[receiveraddr],
)
after = algod.account_info(receiveraddr)
print(f"Before implementing proposal, receiver account: {before}")
print(f"After implementing proposal, receiver amount: {after}")
