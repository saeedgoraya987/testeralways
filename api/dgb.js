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

        // 1. GENERATE WALLET
        if (action === 'generate') {
            const privateKey = new DigiByte.PrivateKey();
            return res.status(200).json({
                success: true,
                privateKey: privateKey.toWIF(),
                address: privateKey.toAddress().toString(),
                warning: "⚠️ SAVE YOUR PRIVATE KEY SECURELY!"
            });
        }

        // 2. CHECK BALANCE
        if (action === 'balance' && address) {
            const data = await makeRequest(`${explorerUrl}/api/addr/${address}`);
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                success: true,
                address: address,
                balance: data.balance,
                satoshis: data.balanceSat,
                usd_value: (data.balance * parseFloat(market[0].price_usd)).toFixed(2),
                transactions: data.transactions ? data.transactions.length : 0
            });
        }

        // 3. MARKET PRICE
        if (action === 'price') {
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                success: true,
                price_usd: market[0].price_usd,
                price_btc: market[0].price_btc,
                percent_change_24h: market[0].percent_change_24h,
                market_cap: market[0].market_cap_usd,
                volume_24h: market[0].volume_24h_usd
            });
        }

        // 4. GET UTXO
        if (action === 'utxo' && address) {
            const utxos = await makeRequest(`${explorerUrl}/api/addr/${address}/utxo`);
            return res.status(200).json({
                success: true,
                address: address,
                utxos: utxos,
                total: utxos.length
            });
        }

        // 5. SEND DGB (GET)
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
                    error: 'Invalid destination address format'
                });
            }

            try {
                const sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                const sourceAddress = sourcePrivateKey.toAddress();
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
                        change_address: changeAddress,
                        change_private_key: changePrivateKey.toWIF()
                    },
                    updated_balance: {
                        dgb: updatedBalance.balance,
                        satoshis: updatedBalance.balanceSat,
                        usd: (updatedBalance.balance * parseFloat(market[0].price_usd)).toFixed(2)
                    },
                    warning: "⚠️ SAVE THE change_private_key - It contains your remaining funds!"
                });

            } catch (error) {
                return res.status(500).json({
                    success: false,
                    error: error.message
                });
            }
        }

        // 6. POST: Send DGB
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
                        error: 'Invalid destination address format'
                    });
                }

                try {
                    const sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                    const sourceAddress = sourcePrivateKey.toAddress();
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
                            change_address: changeAddress,
                            change_private_key: changePrivateKey.toWIF()
                        },
                        updated_balance: {
                            dgb: updatedBalance.balance,
                            satoshis: updatedBalance.balanceSat,
                            usd: (updatedBalance.balance * parseFloat(market[0].price_usd)).toFixed(2)
                        },
                        warning: "⚠️ SAVE THE change_private_key - It contains your remaining funds!"
                    });

                } catch (error) {
                    return res.status(500).json({
                        success: false,
                        error: error.message
                    });
                }
            }

            return res.status(400).json({
                success: false,
                error: 'Invalid action'
            });
        }

        // Default: API Info
        return res.status(200).json({
            name: 'DigiByte API',
            version: '1.0.0',
            description: 'DigiByte cryptocurrency management API',
            endpoints: {
                'GET ?action=generate': 'Generate new wallet',
                'GET ?action=balance&address=ADDR': 'Check wallet balance',
                'GET ?action=price': 'Get current market price',
                'GET ?action=utxo&address=ADDR': 'Get UTXO for address',
                'GET ?action=send&privateKey=KEY&destination=ADDR&amount=SAT': 'Send DGB (GET)',
                'POST /api/dgb': 'Send DGB (POST) - body: {action:"send",privateKey,destination,amount}'
            },
            notes: {
                satoshis: '1 DGB = 100,000,000 satoshis',
                fee: 'Transaction fee is approximately 0.001 DGB',
                security: 'Never share your private key publicly'
            }
        });

    } catch (error) {
        return res.status(500).json({
            success: false,
            error: error.message || 'Internal server error'
        });
    }
};
