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
        self.address_user_friendly = self.wallet.address.to_str(
            is_user_friendly=True,
            is_url_safe=True,
            is_bounceable=True
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

            # FIX: transfer() both builds AND sends; it returns the sent Cell.
            # No seqno parameter (pytoniq fetches it internally).
            # No send_transfer() call needed — transfer() already sent the message.
            tx = await self.wallet.transfer(
                destination=addr,
                amount=int(amount_ton * 1e9),
                body=body
            )

            return {
                'success': True,
                'tx_hash': tx.hash().hex(),
                'amount': amount_ton,
                'to': to_address,
                'from': self.address_user_friendly,
                'comment': comment
            }

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Send error: {error_msg}")
            return {'success': False, 'error': error_msg}

    async def send_usdt(self, to_address, amount_usdt, comment=""):
        """Send USDT (jetton) to an address."""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"

        try:
            await self.init_wallet()

            addr = Address(to_address)

            # FIX: deploy wallet contract if this is its first on-chain transaction.
            await self._ensure_deployed()

            # Check USDT balance
            usdt_balance = await self.get_usdt_balance()
            if usdt_balance < amount_usdt:
                return {
                    'success': False,
                    'error': f'Insufficient USDT. Have: {usdt_balance} USDT'
                }

            # FIX: WalletV4R2 has no transfer_jettons() method.
            # Jetton transfers require three steps:
            #   1. Look up the user's personal jetton wallet address (not the master).
            #   2. Build the standard jetton transfer message (op 0xf8a7ea5).
            #   3. Send TON (for gas) to that jetton wallet with the payload as body.

            # Step 1 — get user's USDT jetton wallet address via Toncenter v3
            try:
                resp = requests.get(
                    "https://toncenter.com/api/v3/jetton/wallets",
                    params={
                        'owner_address': self.address_raw,
                        'jetton_address': USDT_MASTER
                    },
                    timeout=10
                )
                resp.raise_for_status()
                jetton_wallets = resp.json().get('jetton_wallets', [])
                if not jetton_wallets:
                    return {
                        'success': False,
                        'error': 'No USDT jetton wallet found for this address. '
                                 'You may not hold any USDT yet.'
                    }
                jetton_wallet_addr = Address(jetton_wallets[0]['address'])
            except Exception as e:
                return {'success': False, 'error': f'Failed to get USDT jetton wallet: {e}'}

            # Step 2 — build the jetton transfer payload
            # FIX: USDT on TON uses 6 decimals (1e6), not 9.
            if comment:
                forward_payload = (
                    begin_cell()
                    .store_uint(0, 32)
                    .store_snake_string(comment)
                    .end_cell()
                )
                body = (
                    begin_cell()
                    .store_uint(0xf8a7ea5, 32)           # op: jetton_transfer
                    .store_uint(0, 64)                    # query_id
                    .store_coins(int(amount_usdt * 1e6))  # amount in minimal USDT units
                    .store_address(addr)                  # recipient
                    .store_address(self.wallet.address)   # return excess TON here
                    .store_uint(0, 1)                     # no custom payload
                    .store_coins(int(0.001 * 1e9))        # forward TON (to carry payload)
                    .store_uint(1, 1)                     # forward_payload as cell ref
                    .store_ref(forward_payload)
                    .end_cell()
                )
            else:
                body = (
                    begin_cell()
                    .store_uint(0xf8a7ea5, 32)
                    .store_uint(0, 64)
                    .store_coins(int(amount_usdt * 1e6))
                    .store_address(addr)
                    .store_address(self.wallet.address)
                    .store_uint(0, 1)
                    .store_coins(1)                       # 1 nanoton forward for notification
                    .store_uint(0, 1)                     # no forward payload
                    .end_cell()
                )

            # Step 3 — send to the jetton wallet (NOT the master contract)
            # 0.05 TON covers jetton transfer gas fees.
            tx = await self.wallet.transfer(
                destination=jetton_wallet_addr,
                amount=int(0.05 * 1e9),
                body=body
            )

            return {
                'success': True,
                'tx_hash': tx.hash().hex(),
                'amount': amount_usdt,
                'to': to_address,
                'currency': 'USDT',
                'from': self.address_user_friendly
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

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
        if path in ('/api/balance', '/balance'):
            self.handle_balance()
        elif path in ('/api/wallet', '/wallet'):
            self.handle_wallet_info()
        elif path == '/':
            self.handle_root()
        else:
            self.send_error_response(404, 'Endpoint not found')

    def do_POST(self):
        path = self.path.split('?')[0]
        if path in ('/api/send-ton', '/send-ton'):
            self.handle_send_ton()
        elif path in ('/api/send-usdt', '/send-usdt'):
            self.handle_send_usdt()
        elif path in ('/api/withdrawal-link', '/withdrawal-link'):
            self.handle_withdrawal_link()
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

    def handle_root(self):
        self.send_success_response({
            'name': 'TON Payment API',
            'version': '1.0.0',
            'endpoints': {
                'GET /balance': 'Check wallet balance',
                'GET /wallet': 'Get wallet info',
                'POST /send-ton': 'Send TON',
                'POST /send-usdt': 'Send USDT',
                'POST /withdrawal-link': 'Create withdrawal link'
            }
        })

    def handle_balance(self):
        try:
            async def get_balances():
                w = TONWallet()
                await w.init_wallet()
                ton = await w.get_balance()
                usdt = await w.get_usdt_balance()
                return w, ton, usdt

            wallet, ton_balance, usdt_balance = asyncio.run(get_balances())
            self.send_success_response({
                'success': True,
                'address': wallet.address_user_friendly,
                'address_raw': wallet.address_raw,
                'balances': {'ton': ton_balance, 'usdt': usdt_balance}
            })
        except Exception as e:
            self.send_error_response(500, str(e))

    def handle_wallet_info(self):
        try:
            async def get_info():
                w = TONWallet()
                await w.init_wallet()
                return w

            wallet = asyncio.run(get_info())
            self.send_success_response({
                'success': True,
                'address': wallet.address_user_friendly,
                'address_raw': wallet.address_raw,
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

    def handle_send_usdt(self):
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
                return await w.send_usdt(to_address, amount, comment)

            result = asyncio.run(send())
            if result.get('success'):
                self.send_success_response(result)
            else:
                self.send_error_response(400, result.get('error', 'Send failed'))

        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))

    def handle_withdrawal_link(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            # FIX: renamed from 'data' to 'req_data' — the original code later did
            # `data = response.json()` which silently shadowed the request body.
            req_data = json.loads(self.rfile.read(content_length).decode())

            currency = req_data.get('currency', 'TON')
            network = req_data.get('network', 'TON')
            address = req_data.get('address')
            amount = req_data.get('amount')

            if not address or not amount:
                self.send_error_response(400, 'address and amount are required')
                return

            resp = requests.get(
                'https://pay.xrocket.tg/withdrawal-link',
                params={
                    'currency': currency,
                    'network': network,
                    'address': address,
                    'amount': str(amount)
                },
                timeout=10
            )

            if resp.status_code == 200:
                resp_data = resp.json()
                self.send_success_response({
                    'success': True,
                    'telegram_link': resp_data.get('data', {}).get('telegramAppLink'),
                    'amount': amount,
                    'currency': currency,
                    'address': address
                })
            else:
                self.send_error_response(500, 'Failed to create withdrawal link')

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
    print('   GET  /balance')
    print('   GET  /wallet')
    print('   POST /send-ton')
    print('   POST /send-usdt')
    print('   POST /withdrawal-link')
    print('⚠️  Make sure TON_RECOVERY_PHRASE is set in .env')
    server.serve_forever()
