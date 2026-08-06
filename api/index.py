from http.server import BaseHTTPRequestHandler
import json
import asyncio
import requests
import os
from pytoniq import WalletV4R2
from pytoniq_core import Address

class TONWallet:
    """TON Wallet handler"""
    
    def __init__(self):
        self.recovery_phrase = os.getenv('TON_RECOVERY_PHRASE')
        
        if not self.recovery_phrase:
            raise ValueError("TON_RECOVERY_PHRASE not set in environment")
        
        mnemonic_list = self.recovery_phrase.split()
        self.wallet = WalletV4R2.from_mnemonic(mnemonic_list, workchain=0)
        self.address = self.wallet.address.to_str()
    
    async def get_balance(self):
        """Get TON balance"""
        try:
            url = "https://toncenter.com/api/v2/getAddressBalance"
            params = {'address': self.address}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                balance_nano = int(data.get('result', 0))
                return balance_nano / 1e9
            return 0
        except:
            return 0
    
    async def get_usdt_balance(self):
        """Get USDT balance"""
        USDT_MASTER = "EQCxE6mUtQJKFnGfaROHKOa1gaZ1Y5jgDsuRAtJ53cV-ZjvD"
        
        try:
            url = "https://toncenter.com/api/v2/getAccountJettonBalance"
            params = {
                'address': self.address,
                'jetton_master': USDT_MASTER
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})
                balance = int(result.get('balance', 0))
                return balance / 1e9
            return 0
        except:
            return 0
    
    async def send_ton(self, to_address, amount_ton, comment=""):
        """Send TON"""
        try:
            Address(to_address)
            
            seqno = await self.wallet.get_seqno()
            
            tx = await self.wallet.transfer(
                destination=Address(to_address),
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
                'from': self.address
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
            Address(to_address)
            
            seqno = await self.wallet.get_seqno()
            
            tx = await self.wallet.transfer_jettons(
                jetton_master=Address(USDT_MASTER),
                destination=Address(to_address),
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
                'currency': 'USDT'
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
# Vercel Handler
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
                'GET /api/balance': 'Check wallet balance',
                'GET /api/wallet': 'Get wallet info',
                'POST /api/send-ton': 'Send TON',
                'POST /api/send-usdt': 'Send USDT',
                'POST /api/withdrawal-link': 'Create withdrawal link'
            },
            'docs': 'https://github.com/your-repo'
        }
        self.send_success_response(response)
    
    def handle_balance(self):
        """Handle balance check"""
        try:
            wallet = TONWallet()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            ton_balance = loop.run_until_complete(wallet.get_balance())
            usdt_balance = loop.run_until_complete(wallet.get_usdt_balance())
            
            response = {
                'success': True,
                'address': wallet.address,
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
            wallet = TONWallet()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            ton_balance = loop.run_until_complete(wallet.get_balance())
            
            response = {
                'success': True,
                'address': wallet.address,
                'explorer_url': f'https://tonscan.org/address/{wallet.address}',
                'balance': ton_balance,
                'network': 'mainnet'
            }
            self.send_success_response(response)
            
        except Exception as e:
            self.send_error_response(500, str(e))
    
    def handle_send_ton(self):
        """Handle sending TON"""
        try:
            # Parse request body
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
            
            wallet = TONWallet()
            
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            # Check balance
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
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
            
            wallet = TONWallet()
            
            if not wallet.validate_address(to_address):
                self.send_error_response(400, 'Invalid recipient address')
                return
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
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
            
            # Call xRocket API
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
    print(f'   GET  /api/balance')
    print(f'   GET  /api/wallet')
    print(f'   POST /api/send-ton')
    print(f'   POST /api/send-usdt')
    print(f'   POST /api/withdrawal-link')
    server.serve_forever()
