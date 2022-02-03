import base64

import flask
import pyteal
from algosdk.v2client.algod import AlgodClient

import algodao.deploy
import algodao.voting
import algodao.helpers

app = flask.Flask(__name__)


@app.route("/contracts/proposal")
def create_proposal():
    proposal = algodao.voting.Proposal(
        "My Proposal Name",
        algodao.voting.ElectionToken(123),
        1000,
        2000,
        1000,
        2000,
        3
    )
    localschema = proposal.localschema()
    globalschema = proposal.globalschema()
    approval_teal = pyteal.compileTeal(
        proposal.approval_program(),
        mode=pyteal.Mode.Application,
        version=5
    )
    clear_teal = pyteal.compileTeal(
        proposal.clear_program(),
        mode=pyteal.Mode.Application,
        version=5
    )
    algod: AlgodClient = algodao.helpers.createclient()
    approval_program = algodao.deploy.compile_program(algod, approval_teal)
    clear_program = algodao.deploy.compile_program(algod, clear_teal)
    appargs = [
        base64.b64encode(algodao.helpers.int2bytes(number)).decode()
        for number in (1000, 2000, 1000, 2000,)
    ]
    return {
        'numLocalByteSlices': localschema.num_byte_slices,
        'numLocalInts': localschema.num_uints,
        'numGlobalBytesSlices': globalschema.num_byte_slices,
        'numGlobalInts': globalschema.num_uints,
        'approvalProgram': base64.b64encode(approval_program).decode(),
        'clearProgram': base64.b64encode(clear_program).decode(),
        'appArgs': appargs,
    }


@app.after_request
def after_request(response):
    header = response.headers
    header['Access-Control-Allow-Origin'] = '*'
    return response
