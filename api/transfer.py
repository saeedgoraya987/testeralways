import json
import hashlib
import requests
import time
import random
from typing import Dict, Any, Tuple
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def generate_transfer_id(tg_user_id: str) -> str:
    """Generate unique transfer ID matching PHP's uniqid + md5"""
    unique_str = f"{tg_user_id}_{time.time()}_{random.randint(0, 1000000)}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:20]

def validate_params(data: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
    """Validate input parameters"""
    errors = {}
    
    # Validate tgUserId
    tg_user_id = data.get('tgUserId', '')
    if not tg_user_id:
        errors['tgUserId'] = 'tgUserId is required'
    elif not str(tg_user_id).isdigit():
        errors['tgUserId'] = 'tgUserId must be a valid number'
    
    # Validate currency
    currency = data.get('currency', '').strip()
    if not currency:
        errors['currency'] = 'currency is required'
    
    # Validate amount
    amount = data.get('amount', '')
    if amount == '' or amount is None:
        errors['amount'] = 'amount is required'
    else:
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                errors['amount'] = 'amount must be a positive number'
        except (ValueError, TypeError):
            errors['amount'] = 'amount must be a valid number'
    
    # Validate apiKey
    api_key = data.get('apiKey', '').strip()
    if not api_key:
        errors['apiKey'] = 'apiKey is required'
    
    return len(errors) == 0, errors

@app.route('/api/transfer', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/transfer', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def transfer():
    """Main transfer endpoint - matches xRocket API exactly"""
    
    # Handle OPTIONS preflight
    if request.method == 'OPTIONS':
        response = Response('')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Rocket-Pay-Key'
        return response, 200
    
    # Set response headers
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
    
    # Extract parameters
    tg_user_id = params.get('tgUserId', '')
    currency = params.get('currency', '').strip()
    amount = params.get('amount', '')
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
        # Format errors to match xRocket API format
        error_list = []
        for field, message in errors.items():
            error_list.append({
                'property': field,
                'error': message
            })
        
        return jsonify({
            'success': False,
            'message': 'Validation failed',
            'errors': error_list
        }), 400, headers
    
    # Generate transfer ID if not provided
    transfer_id = params.get('transferId', '')
    if not transfer_id:
        transfer_id = generate_transfer_id(str(tg_user_id))
    
    # Build request body (matching xRocket API exactly)
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
        response = requests.post(
            'https://pay.xrocket.tg/app/transfer',
            json=body,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Rocket-Pay-Key': api_key,
            },
            timeout=10,
            verify=True
        )
        
        http_code = response.status_code
        
        # Parse response
        try:
            x_response = response.json()
        except json.JSONDecodeError:
            return jsonify({
                'success': False,
                'message': 'Invalid response from xRocket',
                'raw': response.text
            }), 502, headers
        
        # Handle response based on status code (matching xRocket API)
        if http_code == 201:
            # Success - 201 Created
            return jsonify({
                'success': True,
                'data': x_response.get('data', {})
            }), 201, headers
            
        elif http_code == 400:
            # Bad Request - Validation errors
            return jsonify({
                'success': False,
                'message': x_response.get('message', 'Validation failed'),
                'errors': x_response.get('errors', [])
            }), 400, headers
            
        elif http_code == 401:
            # Unauthorized
            return jsonify({
                'success': False,
                'message': x_response.get('message', 'Unauthorized')
            }), 401, headers
            
        elif http_code == 403:
            # Forbidden
            return jsonify({
                'success': False,
                'message': x_response.get('message', 'Forbidden')
            }), 403, headers
            
        elif http_code == 500:
            # Internal Server Error
            return jsonify({
                'success': False,
                'message': x_response.get('message', 'Internal server error')
            }), 500, headers
            
        else:
            # Handle other status codes
            if x_response.get('success') is True:
                return jsonify({
                    'success': True,
                    'data': x_response.get('data', {})
                }), http_code, headers
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
