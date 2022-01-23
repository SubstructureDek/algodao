from typing import TypedDict


PendingTransactionInfo = TypedDict(
    'PendingTransactionInfo',
    {
        'asset-index': int,
    }
)


AccountInfo = TypedDict(
    'AccountInfo',
    {
        'amount': int,
    }
)
