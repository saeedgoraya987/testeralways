from http.server import BaseHTTPRequestHandler
import json
import asyncio
import requests
import os
from pytoniq import WalletV4R2, LiteBalancer
from pytoniq_core import Address, Cell, begin_cell

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
        self.address_raw = self.wallet.address.to_str()
        addr = Address(self.address_raw)
        self.address_user_friendly = addr.to_str(is_user_friendly=True)
        
        print(f"✅ Wallet loaded: {self.address_user_friendly}")
        
        return self.wallet
    
    async def get_balance(self):
        """Get TON balance"""
        try:
            await self.init_wallet()
            balance = await self.provider.get_balance(self.address_raw)
            return balance / 1e9
        except Exception as e:
            print(f"Balance error: {e}")
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
            await self.init_wallet()
            
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
        """Send TON - COMPLETELY FIXED"""
        try:
            # Initialize wallet
            await self.init_wallet()
            
            # Validate address
            addr = Address(to_address)
            
            # Get seqno - ALWAYS try to get it from chain
            try:
                seqno = await self.wallet.get_seqno()
                print(f"📊 Seqno from chain: {seqno}")
            except Exception as e:
                print(f"Seqno error: {e}")
                # If error, try getting from provider directly
                try:
                    seqno = await self.provider.get_seqno(self.address_raw)
                    print(f"📊 Seqno from provider: {seqno}")
                except:
                    # Last resort - assume 0
                    seqno = 0
                    print(f"📊 Seqno default: {seqno}")
            
            # Check balance
            balance = await self.get_balance()
            if balance < amount_ton:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Have: {balance} TON, Need: {amount_ton} TON'
                }
            
            print(f"💰 Balance: {balance} TON")
            print(f"📊 Seqno: {seqno}")
            
            # Create comment cell if needed
            message = None
            if comment:
                message = begin_cell() \
                    .store_uint(0, 32) \
                    .store_string(comment) \
                    .end_cell()
            
            # Create transfer
            tx = await self.wallet.transfer(
                destination=addr,
                amount=int(amount_ton * 1e9),
                seqno=seqno,
                body=message
            )
            
            # Send
            await self.wallet.send_transfer(tx)
            
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
            
            # Get seqno
            try:
                seqno = await self.wallet.get_seqno()
            except Exception:
                try:
                    seqno = await self.provider.get_seqno(self.address_raw)
                except:
                    seqno = 0
            
            # Check USDT balance
            usdt_balance = await self.get_usdt_balance()
            if usdt_balance < amount_usdt:
                return {
                    'success': False,
                    'error': f'Insufficient USDT. Have: {usdt_balance} USDT'
                }
            
            # Create comment
            message = None
            if comment:
                message = begin_cell() \
                    .store_uint(0, 32) \
                    .store_string(comment) \
                    .end_cell()
            
            tx = await self.wallet.transfer_jettons(
                jetton_master=Address(USDT_MASTER),
                destination=addr,
                amount=int(amount_usdt * 1e9),
                seqno=seqno,
                body=message
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
