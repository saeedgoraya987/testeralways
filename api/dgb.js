const DigiByte = require("digibyte");
const Request = require("request");

module.exports = async (req, res) => {
    // Enable CORS
    res.setHeader('Access-Control-Allow-Credentials', true);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,POST');
    res.setHeader('Access-Control-Allow-Headers', 'X-CSRF-Token, X-Requested-With, Accept, Content-Type');

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
        // GET: Generate wallet
        if (req.method === 'GET' && req.query.action === 'generate') {
            const privateKey = new DigiByte.PrivateKey();
            return res.status(200).json({
                privateKey: privateKey.toWIF(),
                address: privateKey.toAddress().toString()
            });
        }

        // GET: Check balance
        if (req.method === 'GET' && req.query.action === 'balance' && req.query.address) {
            const data = await makeRequest(`${explorerUrl}/api/addr/${req.query.address}`);
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                address: req.query.address,
                balance: data.balance,
                satoshis: data.balanceSat,
                usd: (data.balance * parseFloat(market[0].price_usd)).toFixed(2)
            });
        }

        // GET: Market price
        if (req.method === 'GET' && req.query.action === 'price') {
            const market = await makeRequest(`${marketUrl}/digibyte/`);
            return res.status(200).json({
                price_usd: market[0].price_usd,
                price_btc: market[0].price_btc,
                change_24h: market[0].percent_change_24h
            });
        }

        // GET: Send DGB (fast)
        if (req.method === 'GET' && req.query.action === 'send') {
            const { privateKey, destination, amount } = req.query;
            
            if (!privateKey || !destination || !amount) {
                return res.status(400).json({ error: 'Missing: privateKey, destination, amount' });
            }

            const satoshis = parseInt(amount);
            if (isNaN(satoshis) || satoshis <= 0) {
                return res.status(400).json({ error: 'Amount must be positive number' });
            }

            try {
                // Import private key
                const sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                const sourceAddress = sourcePrivateKey.toAddress();

                // Get UTXO
                const utxos = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}/utxo`);
                
                if (utxos.length === 0) {
                    return res.status(400).json({ error: 'No unspent transactions' });
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

                // Send
                const result = await makeRequest(`${explorerUrl}/api/tx/send`, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({ rawtx: transaction.serialize() })
                });

                return res.status(200).json({
                    success: true,
                    txid: result.txid,
                    sent: (satoshis / 100000000).toFixed(8),
                    changeAddress: changeAddress,
                    changePrivateKey: changePrivateKey.toWIF(),
                    warning: "SAVE changePrivateKey - it contains your remaining funds!"
                });

            } catch (error) {
                return res.status(500).json({ error: error.message });
            }
        }

        // POST: Send DGB (more secure)
        if (req.method === 'POST' && req.body.action === 'send') {
            const { privateKey, destination, amount } = req.body;
            
            if (!privateKey || !destination || !amount) {
                return res.status(400).json({ error: 'Missing: privateKey, destination, amount' });
            }

            const satoshis = parseInt(amount);
            if (isNaN(satoshis) || satoshis <= 0) {
                return res.status(400).json({ error: 'Amount must be positive number' });
            }

            try {
                const sourcePrivateKey = DigiByte.PrivateKey.fromWIF(privateKey);
                const sourceAddress = sourcePrivateKey.toAddress();
                const utxos = await makeRequest(`${explorerUrl}/api/addr/${sourceAddress}/utxo`);
                
                if (utxos.length === 0) {
                    return res.status(400).json({ error: 'No unspent transactions' });
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

                return res.status(200).json({
                    success: true,
                    txid: result.txid,
                    sent: (satoshis / 100000000).toFixed(8),
                    changeAddress: changeAddress,
                    changePrivateKey: changePrivateKey.toWIF(),
                    warning: "SAVE changePrivateKey - it contains your remaining funds!"
                });

            } catch (error) {
                return res.status(500).json({ error: error.message });
            }
        }

        // Default
        return res.status(200).json({
            name: 'DigiByte API',
            endpoints: {
                'GET ?action=generate': 'Create new wallet',
                'GET ?action=balance&address=ADDRESS': 'Check balance',
                'GET ?action=price': 'Get market price',
                'GET ?action=send&privateKey=KEY&destination=ADDR&amount=SATOSHIS': 'Send DGB (GET)',
                'POST {action:"send",privateKey, destination, amount}': 'Send DGB (POST)'
            },
            note: '1 DGB = 100,000,000 satoshis'
        });

    } catch (error) {
        return res.status(500).json({ error: error.message });
    }
};
