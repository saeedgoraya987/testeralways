import json
import hashlib
import requests
import time
import random
from typing import Dict, Any, Tuple, Optional
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def generate_transfer_id(tg_user_id: str) -> str:
    """Generate unique transfer ID matching PHP's uniqid + md5"""
    # PHP's uniqid($prefix, true) generates unique string with more entropy
    unique_str = f"{tg_user_id}_{time.time()}_{random.randint(0, 1000000)}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:20]

def validate_params(data: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
    """Validate input parameters"""
    errors = {}
    
    # Validate tgUserId
    tg_user_id = data.get('tgUserId', '').strip()
    if not tg_user_id:
        errors['tgUserId'] = 'tgUserId is required'
    elif not tg_user_id.isdigit():
        errors['tgUserId'] = 'tgUserId must be a valid number'
    
    # Validate currency
    currency = data.get('currency', '').strip()
    if not currency:
        errors['currency'] = 'currency is required'
    
    # Validate amount
    amount = data.get('amount', '').strip()
    if not amount:
        errors['amount'] = 'amount is required'
    else:
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                errors['amount'] = 'amount must be a positive number'
        except ValueError:
            errors['amount'] = 'amount must be a valid number'
    
    # Validate apiKey
    api_key = data.get('apiKey', '').strip()
    if not api_key:
        errors['apiKey'] = 'apiKey is required'
    
    return len(errors) == 0, errors

@app.route('/api/transfer', methods=['GET', 'POST', 'OPTIONS'])
def transfer():
    """Main transfer endpoint - matches PHP functionality exactly"""
    
    # Handle OPTIONS preflight
    if request.method == 'OPTIONS':
        response = Response('')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Rocket-Pay-Key'
        return response, 200
    
    # Set response headers (matching PHP)
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'X-Content-Type-Options': 'nosniff',
        'Access-Control-Allow-Origin': '*'
    }
    
    # Get parameters from GET or POST
    if request.method == 'GET':
        params = request.args.to_dict()
    else:  # POST
        if request.is_json:
            params = request.get_json() or {}
        else:
            return jsonify({
                'success': False,
                'message': 'Content-Type must be application/json'
            }), 400, headers
    
    # Extract parameters (matching PHP's $_GET)
    tg_user_id = params.get('tgUserId', '').strip()
    currency = params.get('currency', '').strip()
    amount = params.get('amount', '').strip()
    api_key = params.get('apiKey', '').strip()
    description = params.get('description', '').strip()
    
    # Validate parameters
    data = {
        'tgUserId': tg_user_id,
        'currency': currency,
        'amount': amount,
        'apiKey': api_key,
        'description': description
    }
    
    is_valid, errors = validate_params(data)
    if not is_valid:
        return jsonify({
            'success': False,
            'message': 'Validation failed',
            'errors': errors
        }), 400, headers
    
    # Generate transfer ID
    transfer_id = generate_transfer_id(tg_user_id)
    
    # Build request body
    body = {
        'tgUserId': int(tg_user_id),
        'currency': currency.upper(),
        'amount': float(amount),
        'transferId': transfer_id,
    }
    
    if description:
        body['description'] = description
    
    # Make request to xRocket
    try:
        # cURL equivalent - optimized
        response = requests.post(
            'https://pay.xrocket.tg/app/transfer',
            json=body,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Rocket-Pay-Key': api_key,
            },
            timeout=10,  # CURLOPT_TIMEOUT
            verify=True,  # CURLOPT_SSL_VERIFYPEER
            # CURLOPT_ENCODING: 'gzip' - handled automatically by requests
        )
        
        http_code = response.status_code
        raw = response.text
        
        # Parse response
        try:
            x_response = response.json()
        except json.JSONDecodeError:
            return jsonify({
                'success': False,
                'message': 'Invalid response from xRocket',
                'raw': raw
            }), 502, headers
        
        # Final response - matching PHP logic exactly
        if x_response.get('success') is True:
            return jsonify({
                'success': True,
                'message': 'Transfer successful',
                'transferId': transfer_id,
                'data': x_response.get('data', {})
            }), 200, headers
        else:
            return jsonify({
                'success': False,
                'message': x_response.get('message', 'Transfer failed'),
                'errors': x_response.get('errors', [])
            }), http_code or 400, headers
    
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Request timeout'
        }), 504, headers
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'Connection error'
        }), 500, headers
    except requests.exceptions.RequestException as e:
        return jsonify({
            'success': False,
            'message': 'Request failed',
            'error': str(e)
        }), 500, headers

# For Vercel serverless
def handler(event, context):
    """Vercel serverless handler"""
    return app(event, context)

# Local development
if __name__ == '__main__':
    app.run(debug=True, port=3000)
