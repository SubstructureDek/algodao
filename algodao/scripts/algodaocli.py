import argparse

import algodao.voting


def main():
    parser = create_parser()
    args = parser.parse_args()

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Launch a DAO on Algorand')
    subparsers = parser.add_subparsers(title='commands', description='algodao CLI commands')
    dao = subparsers.add_parser("dao", help='DAO creation commands')
    daosubs = dao.add_subparsers(title='subcommands', description='DAO commands')
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
    preapproval = subparsers.add_parser('preapproval', help='preapproval committee commands')
    preapprovalsubs = preapproval.add_subparsers(
        title='subcommands',
        description='preapproval committee commands',
        dest='preapproval',
    )
    createpreapproval = preapprovalsubs.add_parser('create', help='create the preapproval committee')
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
    preapprovalsubs.add_parser(
        'inittoken',
        description='initialize the trust token',

    )

    return parser

if __name__ == '__main__':
    main()
