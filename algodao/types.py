from typing import List, TypedDict


PendingTransactionInfo = TypedDict(
    'PendingTransactionInfo',
    {
        'asset-index': int,
        'application-index': int,
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


AssetBalanceInfo = TypedDict(
    'AssetBalanceInfo',
    {
        'amount': int,
        'address': str,
    }
)

AssetBalances = TypedDict(
    'AssetBalances',
    {
        'balances': List[AssetBalanceInfo],
    }
)

ApplicationStateSchema = TypedDict(
    'ApplicationStateSchema',
    {
        'num-bytes-slice': int,
        'num-uint': int,
    }
)


TealValue = TypedDict(
    'TealValue',
    {
        'bytes': str,
        'type': int,
        'uint': int,
    }
)


class TealKeyValue(TypedDict):
    key: str
    value: TealValue


TealKeyValueStore = List[TealKeyValue]


ApplicationParams = TypedDict(
    'ApplicationParams',
    {
        'approval-program': str,
        'clear-state-program': str,
        'creator': str,
        'extra-program-pages': int,
        'global-state': TealKeyValueStore,
        'global-state-schema': ApplicationStateSchema,
        'local-state-schema': ApplicationStateSchema,
    }
)


ApplicationInfo = TypedDict(
    'ApplicationInfo',
    {
        'id': int,
        'params': ApplicationParams,
    }
)