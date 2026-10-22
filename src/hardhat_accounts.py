"""
src/hardhat_accounts.py
------------------------------------------------------------------------------
Hardhat's default local-node accounts (from its fixed test mnemonic: "test
test test test test test test test test test test junk"). These are
identical on every `npx hardhat node` restart - that determinism is exactly
why they are safe to hardcode for LOCAL DEVELOPMENT ONLY. They are public
knowledge; anyone can derive them from the well-known mnemonic. NEVER fund
these addresses or use these keys outside a local Hardhat network.

Verified directly against a real running node's printed output in this
project's build log (not reproduced from memory), then hardcoded here so
oracle_bridge.py and simulate_trades.py don't depend on parsing log output
at runtime (which is timing-sensitive - Hardhat buffers stdout when it isn't
a TTY, so a log file can appear empty for several seconds after startup).

account #0 = oracle/deployer/admin (matches Section 8: "Oracle account:
Hardhat accounts[0]"). accounts #1-20 = the 20 devices, in the same order
deploy.js registers them (DEV_000 -> account #1, ..., DEV_019 -> account #20).
------------------------------------------------------------------------------
"""

ACCOUNTS_BY_INDEX = {
    0: ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"),
    1: ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"),
    2: ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"),
    3: ("0x90F79bf6EB2c4f870365E785982E1f101E93b906", "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"),
    4: ("0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65", "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"),
    5: ("0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc", "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba"),
    6: ("0x976EA74026E726554dB657fA54763abd0C3a0aa9", "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e"),
    7: ("0x14dC79964da2C08b23698B3D3cc7Ca32193d9955", "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356"),
    8: ("0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f", "0xdbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97"),
    9: ("0xa0Ee7A142d267C1f36714E4a8F75612F20a79720", "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6"),
    10: ("0xBcd4042DE499D14e55001CcbB24a551F3b954096", "0xf214f2b2cd398c806f84e317254e0f0b801d0643303237d97a22a48e01628897"),
    11: ("0x71bE63f3384f5fb98995898A86B02Fb2426c5788", "0x701b615bbdfb9de65240bc28bd21bbc0d996645a3dd57e7b12bc2bdf6f192c82"),
    12: ("0xFABB0ac9d68B0B445fB7357272Ff202C5651694a", "0xa267530f49f8280200edf313ee7af6b827f2a8bce2897751d06a843f644967b1"),
    13: ("0x1CBd3b2770909D4e10f157cABC84C7264073C9Ec", "0x47c99abed3324a2707c28affff1267e45918ec8c3f20b8aa892e8b065d2942dd"),
    14: ("0xdF3e18d64BC6A983f673Ab319CCaE4f1a57C7097", "0xc526ee95bf44d8fc405a158bb884d9d1238d99f0612e9f33d006bb0789009aaa"),
    15: ("0xcd3B766CCDd6AE721141F452C550Ca635964ce71", "0x8166f546bab6da521a8369cab06c5d2b9e46670292d85c875ee9ec20e84ffb61"),
    16: ("0x2546BcD3c84621e976D8185a91A922aE77ECEc30", "0xea6c44ac03bff858b476bba40716402b03e41b8e97e276d1baec7c37d42484a0"),
    17: ("0xbDA5747bFD65F08deb54cb465eB87D40e51B197E", "0x689af8efa8c651a91ad287602527f3af2fe9f6501a7ac4b061667b5a93e037fd"),
    18: ("0xdD2FD4581271e230360230F9337D5c0430Bf44C0", "0xde9be858da4a475276426320d5e9262ecfc3ba460bfac56360bfa6c4c28b4ee0"),
    19: ("0x8626f6940E2eb28930eFb4CeF49B2d1F2C9C1199", "0xdf57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e"),
    20: ("0x09DB0a93B389bEF724429898f539AEB7ac2Dd55f", "0xeaa861a9a01391ed3d587d8a5a84ca56ee277629a8b02c22093a419bf240e65d"),
    21: ("0x02484cb50AAC86Eae85610D6f4Bf026f30f6627D", "0xc511b2aa70776d4ff1d376e8537903dae36896132c90b91d52c1dfbae267cd8b"),
    22: ("0x08135Da0A343E492FA2d4282F2AE34c6c5CC1BbE", "0x224b7eb7449992aac96d631d9677f7bf5888245eef6d6eeda31e62d2f29a83e4"),
    23: ("0x5E661B79FE2D3F6cE70F5AAC07d8Cd9abb2743F1", "0x4624e0802698b9769f5bdb260a3777fbd4941ad2901f5966b854f953497eec1b"),
    24: ("0x61097BA76cD906d2ba4FD106E757f7Eb455fc295", "0x375ad145df13ed97f8ca8e27bb21ebf2a3819e9e0a06509a812db377e533def7"),
    25: ("0xDf37F81dAAD2b0327A0A50003740e1C935C70913", "0x18743e59419b01d1d846d97ea070b5a3368a3e7f6f0242cf497e1baac6972427"),
    26: ("0x553BC17A05702530097c3677091C5BB47a3a7931", "0xe383b226df7c8282489889170b0f68f66af6459261f4833a781acd0804fafe7a"),
    27: ("0x87BdCE72c06C21cd96219BD8521bDF1F42C78b5e", "0xf3a6b71b94f5cd909fb2dbb287da47badaa6d8bcdc45d595e2884835d8749001"),
    28: ("0x40Fc963A729c542424cD800349a7E4Ecc4896624", "0x4e249d317253b9641e477aba8dd5d8f1f7cf5250a5acadd1229693e262720a19"),
    29: ("0x9DCCe783B6464611f38631e6C851bf441907c710", "0x233c86e887ac435d7f7dc64979d7758d69320906a0d340d2b6518b0fd20aa998"),
}

# address (checksummed as printed by Hardhat) -> private key
KEY_BY_ADDRESS = {addr: pk for addr, pk in ACCOUNTS_BY_INDEX.values()}

ORACLE_ADDRESS, ORACLE_PRIVATE_KEY = ACCOUNTS_BY_INDEX[0]


def private_key_for(address: str) -> str:
    if address not in KEY_BY_ADDRESS:
        raise KeyError(f"No known private key for {address} - is this one of Hardhat's default 30 accounts?")
    return KEY_BY_ADDRESS[address]
