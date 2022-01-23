# see https://github.com/ipaleka/algorand-contracts-testing
import os
import pathlib
import pty
import subprocess

import algosdk.account
import algosdk.future.transaction
import algosdk.mnemonic

import algodao.helpers


def _cli_passphrase_for_account(address):
    """Return passphrase for provided address."""
    process = call_sandbox_command("goal", "account", "export", "-a", address)

    if process.stderr:
        raise RuntimeError(process.stderr.decode("utf8"))

    passphrase = ""
    parts = process.stdout.decode("utf8").split('"')
    if len(parts) > 1:
        passphrase = parts[1]
    if passphrase == "":
        raise ValueError(
            "Can't retrieve passphrase from the address: %s\nOutput: %s"
            % (address, process.stdout.decode("utf8"))
        )
    return passphrase


def call_sandbox_command(*args):
    """Call and return sandbox command composed from provided arguments."""
    return subprocess.run(
        [_sandbox_executable(), *args],
        stdin=pty.openpty()[1],
        capture_output=True
    )


def _sandbox_executable():
    """Return full path to Algorand's sandbox executable."""
    return _sandbox_directory() + "/sandbox"


def _sandbox_directory():
    """Return full path to Algorand's sandbox executable.

    The location of sandbox directory is retrieved either from the SANDBOX_DIR
    environment variable or if it's not set then the location of sandbox directory
    is implied to be the sibling of this Django project in the directory tree.
    """
    return os.environ.get("SANDBOX_DIR") or str(
        pathlib.Path(__file__).resolve().parent.parent / "sandbox"
    )


def _initial_funds_address():
    """Get the address of initially created account having enough funds.

    Such an account is used to transfer initial funds for the accounts
    created in this tutorial.
    """
    indexer = algodao.helpers.indexer_client()
    return next(
        (
            account.get("address")
            for account in indexer.accounts().get("accounts", [{}, {}])
            if account.get("created-at-round") == 0
            and account.get("status") == "Offline"  # "Online" for devMode
        ),
        None,
    )


def add_standalone_account():
    """Create standalone account"""
    private_key, address = algosdk.account.generate_account()
    return private_key, address


def fund_account(address, initial_funds=1000000000):
    """Fund provided `address` with `initial_funds` amount of microAlgos."""
    initial_funds_address = _initial_funds_address()
    if initial_funds_address is None:
        raise Exception("Initial funds weren't transferred!")
    _add_transaction(
        initial_funds_address,
        address,
        _cli_passphrase_for_account(initial_funds_address),
        initial_funds,
        "Initial funds",
    )


def _add_transaction(sender, receiver, passphrase, amount, note):
    """Create and sign transaction from provided arguments.

    Returned non-empty tuple carries field where error was raised and description.
    If the first item is None then the error is non-field/integration error.
    Returned two-tuple of empty strings marks successful transaction.
    """
    client = algodao.helpers.createclient()
    params = client.suggested_params()
    unsigned_txn = algosdk.future.transaction.PaymentTxn(
        sender,
        params,
        receiver,
        amount,
        None,
        note.encode()
    )
    signed_txn = unsigned_txn.sign(algosdk.mnemonic.to_private_key(passphrase))
    transaction_id = client.send_transaction(signed_txn)
    algodao.helpers.wait_for_confirmation(client, transaction_id)
    return transaction_id
