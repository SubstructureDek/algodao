# AlgoDao
> The Algorand-based Decentralized Autonomous Organization (*DAO*) builder.
### This repository is for informational purposes only and has not been audited for security.

AlgoDao allows you to spin up a (truly) decentralized (truly) autonomous
organization in minutes using a set of smart contract templates that will
determine the (initial) governance rules of your new organization.

AlgoDao is built on the [Algorand ecosystem](https://www.algorand.com/), using
[PyTeal](https://pyteal.readthedocs.io/en/stable/) to create 
[smart contracts](https://developer.algorand.org/docs/get-details/dapps/smart-contracts/apps/)
and [Algorand Standard Assets (ASA)](https://developer.algorand.org/docs/get-details/asa/)
that govern the activities of your [DAO](https://en.wikipedia.org/wiki/Decentralized_autonomous_organization).

## Setup

To use the code in this repository, run `pip install -r requirements.txt` and,
for development work, `pip install -r requirements-dev.txt`. All tests are
written against the Algorand sandbox running in release mode. Make sure the
sandbox is running (`./sandbox start release`) and then set the `SANDBOX_DIR`
environment variable either directly (`export SANDBOX_DIR=/path/to/sandbox`)
or by adding it to a `.env` file in the current directly.

To run the full end to end example, run `python -m algodao.scripts.end2end`.

## Features

### Trustless Treasury

Unlike with many DAOs, the AlgoDao treasury is not controlled by any single
key or multisig. Instead, the treasury is fully owned by the main `AlgoDao`
smart contract, and funds can only be disbursed through approved `Proposals`
that meet the specifications defined in the governance structure of the DAO.
Once the original DAO specification is finalized and its governance token is
disbursed, the DAO creator is just like any other member of the DAO in
accordance with their token ownership and committee membership.

The DAO governance specifications are fully customizable and - if the governance
structure allows it - can also be themselves updated through an approved `Proposal`.

### Smart-Contract Governance

The governance rules of the AlgoDoa are fully embedded and enforced in the
smart contract implementation. There is no external reliance on any off-chain
resources or assumptions - the rules to create committees, add members,
determine voting thresholds, pay out funds, etc., and defined within the smart
contracts themselves, and expert users can interface directly with the smart
contract interfaces for all DAO-related activities.

### Custom Committee Assignments

Pure governance-token based elections frequently suffer from low participation.
In order to ensure well-informed decision making on issues critical to the DAO,
AlgoDao supports the creation and delegation of responsibilities to custom
committees. The purpose of these committees is up to the organization itself,
and members can be elected or ejected either by governance token votes or by
votes from another committee (again, according to the governance rules defined
by the DAO). 

## Technical Specifications

### AlgoDao and the Preapproval Gate
The initial structure created by AlgoDao consists of two smart contracts - the
`AlgoDao` and the `PreapprovalGate`. 

The `AlgoDao` contract defines the top-level structure of the DAO and includes
(in the smart contract) the rules by which `Proposals` may be accepted and
implemented. These proposals can be used to create new committes; disburse 
funds from the DAO; add or eject members from committees; or close out the DAO
and disburse the treasury to its constituents. The `AlgoDao` smart contract is
created by the `AlgoDao.CreateDao` class in 
[algodao/governance.py](algodao/governance.py) and, once on-chain, represented
by the `AlgoDao.DeployedDao` class in
[algodao/governance.py](algodao/governance.py).

The `PreapprovalGate` defines the method by which `Proposals` are allowed to be
considered by the DAO. Since there is no way to determine on-chain whether a
given smart contract is in fact a deployment of a specific TEAL contract, and 
because anyone is allowed to create `Proposals` to be considered by the DAO, the
`PreapprovalGate` process is needed to ensure that new `Proposals` are in fact
valid before they get voted on. The `PreapprovalGate` process is governed by a
special-case `Committee` called the "Trust Committee", which is populated and
governed using the usual `Committee` rules. The `PreapprovalGate` is currently
hard-coded to require a majority vote of the committee members to move a
`Proposal` forward before it can be voted on as usual.

Without the `PreapprovalGate` process, an attacker could, for example, write
their own smart contract that mimiced the standard `Proposal` but claimed it
had already been voted on and approved and immediately be used to disburse funds
to the attacker's account.

One hypothetical use case for the "Trust Committee" would be to have it
consist of only one automated member, which would run off-chain and preapprove
any `Proposals` that have a TEAL hash that matches known, approved versions of
the contract. This would ensure the DAO is allowed to vote on all valid
`Proposals`. With human committee members, the Trust Committee might also decide
to reject certain valid `Proposals` that they disapprove of; depending on the
governance structure of the DAO and the Trust Committee, this could be either
beneficial or unwanted.

### Trust Token

A special "Trust" ASA token is created during the creation of the
`PreapprovalGate` contract. This token is used by the `PreapprovalGate` to
indicate that a particular `Proposal` or `Committee` contract has passed a
vote by the Trust Committee. These tokens are non-transferable and can be
clawed back by the `PreapprovalGate` contract.

### Committees

Committees are tracked using a custom ASA token per committee. Committee tokens
are non-transferable - they are frozen to their members' accounts and can only
be transferred back to the Committee contract via resignation or via clawback
(if the committee member is ejected).

### Election Tokens

Two forms of voting are supported - via committee, or via the governance token.
Which approach is allowed for a given contract (and the percentage approval
required) depends on the governance rules.

Committee votes are relatively straightforward - since committee tokens are
non-transferable, there is little concern about double-voting. For governance
token votes, votes are proportional to the number of governance tokens owned
by a given user. In order to prevent double voting, a snapshot is taken 
off-chain and used to create a Merkle tree that defines the distribution of a
new "election token". The Merkle tree must be made accessible off-chain in order
for a user to claim their election tokens; election tokens are then deposited 
back into the `Proposal` contract to indicate a vote. The off-chain Merkle tree
logic is encoded in the `MerkleTree` class in [algodao/merkle.py](algodao/merkle.py);
the on-chain distribution logic is in the `TokenDistributionTree` class in
[algodao/assets.py](algodao/assets.py). 

The `Proposal` contract allows an arbitrary ASA to be selected as the Election
token as part of its construction. This allows for more flexibility in 
supporting some forms of quadratic voting - if a single election token is shared
among many proposals, the user might decide to spend more of their tokens on a
proposal they care more about, or save them all for a future election. This
logic around election tokens is *not* currently enforced by the `AlgoDao`
governance - it is up to the Trust Committee to ensure a `Proposal` follows the
appropriate election token logic for the DAO, and to create the corresponding
`TokenDistributionTree` contract if appropriate.

## To Be Implemented

Not all of the logic described in this README is currently implemented. In
particular the following gaps currently exist:

* Committee voting is only supported for the special-case Trust Committee in its
  votes to preapprove `Proposals`. Generalized committee voting is not yet
  supported by general `Proposals`.
* The only `Proposal` type currently supported is the `PAYMENT` type (to 
  disburse a specified amount to a specific address). Votes on adding and
  removing committee members; creation of new committees; the closing of 
  the DAO and subsequent disbursal of funds; and the modification of the DAO 
  governance rules are not yet implemented.
* Quorum rules and vote delegation are not yet implemented.
* Keep meaning to pull in the standard "best practices" contract checks
  [as defined here](https://github.com/algorand/pyteal-utils/blob/main/pytealutils/transaction/transaction.py)
  but keep getting distracted by other items; will remove this bullet when I
  get around to it.
* Proposal rules are currently only checked and enforced when the DAO attempts
  to implement a passed proposal. They should also be checked and enforced when
  creating the proposal.

## Future Work

I wanted this project to focus on enforcing on-chain rules and therefore have
not put the effort into creating a Web-based front-end to it, which could obscure
how much is done by the on-chain logic vs. the webapp. Certainly a front-end
webapp would be necessary to use this project in earnest. The 
`feature/webservice` branch contains a very simple proof of concept of how the
contracts could be built on the backend via a gunicorn web service and then
sent to the end-user as a JSON object, which they could then deploy to
the network using MyAlgoWallet. This proof of concept has been tested with a
trivial webapp (not provided here).

Due to the fully on-chain logic and smart-contract governed treasury used by
AlgoDao, you would certainly want to ensure the contracts here are air-tight
and failsafe before using it with any seriousness, which would require further
auditing. As mentioned at the top of this README, **this project has not been
audited for security and is for informational purposes only**.

## End-to-end Example

The beginning of a CLI is implemented on the `feature/cli` branch; this turned
out to be much more repetitive work handling all of the possible command line
argument variations than anticipated so it is unfinished. In the meantime there
is a full example of deploying a DAO, initializing an election token, creating
and voting on a proposal, and then implementing the proposal in 
[algodao/scripts/end2end.py](algodao/scripts/end2end.py). This code snippet
is essentially a combination of the `test_daoproposal` test in
[tests/test_governance.py](tests/test_governance.py) and the
`test_distributiontree` test in [tests/test_assets.py](tests/test_assets.py).

