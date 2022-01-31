# based off https://github.com/algorand/docs/blob/cdf11d48a4b1168752e6ccaf77c8b9e8e599713a/examples/smart_contracts/v2/python/stateful_smart_contracts.py
import base64
import logging

from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from algosdk import account, mnemonic

import algodao.helpers
from algodao.types import PendingTransactionInfo

log = logging.getLogger(__name__)


# helper function to compile program source
def compile_program(client, source_code) -> bytes:
    log.info("Compiling program")
    compile_response = client.compile(source_code)
    log.info(f"Compiler response: {compile_response}")
    return base64.b64decode(compile_response["result"])


# helper function that converts a mnemonic passphrase into a private signing key
def get_private_key_from_mnemonic(mn):
    private_key = mnemonic.to_private_key(mn)
    return private_key


def wait_for_round(algod: AlgodClient, algoround: int):
    last_round = algod.status().get("last-round")
    print(f"Waiting for round {algoround}")
    while last_round < algoround:
        last_round += 1
        algod.status_after_block(last_round)
        print(f"Round {last_round}")


def create_app(
    client: AlgodClient,
    private_key: str,
    approval_program,
    clear_program,
    global_schema,
    local_schema,
    app_args,
) -> int:
    sender = account.address_from_private_key(private_key)
    on_complete = transaction.OnComplete.NoOpOC.real
    params = client.suggested_params()
    txn = transaction.ApplicationCreateTxn(
        sender,
        params,
        on_complete,
        approval_program,
        clear_program,
        global_schema,
        local_schema,
        app_args,
    )
    signed_txn = txn.sign(private_key)
    tx_id = signed_txn.transaction.get_txid()
    client.send_transactions([signed_txn])
    algodao.helpers.wait_for_confirmation(client, tx_id)
    response: PendingTransactionInfo = client.pending_transaction_info(tx_id)
    app_id = response["application-index"]
    log.info(f"Created new app-id {app_id}: {response}")
    return app_id


def format_state(state):
    formatted = {}
    for item in state:
        key = item["key"]
        value = item["value"]
        formatted_key = base64.b64decode(key).decode("utf-8")
        if value["type"] == 1:
            # byte string
            if formatted_key == "voted":
                formatted_value = base64.b64decode(value["bytes"]).decode("utf-8")
            else:
                formatted_value = value["bytes"]
            formatted[formatted_key] = formatted_value
        else:
            # integer
            formatted[formatted_key] = value["uint"]
    return formatted


# read user local state
def read_local_state(client, addr, app_id):
    results = client.account_info(addr)
    for local_state in results["apps-local-state"]:
        if local_state["id"] == app_id:
            if "key-value" not in local_state:
                return {}
            return format_state(local_state["key-value"])
    return {}


# read app global state
def read_global_state(client, addr, app_id):
    results = client.account_info(addr)
    apps_created = results["created-apps"]
    for app in apps_created:
        if app["id"] == app_id:
            return format_state(app["params"]["global-state"])
    return {}
