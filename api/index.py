from http.server import BaseHTTPRequestHandler
import json
import asyncio
import requests
import os
from pytoniq import WalletV4R2, LiteBalancer
from pytoniq_core import Address

# ============================================
# TON WALLET CLASS - WITH CORRECT ADDRESS FORMAT
# ============================================

class TONWallet:
    """TON Wallet handler - Fixed address format"""
    
    def __init__(self):
        self.recovery_phrase = os.getenv('TON_RECOVERY_PHRASE')
        
        if not self.recovery_phrase:
            raise ValueError("TON_RECOVERY_PHRASE not set in environment")
        
        mnemonic_list = self.recovery_phrase.split()
        
        # Store mnemonics for later initialization
        self.mnemonic_list = mnemonic_list
        self.wallet = None
        self.address = None
        self.address_raw = None  # Raw format (EQC...)
        self.address_user_friendly = None  # User-friendly format (UQC...)
        self.provider = None
    
    async def _init_wallet(self):
        """Initialize wallet asynchronously"""
        if self.wallet is None:
            # Create provider
            self.provider = LiteBalancer.from_mainnet_config(trust_level=1)
            await self.provider.start_up()
            
            # Create wallet - AWAIT the coroutine
            self.wallet = await WalletV4R2.from_mnemonic(
                mnemonics=self.mnemonic_list,
                provider=self.provider
            )
            
            # Get address in RAW format (EQC...)
            self.address_raw = self.wallet.address.to_str()
            
            # Convert to USER-FRIENDLY format (UQC...)
            # Remove the workchain prefix and convert
            addr = Address(self.address_raw)
            self.address_user_friendly = addr.to_str(is_user_friendly=True)
            
            # Set default address to user-friendly
            self.address = self.address_user_friendly
            
            print(f"✅ Wallet loaded")
            print(f"   Raw address: {self.address_raw}")
            print(f"   User-friendly: {self.address_user_friendly}")
        
        return self.wallet
    
    async def get_balance(self):
        """Get TON balance"""
        try:
            # Initialize wallet first
            await self._init_wallet()
            
            # Use provider to get balance (works with any format)
            balance = await self.provider.get_balance(self.address_raw)
            return balance / 1e9
        except Exception as e:
            print(f"Balance error: {e}")
            # Fallback to TON Center API
            try:
                url = "https://toncenter.com/api/v2/getAddressBalance"
                params = {'address': self.address_raw}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    balance_nano = int(data.get('result', 0))
                    return balance_nano / 1e9
            except:
                pass
            return 0
    
    async def get_usdt_balance(self):
        """Get USDT balance"""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        
        try:
            await self._init_wallet()
            
            # Use TON Center API for USDT
            url = "https://toncenter.com/api/v2/getAccountJettonBalance"
            params = {
                'address': self.address_raw,
                'jetton_master': USDT_MASTER
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})
                balance = int(result.get('balance', 0))
                return balance / 1e9
            return 0
        except Exception as e:
            print(f"USDT balance error: {e}")
            return 0
    
    async def send_ton(self, to_address, amount_ton, comment=""):
        """Send TON"""
        try:
            await self._init_wallet()
            
            # Validate and convert address
            addr = Address(to_address)
            
            seqno = await self.wallet.get_seqno()
            
            tx = await self.wallet.transfer(
                destination=addr,
                amount=int(amount_ton * 1e9),
                comment=comment,
                seqno=seqno
            )
            
            await self.wallet.send_transfer(tx)
            
            return {
                'success': True,
                'tx_hash': tx.hash().hex(),
                'amount': amount_ton,
                'to': to_address,
                'from': self.address_user_friendly
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def send_usdt(self, to_address, amount_usdt, comment=""):
        """Send USDT"""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        
        try:
            await self._init_wallet()
            
            addr = Address(to_address)
            
            seqno = await self.wallet.get_seqno()
            
            tx = await self.wallet.transfer_jettons(
                jetton_master=Address(USDT_MASTER),
                destination=addr,
                amount=int(amount_usdt * 1e9),
                comment=comment,
                seqno=seqno
            )
            
            await self.wallet.send_transfer(tx)
            
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
        except:
            return False

# ============================================
# SINGLETON WALLET INSTANCE
# ============================================

_wallet_instance = None

def get_wallet():
    """Get or create wallet instance"""
    global _wallet_instance
    if _wallet_instance is None:
        _wallet_instance = TONWallet()
    return _wallet_instance

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
            wallet = get_wallet()
            
            # Run async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Initialize wallet first
            loop.run_until_complete(wallet._init_wallet())
            
            # Get balances
            ton_balance = loop.run_until_complete(wallet.get_balance())
            usdt_balance = loop.run_until_complete(wallet.get_usdt_balance())
            
            response = {
                'success': True,
                'address': wallet.address_user_friendly,  # User-friendly format
                'address_raw': wallet.address_raw,  # Raw format (for reference)
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
            wallet = get_wallet()
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(wallet._init_wallet())
            
            response = {
                'success': True,
                'address': wallet.address_user_friendly,  # User-friendly format
                'address_raw': wallet.address_raw,  # Raw format
                'explorer_url': f'https://tonscan.org/address/{wallet.address_user_friendly}',
                'network': 'mainnet'
            }
            self.send_success_response(response)
            
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_send_ton(self):
        """Handle sending TON"""
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
            
            wallet = get_wallet()
            
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Initialize wallet
            loop.run_until_complete(wallet._init_wallet())
            
            # Check balance
            balance = loop.run_until_complete(wallet.get_balance())
            if balance < amount:
                self.send_error_response(400, f'Insufficient balance. Have: {balance} TON')
                return
            
            # Send
            result = loop.run_until_complete(
                wallet.send_ton(to_address, amount, comment)
            )
            
            self.send_success_response(result)
            
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
            
            wallet = get_wallet()
            
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Initialize wallet
            loop.run_until_complete(wallet._init_wallet())
            
            # Check USDT balance
            usdt_balance = loop.run_until_complete(wallet.get_usdt_balance())
            if usdt_balance < amount:
                self.send_error_response(400, f'Insufficient USDT. Have: {usdt_balance} USDT')
                return
            
            result = loop.run_until_complete(
                wallet.send_usdt(to_address, amount, comment)
            )
            
            self.send_success_response(result)
            
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_withdrawal_link(self):
        """Handle withdrawal link creation"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())
            
            currency = data.get('currency', 'TON')
            network = data.get('network', 'TON')
            address = data.get('address')
            amount = data.get('amount')
            
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
                data = response.json()
                response_data = {
                    'success': True,
                    'telegram_link': data.get('data', {}).get('telegramAppLink'),
                    'amount': amount,
                    'currency': currency,
                    'address': address
                }
                self.send_success_response(response_data)
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
