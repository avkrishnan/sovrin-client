from plenum.common.keygen_utils import initLocalKeys
from plenum.test import waits as plenumWaits

from stp_core.loop.eventually import eventually
import warnings

from plenum.common.util import randomString
from plenum.test.helper import waitForSufficientRepliesForRequests
from plenum.test.node_catchup.helper import \
    ensureClientConnectedToNodesAndPoolLedgerSame
from plenum.test.test_node import checkNodesConnected
from sovrin_client.client.wallet.node import Node
from sovrin_common import strict_types
from stp_core.network.port_dispenser import genHa

# typecheck during tests
strict_types.defaultShouldCheck = True

import pytest
from copy import deepcopy

from stp_core.loop.looper import Looper
from plenum.common.signer_simple import SimpleSigner
from plenum.common.constants import VERKEY, NODE_IP, NODE_PORT, CLIENT_IP, CLIENT_PORT, \
    ALIAS, SERVICES, VALIDATOR, TYPE, STEWARD, TRUSTEE, TXN_ID
from plenum.test.plugin.helper import getPluginPath

from sovrin_client.client.wallet.wallet import Wallet
from sovrin_common.constants import NYM, TRUST_ANCHOR
from sovrin_common.constants import TXN_TYPE, TARGET_NYM, ROLE
from sovrin_common.txn_util import getTxnOrderedFields
from sovrin_common.config_util import getConfig
from sovrin_client.test.cli.helper import newCLI, addTrusteeTxnsToGenesis, addTxnToFile
from sovrin_node.test.helper import TestNode, \
    makePendingTxnsRequest, buildStewardClient
from sovrin_client.test.helper import addRole, getClientAddedWithRole, primes, \
    genTestClient, TestClient, createNym


# noinspection PyUnresolvedReferences
from plenum.test.conftest import tdir, nodeReg, up, ready, \
    whitelist, concerningLogLevels, logcapture, keySharedNodes, \
    startedNodes, tdirWithDomainTxns, txnPoolNodeSet, poolTxnData, dirName, \
    poolTxnNodeNames, allPluginsPath, tdirWithNodeKeepInited, tdirWithPoolTxns, \
    poolTxnStewardData, poolTxnStewardNames, getValueFromModule, \
    txnPoolNodesLooper, nodeAndClientInfoFilePath, conf, patchPluginManager, \
    warncheck, warnfilters as plenum_warnfilters, setResourceLimits


@pytest.fixture(scope="session")
def warnfilters(plenum_warnfilters):
    def _():
        plenum_warnfilters()
        warnings.filterwarnings('ignore', category=ResourceWarning, message='unclosed file')
    return _


@pytest.fixture(scope="module")
def primes1():
    P_PRIME1, Q_PRIME1 = primes.get("prime1")
    return dict(p_prime=P_PRIME1, q_prime=Q_PRIME1)


@pytest.fixture(scope="module")
def primes2():
    P_PRIME2, Q_PRIME2 = primes.get("prime2")
    return dict(p_prime=P_PRIME2, q_prime=Q_PRIME2)


@pytest.fixture(scope="module")
def tconf(conf, tdir):
    conf.baseDir = tdir
    conf.MinSepBetweenNodeUpgrades = 5
    return conf


@pytest.fixture(scope="module")
def updatedPoolTxnData(poolTxnData):
    data = deepcopy(poolTxnData)
    trusteeSeed = 'thisistrusteeseednotsteward12345'
    signer = SimpleSigner(seed=trusteeSeed.encode())
    t = {
        TARGET_NYM: signer.verkey,
        ROLE: TRUSTEE,
        TYPE: NYM,
        ALIAS: "Trustee1",
        TXN_ID: "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4a"
    }
    data["seeds"]["Trustee1"] = trusteeSeed
    data["txns"].insert(0, t)
    return data


@pytest.fixture(scope="module")
def poolTxnTrusteeNames():
    return "Trustee1",


@pytest.fixture(scope="module")
def trusteeData(poolTxnTrusteeNames, updatedPoolTxnData):
    ret = []
    for name in poolTxnTrusteeNames:
        seed = updatedPoolTxnData["seeds"][name]
        txn = next((txn for txn in updatedPoolTxnData["txns"] if txn[ALIAS] == name), None)
        ret.append((name, seed.encode(), txn))
    return ret


@pytest.fixture(scope="module")
def trusteeWallet(trusteeData):
    name, sigseed, txn = trusteeData[0]
    wallet = Wallet('trustee')
    signer = SimpleSigner(seed=sigseed)
    wallet.addIdentifier(signer=signer)
    return wallet


# TODO: This fixture is present in sovrin_node too, it should be
# sovrin_common's conftest.
@pytest.fixture(scope="module")
def trustee(nodeSet, looper, tdir, trusteeWallet):
    return buildStewardClient(looper, tdir, trusteeWallet)


@pytest.fixture(scope="module")
def allPluginsPath():
    return [getPluginPath('stats_consumer')]


@pytest.fixture(scope="module")
def stewardWallet(poolTxnStewardData):
    name, sigseed = poolTxnStewardData
    wallet = Wallet('steward')
    signer = SimpleSigner(seed=sigseed)
    wallet.addIdentifier(signer=signer)
    return wallet


@pytest.fixture(scope="module")
def looper():
    with Looper() as l:
        yield l


# TODO: This fixture is present in sovrin_node too, it should be
# sovrin_common's conftest.
@pytest.fixture(scope="module")
def steward(nodeSet, looper, tdir, stewardWallet):
    return buildStewardClient(looper, tdir, stewardWallet)


@pytest.fixture(scope="module")
def genesisTxns(stewardWallet: Wallet, trusteeWallet: Wallet):
    nym = stewardWallet.defaultId
    return [
        {
            TXN_TYPE: NYM,
            TARGET_NYM: nym,
            TXN_ID: "9c86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
            ROLE: STEWARD,
            VERKEY: stewardWallet.getVerkey()
        },
    ]


@pytest.fixture(scope="module")
def domainTxnOrderedFields():
    return getTxnOrderedFields()


@pytest.fixture(scope="module")
def conf(tdir):
    return getConfig(tdir)


@pytest.fixture(scope="module")
def testNodeClass():
    return TestNode


@pytest.fixture(scope="module")
def testClientClass():
    return TestClient


@pytest.fixture(scope="module")
def tdirWithDomainTxnsUpdated(tdirWithDomainTxns, poolTxnTrusteeNames, trusteeData, tconf):
    addTrusteeTxnsToGenesis(poolTxnTrusteeNames, trusteeData, tdirWithDomainTxns, tconf.domainTransactionsFile)
    return tdirWithDomainTxns


@pytest.fixture(scope="module")
def updatedDomainTxnFile(tdir, tdirWithDomainTxnsUpdated, genesisTxns,
                         domainTxnOrderedFields, tconf):
    addTxnToFile(tdir, tconf.domainTransactionsFile, genesisTxns, domainTxnOrderedFields)


@pytest.fixture(scope="module")
def nodeSet(tconf, updatedDomainTxnFile, txnPoolNodeSet):
    return txnPoolNodeSet


@pytest.fixture(scope="module")
def client1Signer():
    seed = b'client1Signer secret key........'
    signer = SimpleSigner(seed=seed)
    assert signer.verkey == '6JvpZp2haQgisbXEXE9NE6n3Tuv77MZb5HdF9jS5qY8m'
    return signer


@pytest.fixture("module")
def trustAnchorCli(looper, tdir):
    return newCLI(looper, tdir)


@pytest.fixture(scope="module")
def clientAndWallet1(client1Signer, looper, nodeSet, tdir, up):
    client, wallet = genTestClient(nodeSet, tmpdir=tdir, usePoolLedger=True)
    wallet = Wallet(client.name)
    wallet.addIdentifier(signer=client1Signer)
    return client, wallet


@pytest.fixture(scope="module")
def client1(clientAndWallet1, looper):
    client, wallet = clientAndWallet1
    looper.add(client)
    looper.run(client.ensureConnectedToNodes())
    return client


@pytest.fixture(scope="module")
def wallet1(clientAndWallet1):
    return clientAndWallet1[1]


@pytest.fixture(scope="module")
def trustAnchorWallet():
    wallet = Wallet('trustAnchor')
    seed = b'trust anchors are people too....'
    wallet.addIdentifier(seed=seed)
    return wallet


@pytest.fixture(scope="module")
def trustAnchor(nodeSet, addedTrustAnchor, trustAnchorWallet, looper, tdir):
    s, _ = genTestClient(nodeSet, tmpdir=tdir, usePoolLedger=True)
    s.registerObserver(trustAnchorWallet.handleIncomingReply)
    looper.add(s)
    looper.run(s.ensureConnectedToNodes())
    makePendingTxnsRequest(s, trustAnchorWallet)
    return s


@pytest.fixture(scope="module")
def addedTrustAnchor(nodeSet, steward, stewardWallet, looper,
                 trustAnchorWallet):
    createNym(looper,
              trustAnchorWallet.defaultId,
              steward,
              stewardWallet,
              role=TRUST_ANCHOR,
              verkey=trustAnchorWallet.getVerkey())
    return trustAnchorWallet


@pytest.fixture(scope="module")
def userWalletA(nodeSet, addedTrustAnchor, trustAnchorWallet, looper, trustAnchor):
    return addRole(looper, trustAnchor, trustAnchorWallet, 'userA', useDid=False,
                   addVerkey=False)


@pytest.fixture(scope="module")
def userWalletB(nodeSet, addedTrustAnchor, trustAnchorWallet, looper, trustAnchor):
    return addRole(looper, trustAnchor, trustAnchorWallet, 'userB', useDid=False,
                   addVerkey=False)


@pytest.fixture(scope="module")
def userIdA(userWalletA):
    return userWalletA.defaultId


@pytest.fixture(scope="module")
def userIdB(userWalletB):
    return userWalletB.defaultId


@pytest.fixture(scope="module")
def userClientA(nodeSet, userWalletA, looper, tdir):
    u, _ = genTestClient(nodeSet, tmpdir=tdir, usePoolLedger=True)
    u.registerObserver(userWalletA.handleIncomingReply)
    looper.add(u)
    looper.run(u.ensureConnectedToNodes())
    makePendingTxnsRequest(u, userWalletA)
    return u


@pytest.fixture(scope="module")
def userClientB(nodeSet, userWalletB, looper, tdir):
    u, _ = genTestClient(nodeSet, tmpdir=tdir, usePoolLedger=True)
    u.registerObserver(userWalletB.handleIncomingReply)
    looper.add(u)
    looper.run(u.ensureConnectedToNodes())
    makePendingTxnsRequest(u, userWalletB)
    return u


def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, str) and isinstance(right, str):
        if op in ('in', 'not in'):
            mod = 'not ' if 'not' in op else ''
            lines = ['    ' + s for s in right.split('\n')]
            return ['"{}" should {}be in...'.format(left, mod)] + lines


@pytest.fixture("module")
def nodeThetaAdded(looper, nodeSet, tdirWithPoolTxns, tconf, steward,
                   stewardWallet, allPluginsPath, testNodeClass,
                   testClientClass, tdir):
    newStewardName = "testClientSteward" + randomString(3)
    newNodeName = "Theta"
    newSteward, newStewardWallet = getClientAddedWithRole(nodeSet, tdir,
                                                          looper, steward,
                                                          stewardWallet,
                                                          newStewardName, STEWARD)

    sigseed = randomString(32).encode()
    nodeSigner = SimpleSigner(seed=sigseed)

    (nodeIp, nodePort), (clientIp, clientPort) = genHa(2)

    data = {
        NODE_IP: nodeIp,
        NODE_PORT: nodePort,
        CLIENT_IP: clientIp,
        CLIENT_PORT: clientPort,
        ALIAS: newNodeName,
        SERVICES: [VALIDATOR, ]
    }

    node = Node(nodeSigner.identifier, data, newStewardWallet.defaultId)
    newStewardWallet.addNode(node)
    reqs = newStewardWallet.preparePending()
    req, = newSteward.submitReqs(*reqs)

    waitForSufficientRepliesForRequests(looper, newSteward, requests=[req])

    def chk():
        assert newStewardWallet.getNode(node.id).seqNo is not None

    timeout = waits.expectedTransactionExecutionTime(len(nodeSet))
    looper.run(eventually(chk, retryWait=1, timeout=timeout))

    initLocalKeys(newNodeName, tdirWithPoolTxns, sigseed, override=True)

    newNode = testNodeClass(newNodeName, basedirpath=tdir, config=tconf,
                            ha=(nodeIp, nodePort), cliha=(clientIp, clientPort),
                            pluginPaths=allPluginsPath)

    nodeSet.append(newNode)
    looper.add(newNode)
    looper.run(checkNodesConnected(nodeSet))
    ensureClientConnectedToNodesAndPoolLedgerSame(looper, steward,
                                                  *nodeSet)
    ensureClientConnectedToNodesAndPoolLedgerSame(looper, newSteward,
                                                  *nodeSet)
    return newSteward, newStewardWallet, newNode



