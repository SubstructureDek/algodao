import abc
from typing import List

import algosdk.error
import pyteal
from algosdk.future import transaction
from algosdk.v2client.algod import AlgodClient
from pyteal import Expr, Mode

import algodao.deploy
import algodao.helpers


class CreateContract(abc.ABC):
    @abc.abstractmethod
    def approval_program(self) -> Expr:
        """Returns the approval program"""
        pass

    @abc.abstractmethod
    def clear_program(self) -> Expr:
        """Return the clear program"""
        pass

    @abc.abstractmethod
    def local_schema(self) -> transaction.StateSchema:
        """Return the local schema"""
        pass

    @abc.abstractmethod
    def global_schema(self) -> transaction.StateSchema:
        """Return the global schema"""
        pass

    @abc.abstractmethod
    def createapp_args(self) -> List[bytes]:
        """Return the arguments to pass to create the contract"""
        pass

    def deploy(self, algod: AlgodClient, privkey: str) -> int:
        """
        Deploys the program and returns the app ID
        """
        approval_teal = pyteal.compileTeal(self.approval_program(), Mode.Application, version=5)
        approval_compiled = algodao.deploy.compile_program(algod, approval_teal)
        clear_teal = pyteal.compileTeal(self.clear_program(), Mode.Application, version=5)
        clear_compiled = algodao.deploy.compile_program(algod, clear_teal)
        appid = algodao.deploy.create_app(
            algod,
            privkey,
            approval_compiled,
            clear_compiled,
            self.global_schema(),
            self.local_schema(),
            self.createapp_args()
        )
        return appid


class DeployedContract(abc.ABC):
    def __init__(self, appid):
        self._appid = appid

    @property
    def appid(self):
        return self._appid

    def call_method(
            self,
            algod: AlgodClient,
            addr: str,
            privkey: str,
            method: bytes,
            args: List[bytes],
            accounts=None,
            foreign_apps=None,
            foreign_assets=None,
    ):
        params = algod.suggested_params()
        txn = transaction.ApplicationNoOpTxn(
            addr,
            params,
            self._appid,
            [method, *args],
            accounts=accounts,
            foreign_apps=foreign_apps,
            foreign_assets=foreign_assets,
        )
        signed = txn.sign(privkey)
        try:
            txid = algod.send_transaction(signed)
            algodao.helpers.wait_for_confirmation(algod, txid)
        except algosdk.error.AlgodHTTPError as exc:
            algodao.helpers.writedryrun(algod, signed, 'failed_txn')
            raise
        return algod.pending_transaction_info(txid)
