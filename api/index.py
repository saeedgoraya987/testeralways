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
        """Initialize wallet"""
        if self.wallet is not None:
            return self.wallet
        
        # Create provider
        self.provider = LiteBalancer.from_mainnet_config(trust_level=1)
        await self.provider.start_up()
        
        # Create wallet
        self.wallet = await WalletV4R2.from_mnemonic(
            mnemonics=self.mnemonic_list,
            provider=self.provider
        )
        
        # Get addresses
        # FIX: use is_url_safe=True for proper base64url encoding of user-friendly address
        self.address_raw = self.wallet.address.to_str(is_user_friendly=False)
        self.address_user_friendly = self.wallet.address.to_str(
            is_user_friendly=True,
            is_url_safe=True,
            is_bounceable=True
        )
        
        print(f"✅ Wallet loaded: {self.address_user_friendly}")
        
        return self.wallet
    
    async def get_balance(self):
        """Get TON balance"""
        try:
            await self.init_wallet()
            # FIX: LiteBalancer has no get_balance(); use get_account_state() instead
            state = await self.provider.get_account_state(Address(self.address_raw))
            return state.balance / 1e9
        except Exception as e:
            print(f"Balance error: {e}")
            # Fallback: use Toncenter REST API
            try:
                url = "https://toncenter.com/api/v2/getAddressBalance"
                params = {'address': self.address_raw}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    balance_nano = int(data.get('result', 0))
                    return balance_nano / 1e9
            except Exception:
                pass
            return 0
    
    async def get_usdt_balance(self):
        """Get USDT balance"""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        
        try:
            await self.init_wallet()
            
            # FIX: /api/v2/getAccountJettonBalance does not exist.
            # Use Toncenter v3 jetton wallet endpoint instead.
            url = "https://toncenter.com/api/v3/jetton/wallets"
            params = {
                'owner_address': self.address_raw,
                'jetton_address': USDT_MASTER
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                wallets = data.get('jetton_wallets', [])
                if wallets:
                    # FIX: USDT on TON uses 6 decimals, not 9
                    balance = int(wallets[0].get('balance', 0))
                    return balance / 1e6
            return 0
        except Exception as e:
            print(f"USDT balance error: {e}")
            return 0
    
    async def send_ton(self, to_address, amount_ton, comment=""):
        """Send TON"""
        try:
            # Initialize wallet
            await self.init_wallet()
            
            # Validate address
            addr = Address(to_address)
            
            # Note: seqno is fetched internally by wallet.transfer() — no need to pass it manually

            # Check balance
            balance = await self.get_balance()
            if balance < amount_ton:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Have: {balance} TON, Need: {amount_ton} TON'
                }
            
            print(f"💰 Balance: {balance} TON")
            
            # Create comment cell if needed
            message = None
            if comment:
                message = (
                    begin_cell()
                    .store_uint(0, 32)
                    .store_string(comment)
                    .end_cell()
                )
            
            # FIX: wallet.transfer() BOTH builds AND sends the transaction.
            # It returns the external message Cell. There is no send_transfer() method.
            # FIX: 'seqno' is not an accepted keyword argument — transfer() fetches it internally.
            tx = await self.wallet.transfer(
                destination=addr,
                amount=int(amount_ton * 1e9),
                body=message
            )
            # FIX: removed the invalid `await self.wallet.send_transfer(tx)` call —
            # that method does not exist; transfer() already sent the message above.
            
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
            return {
                'success': False,
                'error': error_msg
            }
    
    async def send_usdt(self, to_address, amount_usdt, comment=""):
        """Send USDT"""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        
        try:
            await self.init_wallet()
            
            addr = Address(to_address)

            # Note: seqno is fetched internally by wallet.transfer() — no need to pass it manually

            # Check USDT balance
            usdt_balance = await self.get_usdt_balance()
            if usdt_balance < amount_usdt:
                return {
                    'success': False,
                    'error': f'Insufficient USDT. Have: {usdt_balance} USDT'
                }
            
            # FIX: WalletV4R2 has no transfer_jettons() method.
            # Jetton transfers require:
            #   1. Retrieve the user's personal jetton wallet address (not the master)
            #   2. Build the jetton transfer message payload manually (op 0xf8a7ea5)
            #   3. Send TON (for fees) to that jetton wallet with the payload as body

            # Step 1: Get user's USDT jetton wallet address via Toncenter v3
            try:
                resp = requests.get(
                    "https://toncenter.com/api/v3/jetton/wallets",
                    params={
                        "owner_address": self.address_raw,
                        "jetton_address": USDT_MASTER
                    },
                    timeout=10
                )
                resp.raise_for_status()
                jetton_wallets = resp.json().get("jetton_wallets", [])
                if not jetton_wallets:
                    return {
                        'success': False,
                        'error': 'No USDT jetton wallet found for this address'
                    }
                jetton_wallet_addr = Address(jetton_wallets[0]["address"])
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to get USDT jetton wallet address: {e}'
                }

            # Step 2: Build the jetton transfer message body
            body = (
                begin_cell()
                .store_uint(0xf8a7ea5, 32)           # op: jetton_transfer
                .store_uint(0, 64)                    # query_id
                # FIX: USDT uses 6 decimals (1e6), not 9
                .store_coins(int(amount_usdt * 1e6))  # transfer amount in minimal units
                .store_address(addr)                  # destination address
                .store_address(self.wallet.address)   # response_destination (return excess TON here)
                .store_uint(0, 1)                     # no custom payload (0 = None)
                .store_coins(1)                       # forward_ton_amount (1 nanoton for notification)
                .store_uint(0, 1)                     # forward_payload inline (not ref)
                .end_cell()
            )

            # Optionally attach comment to forward payload
            if comment:
                body = (
                    begin_cell()
                    .store_uint(0xf8a7ea5, 32)
                    .store_uint(0, 64)
                    .store_coins(int(amount_usdt * 1e6))
                    .store_address(addr)
                    .store_address(self.wallet.address)
                    .store_uint(0, 1)
                    .store_coins(int(0.001 * 1e9))    # slightly more TON to carry forward payload
                    .store_uint(1, 1)                  # forward_payload as ref
                    .store_ref(
                        begin_cell()
                        .store_uint(0, 32)
                        .store_string(comment)
                        .end_cell()
                    )
                    .end_cell()
                )

            # Step 3: Send to the jetton wallet with 0.05 TON for gas
            # FIX: removed invalid transfer_jettons() and send_transfer() calls
            # FIX: 'seqno' is not an accepted keyword argument — transfer() fetches it internally.
            tx = await self.wallet.transfer(
                destination=jetton_wallet_addr,
                amount=int(0.05 * 1e9),   # 0.05 TON to cover jetton transfer gas
                body=body
            )
            # FIX: removed the invalid `await self.wallet.send_transfer(tx)` call —
            # transfer() already sent the message above.
            
            return {
                'success': True,
                'tx_hash': tx.hash().hex(),
                'amount': amount_usdt,
                'to': to_address,
                'currency': 'USDT',
                'from': self.address_user_friendly
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def validate_address(self, address):
        """Validate TON address"""
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
        """Handle GET requests"""
        path = self.path.split('?')[0]
        
        if path == '/api/balance' or path == '/balance':
            self.handle_balance()
        elif path == '/api/wallet' or path == '/wallet':
            self.handle_wallet_info()
        elif path == '/':
            self.handle_root()
        else:
            self.send_error_response(404, 'Endpoint not found')
    
    def do_POST(self):
        """Handle POST requests"""
        path = self.path.split('?')[0]
        
        if path == '/api/send-ton' or path == '/send-ton':
            self.handle_send_ton()
        elif path == '/api/send-usdt' or path == '/send-usdt':
            self.handle_send_usdt()
        elif path == '/api/withdrawal-link' or path == '/withdrawal-link':
            self.handle_withdrawal_link()
        else:
            self.send_error_response(404, 'Endpoint not found')
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    # ============================================
    # Handlers
    # ============================================
    
    def handle_root(self):
        """Root endpoint - API info"""
        response = {
            'name': 'TON Payment API',
            'version': '1.0.0',
            'endpoints': {
                'GET /balance': 'Check wallet balance',
                'GET /wallet': 'Get wallet info',
                'POST /send-ton': 'Send TON',
                'POST /send-usdt': 'Send USDT',
                'POST /withdrawal-link': 'Create withdrawal link'
            }
        }
        self.send_success_response(response)
    
    def handle_balance(self):
        """Handle balance check"""
        try:
            async def get_balances():
                wallet = TONWallet()
                await wallet.init_wallet()
                ton = await wallet.get_balance()
                usdt = await wallet.get_usdt_balance()
                return wallet, ton, usdt
            
            wallet, ton_balance, usdt_balance = asyncio.run(get_balances())
            
            response = {
                'success': True,
                'address': wallet.address_user_friendly,
                'address_raw': wallet.address_raw,
                'balances': {
                    'ton': ton_balance,
                    'usdt': usdt_balance
                }
            }
            self.send_success_response(response)
            
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_wallet_info(self):
        """Handle wallet info"""
        try:
            async def get_wallet_info():
                wallet = TONWallet()
                await wallet.init_wallet()
                return wallet
            
            wallet = asyncio.run(get_wallet_info())
            
            response = {
                'success': True,
                'address': wallet.address_user_friendly,
                'address_raw': wallet.address_raw,
                'explorer_url': f'https://tonscan.org/address/{wallet.address_user_friendly}',
                'network': 'mainnet'
            }
            self.send_success_response(response)
            
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_send_ton(self):
        """Handle sending TON"""
        try:
            # Parse request
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())
            
            # Validate
            required = ['to_address', 'amount']
            for field in required:
                if field not in data:
                    self.send_error_response(400, f'Missing field: {field}')
                    return
            
            to_address = data['to_address']
            amount = float(data['amount'])
            comment = data.get('comment', '')
            
            if amount <= 0:
                self.send_error_response(400, 'Amount must be greater than 0')
                return
            
            # Validate address
            wallet = TONWallet()
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            # Send TON
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
        """Handle sending USDT"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())
            
            required = ['to_address', 'amount']
            for field in required:
                if field not in data:
                    self.send_error_response(400, f'Missing field: {field}')
                    return
            
            to_address = data['to_address']
            amount = float(data['amount'])
            comment = data.get('comment', '')
            
            if amount <= 0:
                self.send_error_response(400, 'Amount must be greater than 0')
                return
            
            wallet = TONWallet()
            
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            async def send_usdt():
                w = TONWallet()
                await w.init_wallet()
                return await w.send_usdt(to_address, amount, comment)
            
            result = asyncio.run(send_usdt())
            
            if result.get('success'):
                self.send_success_response(result)
            else:
                self.send_error_response(400, result.get('error', 'Send failed'))
            
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_withdrawal_link(self):
        """Handle withdrawal link creation"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            # FIX: renamed from 'data' to 'req_data' to prevent variable shadowing
            # when response.json() is read later in this function
            req_data = json.loads(post_data.decode())
            
            currency = req_data.get('currency', 'TON')
            network = req_data.get('network', 'TON')
            address = req_data.get('address')
            amount = req_data.get('amount')
            
            if not address or not amount:
                self.send_error_response(400, 'address and amount are required')
                return
            
            params = {
                'currency': currency,
                'network': network,
                'address': address,
                'amount': str(amount)
            }
            
            response = requests.get(
                'https://pay.xrocket.tg/withdrawal-link',
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                # FIX: was 'data = response.json()' which shadowed the request body variable
                resp_data = response.json()
                response_payload = {
                    'success': True,
                    'telegram_link': resp_data.get('data', {}).get('telegramAppLink'),
                    'amount': amount,
                    'currency': currency,
                    'address': address
                }
                self.send_success_response(response_payload)
            else:
                self.send_error_response(500, 'Failed to create withdrawal link')
            
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))
    
    # ============================================
    # Response Helpers
    # ============================================
    
    def send_success_response(self, data):
        """Send success response"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def send_error_response(self, code, message):
        """Send error response"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = {
            'success': False,
            'error': message
        }
        self.wfile.write(json.dumps(response, indent=2).encode())

# ============================================
# Local Development
# ============================================

if __name__ == '__main__':
    from http.server import HTTPServer
    
    PORT = 5000
    server = HTTPServer(('0.0.0.0', PORT), handler)
    print(f'🚀 TON Payment API running on http://localhost:{PORT}')
    print(f'📋 Endpoints:')
    print(f'   GET  /balance')
    print(f'   GET  /wallet')
    print(f'   POST /send-ton')
    print(f'   POST /send-usdt')
    print(f'   POST /withdrawal-link')
    print(f'⚠️  Make sure TON_RECOVERY_PHRASE is set in .env')
    server.serve_forever()
