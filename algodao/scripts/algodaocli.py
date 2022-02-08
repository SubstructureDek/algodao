import argparse
import os

import algodao.voting
import algodao.governance
import algodao.helpers


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Launch a DAO on Algorand')
    subparsers = parser.add_subparsers(
        title='commands',
        description='algodao CLI commands',
        dest='cmd',
    )

    # DAO COMMANDS #
    dao = subparsers.add_parser("dao", help='DAO creation commands')
    daosubs = dao.add_subparsers(
        title='subcommands',
        description='DAO commands',
        dest='subcmd'
    )
    createdao = daosubs.add_parser('create', help='create a new DAO')
    createdao.add_argument(
        '--name',
        help='name of the DAO',
        required=True,
        action='store',
        type=str,
    )
    createdao.add_argument(
        '--trust-id',
        help='asset ID of the trust ASA',
        action='store',
        type=int,
        required=True,
    )
    addrule = daosubs.add_parser("addrule", help='add a rule to a DAO being provisioned')
    addrule.add_argument(
        '--dao-id',
        help='the app ID of the DAO smart contract',
        type=int,
        action='store',
        required=True,
    )
    addrule.add_argument(
        '--proposal-type',
        help='the type of proposal this rule will apply to',
        action='store',
        type=str,
        choices=[choice.name for choice in algodao.voting.ProposalType],
        required=True,
    )
    addrule.add_argument(
        '--vote-type',
        help='the type of vote to require for the specified proposal type',
        action='store',
        type=str,
        choices=[choice.name for choice in algodao.voting.VoteType],
        required=True,
    )
    addrule.add_argument(
        '--approval-pct',
        help='the minimum percentage of votes necessary to approve the specified type of proposal',
        action='store',
        type=int,
        required=True,
    )
    finalize = daosubs.add_parser('finalize', help='finalize the DAO governance')
    finalize.add_argument(
        '--dao-id',
        help='app ID of the DAO smart contract',
        action='store',
        type=int,
        required=True,
    )

    # PREAPPROVAL COMMANDS #
    preapproval = subparsers.add_parser(
        'preapproval',
        help='preapproval committee commands'
    )
    preapprovalsubs = preapproval.add_subparsers(
        title='subcommands',
        description='preapproval committee commands',
        dest='subcmd',
    )
    createpreapproval = preapprovalsubs.add_parser(
        'create',
        help='create the preapproval committee'
    )
    createpreapproval.add_argument(
        '--committee-id',
        help='the application ID of the preapproval committee',
        action='store',
        type=int,
        required=True,
    )
    createpreapproval.add_argument(
        '--min-vote-rounds',
        help='minimum number of rounds to consider a proposal before allowing another proposal to be considered',
        action='store',
        type=int,
        required=True,
    )
    inittoken = preapprovalsubs.add_parser(
        'inittoken',
        help='initialize the trust token',
    )
    inittoken.add_argument(
        '--committee-id',
        help='app ID of the preapproval committee smart contract',
        action='store',
        type=int,
        required=True,
    )
    inittoken.add_argument(
        '--asset-total',
        help='total number of trust assets to create',
        action='store',
        type=int,
        required=True,
    )
    inittoken.add_argument(
        '--asset-unit-name',
        help='trust asset unit name',
        action='store',
        type=str,
        required=True,
    )
    inittoken.add_argument(
        '--asset-name',
        help='trust asset name',
        action='store',
        type=str,
        required=True,
    )
    inittoken.add_argument(
        '--asset-url',
        help='trust asset url',
        action='store',
        type=str,
        required=True
    )
    assess = preapprovalsubs.add_parser(
        'assesstoken',
        help='submit a proposal for assessment (must be a trust committee member)'
    )
    assess.add_argument(
        '--committee-id',
        help='app ID of the preapproval committee smart contract',
        action='store',
        type=int,
        required=True,
    )
    assess.add_argument(
        '--considered-appid',
        help='the app ID of the proposal to consider',
        action='store',
        type=str,
        required=True
    )
    vote = preapprovalsubs.add_parser(
        'vote',
        help='submit a vote on the current proposal under consideration (must be a trust committee member)',
    )
    vote.add_argument(
        '--committee-id',
        help='app ID of the preapproval committee smart contract',
        action='store',
        type=int,
        required=True,
    )
    vote.add_argument(
        '--considered-appid',
        help='the app ID of the proposal under consideration (must match the proposal currently under consideration)',
        action='store',
        type=str,
        required=True
    )
    vote.add_argument(
        '--value',
        help='"yes" or "no" vote',
        action='store',
        type=str,
        choices=['yes', 'no'],
        required=True,
    )

    # COMMITTEE COMMANDS
    committee = subparsers.add_parser('committee', help='committee commands')
    committeesubs = committee.add_subparsers(
        title='subcommmands',
        help='committee commands',
        dest='subcmd',
    )
    create = committeesubs.add_parser('create', help='create a new committee')
    create.add_argument(
        '--name',
        help='committee name',
        type=str,
        action='store',
        required=True,
    )
    create.add_argument(
        '--max-members',
        help='max number of committee members',
        type=int,
        action='store',
        required=True,
    )
    inittoken = committeesubs.add_parser('inittoken', help='initialize the committee token')
    inittoken.add_argument(
        '--committee-id',
        help='app ID of the committee smart contract',
        type=int,
        action='store',
        required=True,
    )
    inittoken.add_argument(
        '--asset-unit-name',
        help='committee asset unit name',
        type=str,
        action='store',
        required=True,
    )
    inittoken.add_argument(
        '--asset-name',
        help='committee asset name',
        type=str,
        action='store',
        required=True,
    )
    inittoken.add_argument(
        '--asset-url',
        help='committee asset URL',
        type=str,
        action='store',
        required=True,
    )
    optintoken = committeesubs.add_parser('optintoken', help='opt into the specified token')
    optintoken.add_argument(
        '--committee-id',
        help='app ID of the committee smart contract',
        type=int,
        action='store',
        required=True,
    )
    optintoken.add_argument(
        '--asset-id',
        help='asset ID to opt into',
        type=int,
        action='store',
        required=True,
    )
    setmembers = committeesubs.add_parser('setmembers', help='set the committee members (only available during setup phase)')
    setmembers.add_argument(
        '--committee-id',
        help='app ID of the committee smart contract',
        type=int,
        action='store',
        required=True,
    )
    setmembers.add_argument(
        '--members',
        help='comma-separated list of members to add to the committee',
        type=str,
        action='store',
        required=True,
    )

    # PROPOSAL COMMANDS
    proposal = subparsers.add_parser("proposal", help='Proposal commands')
    propsubs = proposal.add_subparsers(
        title='subcommands',
        description='Proposal commands',
        dest='subcmd'
    )
    create = propsubs.add_parser('create', help='create a new proposal')
    create.add_argument(
        '--name',
        help='Proposal name',
        type=str,
        action='store',
        required=True,
    )
    create.add_argument(
        '--vote-asset-id',
        help='asset ID of the token being used to vote',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--registration-begin',
        help='round for which registration should begin',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--registration-end',
        help='round for which registration should end',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--vote-begin',
        help='round for which voting should begin',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--vote-end',
        help='round for which voting should end',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--num-options',
        help='number of vote options (currently must be 2 and will be Yes/No)',
        type=str,
        action='store',
        required=True,
    )
    create.add_argument(
        '--proposal-type',
        help='proposal type',
        type=str,
        action='store',
        required=True,
        choices=[choice.name for choice in algodao.voting.ProposalType],
    )
    create.add_argument(
        '--dao-id',
        help='app ID of the DAO smart contract',
        type=int,
        action='store',
        required=True,
    )
    create.add_argument(
        '--vote-type',
        help='vote type',
        type=str,
        action='store',
        required=True,
        choices=[choice.name for choice in algodao.voting.VoteType],
    )
    # okay definitely underestimated how much work it would take to
    # implement this CLI (-_-)
    optintoken = propsubs.add_parser('optintoken', help='opt into an ASA')
    optintoken.add_argument(
        '--proposal-id',
        help='app ID of the proposal smart contract',
        type=int,
        action='store',
        required=True,
    )
    optintoken.add_argument(
        '--asset-id',
        help='asset ID of the ASA to opt into',
        type=int,
        action='store',
        required=True,
    )
    setvotetoken = propsubs.add_parser('setvotetoken', help='set the election token')
    setvotetoken.add_argument(
        '--proposal-id',
        help='app ID of the proposal smart contract',
        type=int,
        action='store',
        required=True,
    )
    setvotetoken.add_argument(
        '--asset-id',
        help='asset ID of the ASA to use as the election token',
        type=int,
        action='store',
        required=True,
    )
    vote = propsubs.add_parser('vote', help='vote on a proposal')
    vote.add_argument(
        '--proposal-id',
        help='app ID of the proposal smart contract',
    )
    vote.add_argument(
        '--option',
        help='option to vote on',
        type=int,
        action='store',
        required=True,
    )
    vote.add_argument(
        '--count',
        help='number of election tokens to spend on the option (do not include decimals)',
        type=int,
        action='store',
        required=True,
    )
    finalizevote = propsubs.add_parser('finalizevote', help='finalize a vote that has ended')
    finalizevote.add_argument(
        '--proposal-id',
        help='app ID of the proposal smart contract',
        type=int,
        action='store',
        required=True,
    )
    election = subparsers.add_parser("election", help='election token commands')
    # ...
    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    algod = algodao.helpers.createclient()
    addr = os.getenv("ADDRESS")
    privkey = os.getenv("PRIVATE_KEY")
    if args.cmd == 'dao':
        if args.subcmd == 'create':
            create = algodao.governance.AlgoDao.CreateDao(
                args.name,
                args.trust_id
            )
            algodao.governance.AlgoDao.deploy(algod, create, privkey)
        elif args.subcmd == 'addrule':
            deployed = algodao.governance.AlgoDao.DeployedDao(algod, args.dao_id)
            deployed.call_addrule(
                algod,
                addr,
                privkey,
                algodao.voting.ProposalType[args.proposal_type],
                algodao.voting.VoteType[args.vote_type],
                args.approval_pct
            )
        elif args.subcmd == 'finalize':
            deployed = algodao.governance.AlgoDao.DeployedDao(algod, args.dao_id)
            deployed.call_finalize(algod, addr, privkey)
    elif args.cmd == 'preapproval':
        pass


if __name__ == '__main__':
    main()
