import logging

import algodao.helpers
import tests.helpers
from algodao.types import AccountInfo

log = logging.getLogger(__name__)


def test_createaccount():
    amount = 100000
    client = algodao.helpers.createclient()
    privkey, addr = tests.helpers.add_standalone_account()
    tests.helpers.fund_account(addr, amount)
    info: AccountInfo = client.account_info(addr)
    log.info(info)
    assert info['amount'] == amount
