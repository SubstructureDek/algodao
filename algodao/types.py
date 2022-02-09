"""
This module defines a set of TypedDicts that represent the JSON returned by the
Algorand v2 API. This is not meant to be exhaustive and in many cases only
explicitly includes the fields that are currently being used by the algodao
repository.
"""
from __future__ import annotations

from typing import List, TypedDict, Any


PendingTransactionInfo = TypedDict(
    'PendingTransactionInfo',
    {
        'asset-index': int,
        'application-index': int,
        # mypy does not support cyclic references but the elements of this
        # list will also be PendingTransactionInfo type
        'inner-txns': List[Any]
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

