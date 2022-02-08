import algodao.helpers
import tests.helpers
from algodao.committee import Committee
import algosdk.logic
from algodao.governance import PreapprovalGate, AlgoDao
from algodao.voting import ProposalType, VoteType, ElectionToken, Proposal
import algodao.assets

algodao.helpers.loggingconfig()

# set up the creator's account
algod = algodao.helpers.createclient()
creatorprivkey, creatoraddr = tests.helpers.create_funded(algod)

# create the trust committee
committee = Committee.CreateCommittee("Trusted", 5)
deployedcommittee = Committee.deploy(algod, committee, creatorprivkey)
committee_addr = algosdk.logic.get_application_address(deployedcommittee.appid)
tests.helpers.fund_account(algod, committee_addr)
deployedcommittee.call_inittoken(algod, creatorprivkey, creatoraddr)
algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, deployedcommittee.assetid)
deployedcommittee.call_setmembers(algod, creatorprivkey, creatoraddr, [creatoraddr])

# create the governance token
gov_count = 100000
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
deployeddao.call_addrule(
    algod,
    creatoraddr,
    creatorprivkey,
    ProposalType.PAYMENT,
    VoteType.GOVERNANCE_TOKEN,
    60
)
deployeddao.call_finalize(algod, creatoraddr, creatorprivkey)

# create the election token
lastround = algod.status()['last-round']
voting_rounds = 40
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
# build the Merkle tree to distribute election tokens
createtree = election.builddistribution()
appid = createtree.deploy(algod, creatorprivkey)
deployedtree = algodao.assets.TokenDistributionTree.DeployedTree(
    appid, createtree.addr2count, createtree.merkletree
)
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
algodao.helpers.optinasset(algod, creatoraddr, creatorprivkey, election_assetid)

# claim our share of election tokens
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
    2,
    deployeddao.appid,
    ProposalType.PAYMENT,
)
proposal.setpaymentinfo(receiveraddr, 10000)
proposal.setvotedata(VoteType.GOVERNANCE_TOKEN, 60)
deployedproposal = Proposal.deploy(algod, proposal, creatorprivkey)
tests.helpers.fund_account(algod, algosdk.logic.get_application_address(deployedproposal.appid))
deployedproposal.call_optintoken(algod, creatoraddr, creatorprivkey, gate._trust_asset_id)
deployedproposal.call_optintoken(algod, creatoraddr, creatorprivkey, electiontoken.asset_id)
waitforoundround = algod.status()['last-round'] + voting_rounds + 1

# have the preapproval committee assess and preapprove the proposal
gate.call_assessproposal(algod, creatoraddr, creatorprivkey, deployedproposal.appid)
gate.call_vote(algod, creatoraddr, creatorprivkey, deployedproposal.appid, 1)

# vote on the proposal
algodao.helpers.optinapp(algod, creatorprivkey, creatoraddr, deployedproposal.appid)
deployedproposal.call_vote(algod, creatoraddr, creatorprivkey, 1, 10)
algodao.helpers.wait_for_round(algod, waitforoundround)
deployedproposal.call_finalizevote(algod, creatoraddr, creatorprivkey)
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
