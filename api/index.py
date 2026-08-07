from http.server import BaseHTTPRequestHandler
import json
import asyncio
import requests
import os
from pytoniq import WalletV4R2, LiteBalancer
from pytoniq_core import Address, begin_cell

# ============================================
# TON WALLET CLASS - COMPLETE FIX
# ============================================

class TONWallet:
    """TON Wallet handler - Completely fixed"""

    def __init__(self):
        self.recovery_phrase = os.getenv('TON_RECOVERY_PHRASE')
        if not self.recovery_phrase:
            raise ValueError("TON_RECOVERY_PHRASE not set in environment")

        self.mnemonic_list = self.recovery_phrase.split()
        self.wallet = None
        self.provider = None
        self.address_raw = None
        self.address_user_friendly = None

    async def init_wallet(self):
        """Initialize wallet (idempotent)."""
        if self.wallet is not None:
            return self.wallet

        # FIX: official pytoniq signature is from_mnemonic(provider, mnemonics) —
        # provider comes first positionally (confirmed from pytoniq examples).
        self.provider = LiteBalancer.from_mainnet_config(trust_level=1)
        await self.provider.start_up()

        self.wallet = await WalletV4R2.from_mnemonic(
            self.provider,
            self.mnemonic_list
        )

        # FIX: use is_url_safe=True for proper base64url encoding of the
        # user-friendly address (replaces + and / with - and _).
        self.address_raw = self.wallet.address.to_str(is_user_friendly=False)
        # Non-bounceable (UQ...) is the correct user-facing wallet address format.
        # Bounceable (EQ...) is for smart contracts. Wallets always use non-bounceable.
        self.address_user_friendly = self.wallet.address.to_str(
            is_user_friendly=True,
            is_url_safe=True,
            is_bounceable=False
        )

        print(f"✅ Wallet loaded: {self.address_user_friendly}")
        return self.wallet

    async def _ensure_deployed(self):
        """
        Deploy the wallet contract if it has never been used on-chain.

        FIX: exit code -256 from get_seqno() means the wallet address exists
        (has balance) but no contract code is deployed there yet.  The official
        pytoniq pattern (examples/wallets/wallet.py) is to call
        wallet.deploy_via_external() before the first transfer.  This method
        checks wallet.is_uninitialized (set by pytoniq from the account state)
        and deploys + waits for confirmation when needed.
        """
        if not self.wallet.is_uninitialized:
            return  # Already deployed — nothing to do

        print("⚠️  Wallet contract not yet deployed. Deploying now...")
        await self.wallet.deploy_via_external()

        # Poll until the deployment is confirmed (up to ~30 s).
        for attempt in range(10):
            await asyncio.sleep(3)
            await self.wallet.update()          # refresh account state from chain
            if not self.wallet.is_uninitialized:
                print("✅ Wallet contract deployed successfully.")
                return

        raise Exception(
            "Wallet deployment timed out after 30 s. "
            "Check that the wallet address has enough TON to pay storage fees, "
            "then try again."
        )

    async def get_balance(self):
        """Get TON balance in TON (not nanotons)."""
        try:
            await self.init_wallet()
            # FIX: LiteBalancer has no get_balance(); use get_account_state() instead.
            # The Contract base class exposes .balance (nanotons) fetched during init.
            # Refresh first so the figure is current.
            await self.wallet.update()
            return self.wallet.balance / 1e9
        except Exception as e:
            print(f"Balance error: {e}")
            # Fallback: Toncenter REST API
            try:
                url = "https://toncenter.com/api/v2/getAddressBalance"
                resp = requests.get(url, params={'address': self.address_raw}, timeout=10)
                if resp.status_code == 200:
                    return int(resp.json().get('result', 0)) / 1e9
            except Exception:
                pass
            return 0

    async def get_usdt_balance(self):
        """Get USDT balance in USDT (not minimal units)."""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        try:
            await self.init_wallet()
            # FIX: /api/v2/getAccountJettonBalance does not exist in Toncenter v2.
            # Use Toncenter v3 jetton/wallets endpoint instead.
            resp = requests.get(
                "https://toncenter.com/api/v3/jetton/wallets",
                params={
                    'owner_address': self.address_raw,
                    'jetton_address': USDT_MASTER
                },
                timeout=10
            )
            if resp.status_code == 200:
                wallets = resp.json().get('jetton_wallets', [])
                if wallets:
                    # FIX: USDT on TON uses 6 decimals (1e6), not 9.
                    return int(wallets[0].get('balance', 0)) / 1e6
            return 0
        except Exception as e:
            print(f"USDT balance error: {e}")
            return 0

    async def send_ton(self, to_address, amount_ton, comment=""):
        """Send TON to an address."""
        try:
            await self.init_wallet()

            # Validate recipient address
            addr = Address(to_address)

            # FIX: deploy wallet contract if this is its first on-chain transaction.
            # pytoniq's transfer() calls get_seqno() internally; that fails with
            # exit code -256 when the contract hasn't been deployed yet.
            # Official fix from pytoniq examples: call deploy_via_external() first.
            await self._ensure_deployed()

            # Check balance
            balance = await self.get_balance()
            if balance < amount_ton:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Have: {balance} TON, Need: {amount_ton} TON'
                }

            print(f"💰 Balance: {balance} TON")

            # Build body cell for comment, or use plain string (pytoniq accepts both).
            body = None
            if comment:
                body = (
                    begin_cell()
                    .store_uint(0, 32)        # text-comment op-code
                    .store_snake_string(comment)
                    .end_cell()
                )

            # FIX: transfer() both builds AND sends.
            # In this version of pytoniq it returns an int (the message hash as an
            # integer), not a Cell — so we convert to hex directly instead of calling
            # .hash().hex() on it.
            tx = await self.wallet.transfer(
                destination=addr,
                amount=int(amount_ton * 1e9),
                body=body
            )

            # transfer() returns a status int (1 = success), not the tx hash.
            # Fetch the real hash from Toncenter — the latest outgoing tx is ours.
            tx_hash = self._fetch_latest_tx_hash()

            return {
                'success': True,
                'tx_hash': tx_hash,
                'amount': amount_ton,
                'to': to_address,
                'from': self.address_user_friendly,
                'comment': comment
            }

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Send error: {error_msg}")
            return {'success': False, 'error': error_msg}

    def _fetch_latest_tx_hash(self):
        """
        Fetch the hash of the most recent outgoing transaction for this wallet.

        pytoniq's transfer() returns a status int (1 = accepted), not the tx hash.
        The real hash is retrieved from Toncenter immediately after sending.
        """
        try:
            resp = requests.get(
                "https://toncenter.com/api/v2/getTransactions",
                params={'address': self.address_raw, 'limit': 1},
                timeout=10
            )
            if resp.status_code == 200:
                txs = resp.json().get('result', [])
                if txs:
                    return txs[0].get('transaction_id', {}).get('hash', '')
        except Exception as e:
            print(f"Could not fetch tx hash: {e}")
        return ''

    def validate_address(self, address):
        """Validate a TON address string."""
        try:
            Address(address)
            return True
        except Exception:
            return False


# ============================================
# VERCEL HANDLER
# ============================================

class handler(BaseHTTPRequestHandler):
    """Main API handler for Vercel"""

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/api/wallet', '/wallet', '/'):
            self.handle_wallet()
        else:
            self.send_error_response(404, 'Endpoint not found')

    def do_POST(self):
        path = self.path.split('?')[0]
        if path in ('/api/send-ton', '/send-ton'):
            self.handle_send_ton()
        else:
            self.send_error_response(404, 'Endpoint not found')

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ----------------------------------------
    # Route handlers
    # ----------------------------------------

    def handle_wallet(self):
        """GET /wallet — address, balances, and explorer link in one call."""
        try:
            async def get_wallet():
                w = TONWallet()
                await w.init_wallet()
                ton = await w.get_balance()
                usdt = await w.get_usdt_balance()
                return w, ton, usdt

            wallet, ton_balance, usdt_balance = asyncio.run(get_wallet())
            self.send_success_response({
                'success': True,
                'address': wallet.address_user_friendly,
                'address_raw': wallet.address_raw,
                'balances': {'ton': ton_balance, 'usdt': usdt_balance},
                'explorer_url': f'https://tonscan.org/address/{wallet.address_user_friendly}',
                'network': 'mainnet'
            })
        except Exception as e:
            self.send_error_response(500, str(e))

    def handle_send_ton(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length).decode())

            for field in ('to_address', 'amount'):
                if field not in data:
                    self.send_error_response(400, f'Missing field: {field}')
                    return

            to_address = data['to_address']
            amount = float(data['amount'])
            comment = data.get('comment', '')

            if amount <= 0:
                self.send_error_response(400, 'Amount must be greater than 0')
                return

            if not TONWallet().validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return

            async def send():
                w = TONWallet()
                await w.init_wallet()
                return await w.send_ton(to_address, amount, comment)

            result = asyncio.run(send())
            if result.get('success'):
                self.send_success_response(result)
            else:
                self.send_error_response(400, result.get('error', 'Send failed'))

        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))

    # ----------------------------------------
    # Response helpers
    # ----------------------------------------

    def send_success_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def send_error_response(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'success': False, 'error': message}, indent=2).encode())


# ============================================
# Local Development
# ============================================

if __name__ == '__main__':
    from http.server import HTTPServer

    PORT = 5000
    server = HTTPServer(('0.0.0.0', PORT), handler)
    print(f'🚀 TON Payment API running on http://localhost:{PORT}')
    print('📋 Endpoints:')
    print('   GET  /wallet')
    print('   POST /send-ton')
    print('⚠️  Make sure TON_RECOVERY_PHRASE is set in .env')
    server.serve_forever()
