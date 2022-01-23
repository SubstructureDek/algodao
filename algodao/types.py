from typing import TypedDict, List


PendingTransactionInfo = TypedDict(
    'PendingTransactionInfo',
    {
        'asset-index': int,
    }
)


AssetInfo = TypedDict(
    'AssetInfo',
    {
        'amount': int,
        'asset-id': int,
        'creator': str,
        'is-frozen': bool,
    }
)

AccountInfo = TypedDict(
    'AccountInfo',
    {
        'amount': int,
        'assets': List[AssetInfo]
    }
)
