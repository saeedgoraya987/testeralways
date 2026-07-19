const DigiByte = require("digibyte");
const Request = require("request");

module.exports = async (req, res) => {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,POST');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.status(200).end();
        return;
    }

    const explorerUrl = "https://digiexplorer.info";
    const marketUrl = "https://api.coinmarketcap.com/v1/ticker";

    const makeRequest = (url, options = {}) => {
        return new Promise((resolve, reject) => {
            Request({ url, ...options }, (error, response, body) => {
                if (error) reject(error);
                try {
                    resolve(JSON.parse(body));
                } catch (e) {
                    resolve(body);
                }
            });
        });
    };

    try {
        const query = req.query || {};
        const { action, address, privateKey, destination, amount } = query;

        // ============================================
        // 1. GENERATE WALLET
        // ============================================
        if (action === 'generate') {
            const privateKey = new DigiByte.PrivateKey();
            return res.status(200).json({
                success: true,
                privateKey: privateKey.toWIF(),
                address: privateKey.toAddress().toString(),
                warning: "⚠️ SAVE YOUR PRIVATE KEY SECURELY! Anyone with this key can access your funds."
            });
        }

        // ============================================
        // 2. CHECK BALANCE
        // ============================================
        if (action === 'balance' && address) {
            const data = await makeRequest(`${explorerUrl}/api/addr/${address}`);
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                success: true,
                address: address,
                balance: data.balance,
                satoshis: data.balanceSat,
                usd_value: (data.balance * parseFloat(market[0].price_usd)).toFixed(2),
                total_received: data.totalReceived,
                total_sent: data.totalSent,
                transactions: data.transactions ? data.transactions.length : 0,
                unconfirmed: data.unconfirmedBalance || 0
            });
        }

        // ============================================
        // 3. GET MARKET PRICE
        // ============================================
        if (action === 'price') {
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                success: true,
                price_usd: market[0].price_usd,
                price_btc: market[0].price_btc,
                percent_change_1h: market[0].percent_change_1h,
                percent_change_24h: market[0].percent_change_24h,
                percent_change_7d: market[0].percent_change_7d,
                market_cap: market[0].market_cap_usd,
                volume_24h: market[0].volume_24h_usd,
                circulating_supply: market[0].available_supply,
                total_supply: market[0].total_supply,
                max_supply: market[0].max_supply
            });
        }

        // ============================================
        // 4. GET UTXO
        // ============================================
        if (action === 'utxo' && address) {
            const utxos = await makeRequest(`${explorerUrl}/api/addr/${address}/utxo`);
            const totalAmount = utxos.reduce((sum, utxo) => sum + utxo.amount, 0);
            return res.status(200).json({
                success: true,
                address: address,
                utxos: utxos,
                total_utxos: utxos.length,
                total_amount: totalAmount,
                total_satoshis: Math.round(totalAmount * 100000000)
            });
        }

        // ============================================
        // 5. SEND DGB (GET METHOD)
        // ============================================
        if (action === 'send') {
            if (!privateKey || !destination || !amount) {
                return res.status(400).json({
                    success: false,
                    error: 'Missing required parameters: privateKey, destination, amount'
                });
            }

            const satoshis = parseInt(amount);
            if (isNaN(satoshis) || satoshis <= 0) {
                return res.status(400).json({
                    success: false,
                    error: 'Amount must be a positive number in satoshis'
                });
            }

            if (!destination.startsWith('D')) {
                return res.status(400).json({
                    success: false,
                    error: 'Invalid destination address. Must start with "D"'
                });
            }

            try {
                // Validate private key
                let sourcePrivateKey;
                try {
                    sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                } catch (e) {
                    return res.status(400).json({
                        success: false,
                        error: 'Invalid private key format'
                    });
                }

                const sourceAddress = sourcePrivateKey.toAddress();
                
                // Check balance first
                const balanceData = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}`);
                if (balanceData.balanceSat < satoshis + 100000) { // 0.001 DGB fee buffer
                    return res.status(400).json({
                        success: false,
                        error: `Insufficient balance. Need ${(satoshis/100000000).toFixed(8)} DGB + fee. Available: ${balanceData.balance} DGB`
                    });
                }

                // Get UTXOs
                const utxos = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}/utxo`);
                
                if (utxos.length === 0) {
                    return res.status(400).json({
                        success: false,
                        error: 'No unspent transactions available for this address'
                    });
                }

                // Create change address
                const changePrivateKey = new DigiByte.PrivateKey();
                const changeAddress = changePrivateKey.toAddress();

                // Build transaction
                const transaction = new DigiByte.Transaction();
                utxos.forEach(utxo => transaction.from(utxo));
                transaction.to(destination, satoshis);
                transaction.change(changeAddress);
                transaction.sign(sourcePrivateKey);

                // Send transaction
                const result = await makeRequest(`${explorerUrl}/api/tx/send`, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({ rawtx: transaction.serialize() })
                });

                // Get updated balance
                const updatedBalance = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}`);
                const market = await makeRequest(`${marketUrl}/digibyte/`);

                return res.status(200).json({
                    success: true,
                    transaction: {
                        txid: result.txid,
                        sent_amount_dgb: (satoshis / 100000000).toFixed(8),
                        sent_amount_satoshis: satoshis,
                        destination: destination,
                        change_address: changeAddress.toString(),
                        change_private_key: changePrivateKey.toWIF()
                    },
                    updated_balance: {
                        dgb: updatedBalance.balance,
                        satoshis: updatedBalance.balanceSat,
                        usd: (updatedBalance.balance * parseFloat(market[0].price_usd)).toFixed(2)
                    },
                    explorer_url: `https://digiexplorer.info/tx/${result.txid}`,
                    warning: "⚠️ IMPORTANT: SAVE THE change_private_key! It contains your remaining funds."
                });

            } catch (error) {
                return res.status(500).json({
                    success: false,
                    error: error.message || 'Transaction failed'
                });
            }
        }

        // ============================================
        // 6. GET TRANSACTION DETAILS
        // ============================================
        if (action === 'tx' && query.txid) {
            const txData = await makeRequest(`${explorerUrl}/api/tx/${query.txid}`);
            return res.status(200).json({
                success: true,
                transaction: txData
            });
        }

        // ============================================
        // 7. GET ADDRESS TRANSACTIONS
        // ============================================
        if (action === 'transactions' && address) {
            const data = await makeRequest(`${explorerUrl}/api/addr/${address}`);
            return res.status(200).json({
                success: true,
                address: address,
                transactions: data.transactions || [],
                total: data.transactions ? data.transactions.length : 0
            });
        }

        // ============================================
        // 8. POST: SEND DGB (More Secure)
        // ============================================
        if (req.method === 'POST') {
            const body = req.body || {};
            
            if (body.action === 'send') {
                const { privateKey, destination, amount } = body;
                
                if (!privateKey || !destination || !amount) {
                    return res.status(400).json({
                        success: false,
                        error: 'Missing required fields: privateKey, destination, amount'
                    });
                }

                const satoshis = parseInt(amount);
                if (isNaN(satoshis) || satoshis <= 0) {
                    return res.status(400).json({
                        success: false,
                        error: 'Amount must be a positive number in satoshis'
                    });
                }

                if (!destination.startsWith('D')) {
                    return res.status(400).json({
                        success: false,
                        error: 'Invalid destination address. Must start with "D"'
                    });
                }

                try {
                    let sourcePrivateKey;
                    try {
                        sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                    } catch (e) {
                        return res.status(400).json({
                            success: false,
                            error: 'Invalid private key format'
                        });
                    }

                    const sourceAddress = sourcePrivateKey.toAddress();
                    
                    const balanceData = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}`);
                    if (balanceData.balanceSat < satoshis + 100000) {
                        return res.status(400).json({
                            success: false,
                            error: `Insufficient balance. Need ${(satoshis/100000000).toFixed(8)} DGB + fee. Available: ${balanceData.balance} DGB`
                        });
                    }

                    const utxos = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}/utxo`);
                    
                    if (utxos.length === 0) {
                        return res.status(400).json({
                            success: false,
                            error: 'No unspent transactions available'
                        });
                    }

                    const changePrivateKey = new DigiByte.PrivateKey();
                    const changeAddress = changePrivateKey.toAddress();

                    const transaction = new DigiByte.Transaction();
                    utxos.forEach(utxo => transaction.from(utxo));
                    transaction.to(destination, satoshis);
                    transaction.change(changeAddress);
                    transaction.sign(sourcePrivateKey);

                    const result = await makeRequest(`${explorerUrl}/api/tx/send`, {
                        method: 'POST',
                        headers: { 'content-type': 'application/json' },
                        body: JSON.stringify({ rawtx: transaction.serialize() })
                    });

                    const updatedBalance = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}`);
                    const market = await makeRequest(`${marketUrl}/digibyte/`);

                    return res.status(200).json({
                        success: true,
                        transaction: {
                            txid: result.txid,
                            sent_amount_dgb: (satoshis / 100000000).toFixed(8),
                            sent_amount_satoshis: satoshis,
                            destination: destination,
                            change_address: changeAddress.toString(),
                            change_private_key: changePrivateKey.toWIF()
                        },
                        updated_balance: {
                            dgb: updatedBalance.balance,
                            satoshis: updatedBalance.balanceSat,
                            usd: (updatedBalance.balance * parseFloat(market[0].price_usd)).toFixed(2)
                        },
                        explorer_url: `https://digiexplorer.info/tx/${result.txid}`,
                        warning: "⚠️ IMPORTANT: SAVE THE change_private_key! It contains your remaining funds."
                    });

                } catch (error) {
                    return res.status(500).json({
                        success: false,
                        error: error.message || 'Transaction failed'
                    });
                }
            }

            return res.status(400).json({
                success: false,
                error: 'Invalid action for POST request'
            });
        }

        // ============================================
        // 9. DEFAULT: API Information
        // ============================================
        return res.status(200).json({
            name: 'DigiByte API',
            version: '1.0.0',
            description: 'Complete DigiByte cryptocurrency management API',
            base_url: 'https://testeralways.vercel.app/api/dgb',
            endpoints: {
                'GET ?action=generate': {
                    description: 'Generate a new wallet',
                    example: '/api/dgb?action=generate'
                },
                'GET ?action=balance&address=ADDRESS': {
                    description: 'Get wallet balance and info',
                    example: '/api/dgb?action=balance&address=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm'
                },
                'GET ?action=price': {
                    description: 'Get current market price',
                    example: '/api/dgb?action=price'
                },
                'GET ?action=utxo&address=ADDRESS': {
                    description: 'Get unspent transaction outputs',
                    example: '/api/dgb?action=utxo&address=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm'
                },
                'GET ?action=send&privateKey=KEY&destination=ADDR&amount=SAT': {
                    description: 'Send DGB (GET method)',
                    example: '/api/dgb?action=send&privateKey=L1xxxxx&destination=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm&amount=1000000'
                },
                'POST /api/dgb': {
                    description: 'Send DGB (POST method - more secure)',
                    example: '{"action":"send","privateKey":"L1xxxxx","destination":"D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm","amount":1000000}'
                },
                'GET ?action=tx&txid=TXID': {
                    description: 'Get transaction details',
                    example: '/api/dgb?action=tx&txid=a72537b428cf35c11a309eb09c7dabae2af4fa0a3849a34ef64f986baf80eb8a'
                },
                'GET ?action=transactions&address=ADDRESS': {
                    description: 'Get all transactions for address',
                    example: '/api/dgb?action=transactions&address=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm'
                }
            },
            notes: {
                satoshis: '1 DGB = 100,000,000 satoshis',
                fee: 'Transaction fee is approximately 0.001 DGB',
                security: '⚠️ Never share your private key publicly!',
                change_key: '⚠️ Always save the change_private_key from send responses',
                network: 'DigiByte mainnet',
                explorer: 'https://digiexplorer.info'
            }
        });

    } catch (error) {
        console.error('API Error:', error);
        return res.status(500).json({
            success: false,
            error: error.message || 'Internal server error',
            stack: process.env.NODE_ENV === 'development' ? error.stack : undefined
        });
    }
};
