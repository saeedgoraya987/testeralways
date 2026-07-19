const DigiByte = require("digibyte");
const axios = require("axios");

const EXPLORER = "https://digiexplorer.info";

module.exports = async (req, res) => {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    // Get action from query (GET) or body (POST)
    const action = req.query.action || req.body?.action;

    try {
        // ============================================
        // 1. GENERATE WALLET
        // ============================================
        if (action === "wallet") {
            const privateKey = new DigiByte.PrivateKey();
            return res.json({
                success: true,
                privateKey: privateKey.toWIF(),
                address: privateKey.toAddress().toString()
            });
        }

        // ============================================
        // 2. CHECK BALANCE
        // ============================================
        if (action === "balance") {
            const address = req.query.address || req.body?.address;
            
            if (!address) {
                return res.status(400).json({
                    success: false,
                    error: "Address is required"
                });
            }

            try {
                const { data } = await axios.get(
                    `${EXPLORER}/api/addr/${address}`
                );
                return res.json({
                    success: true,
                    ...data
                });
            } catch (error) {
                return res.status(404).json({
                    success: false,
                    error: "Address not found or invalid"
                });
            }
        }

        // ============================================
        // 3. GET UTXO
        // ============================================
        if (action === "utxo") {
            const address = req.query.address || req.body?.address;
            
            if (!address) {
                return res.status(400).json({
                    success: false,
                    error: "Address is required"
                });
            }

            try {
                const { data } = await axios.get(
                    `${EXPLORER}/api/addr/${address}/utxo`
                );
                return res.json({
                    success: true,
                    utxos: data,
                    total: data.length
                });
            } catch (error) {
                return res.status(404).json({
                    success: false,
                    error: "Address not found or invalid"
                });
            }
        }

        // ============================================
        // 4. GET MARKET PRICE
        // ============================================
        if (action === "price") {
            try {
                const { data } = await axios.get(
                    "https://api.coinmarketcap.com/v1/ticker/digibyte/"
                );
                return res.json({
                    success: true,
                    price_usd: data[0].price_usd,
                    price_btc: data[0].price_btc,
                    percent_change_24h: data[0].percent_change_24h,
                    market_cap: data[0].market_cap_usd,
                    volume_24h: data[0].volume_24h_usd
                });
            } catch (error) {
                return res.status(500).json({
                    success: false,
                    error: "Failed to fetch market price"
                });
            }
        }

        // ============================================
        // 5. SEND TRANSACTION
        // ============================================
        if (action === "send") {
            // Support both GET and POST
            const privateKey = req.query.privateKey || req.body?.privateKey;
            const to = req.query.to || req.body?.to;
            const amount = req.query.amount || req.body?.amount;

            // Validate inputs
            if (!privateKey) {
                return res.status(400).json({
                    success: false,
                    error: "Private key is required"
                });
            }

            if (!to) {
                return res.status(400).json({
                    success: false,
                    error: "Destination address is required"
                });
            }

            if (!amount) {
                return res.status(400).json({
                    success: false,
                    error: "Amount is required"
                });
            }

            const satoshis = parseInt(amount);
            if (isNaN(satoshis) || satoshis <= 0) {
                return res.status(400).json({
                    success: false,
                    error: "Amount must be a positive number in satoshis"
                });
            }

            if (!to.startsWith('D')) {
                return res.status(400).json({
                    success: false,
                    error: "Invalid destination address. Must start with 'D'"
                });
            }

            try {
                // Import private key
                let pk;
                try {
                    pk = DigiByte.PrivateKey.fromWIF(privateKey);
                } catch (e) {
                    return res.status(400).json({
                        success: false,
                        error: "Invalid private key format"
                    });
                }

                const from = pk.toAddress().toString();

                // Get balance first
                const balanceData = await axios.get(
                    `${EXPLORER}/api/addr/${from}`
                );
                
                if (balanceData.data.balanceSat < satoshis + 100000) {
                    return res.status(400).json({
                        success: false,
                        error: `Insufficient balance. Need ${(satoshis/100000000).toFixed(8)} DGB + fee. Available: ${balanceData.data.balance} DGB`
                    });
                }

                // Get UTXOs
                const { data: utxos } = await axios.get(
                    `${EXPLORER}/api/addr/${from}/utxo`
                );

                if (utxos.length === 0) {
                    return res.status(400).json({
                        success: false,
                        error: "No unspent transactions available"
                    });
                }

                // Create change address
                const changePrivateKey = new DigiByte.PrivateKey();
                const changeAddress = changePrivateKey.toAddress();

                // Build transaction
                const tx = new DigiByte.Transaction();
                utxos.forEach(u => tx.from(u));
                tx.to(to, satoshis);
                tx.change(changeAddress.toString());
                tx.sign(pk);

                // Send transaction
                const { data } = await axios.post(
                    `${EXPLORER}/api/tx/send`,
                    {
                        rawtx: tx.serialize()
                    }
                );

                // Get updated balance
                const updatedBalance = await axios.get(
                    `${EXPLORER}/api/addr/${from}`
                );

                return res.json({
                    success: true,
                    txid: data.txid,
                    sent_amount_dgb: (satoshis / 100000000).toFixed(8),
                    sent_amount_satoshis: satoshis,
                    destination: to,
                    change_address: changeAddress.toString(),
                    change_private_key: changePrivateKey.toWIF(),
                    updated_balance: {
                        dgb: updatedBalance.data.balance,
                        satoshis: updatedBalance.data.balanceSat
                    },
                    explorer_url: `https://digiexplorer.info/tx/${data.txid}`,
                    warning: "⚠️ SAVE THE change_private_key - It contains your remaining funds!"
                });

            } catch (error) {
                console.error("Send error:", error.message);
                return res.status(500).json({
                    success: false,
                    error: error.message || "Transaction failed"
                });
            }
        }

        // ============================================
        // 6. GET TRANSACTION DETAILS
        // ============================================
        if (action === "tx") {
            const txid = req.query.txid || req.body?.txid;
            
            if (!txid) {
                return res.status(400).json({
                    success: false,
                    error: "Transaction ID is required"
                });
            }

            try {
                const { data } = await axios.get(
                    `${EXPLORER}/api/tx/${txid}`
                );
                return res.json({
                    success: true,
                    transaction: data
                });
            } catch (error) {
                return res.status(404).json({
                    success: false,
                    error: "Transaction not found"
                });
            }
        }

        // ============================================
        // 7. DEFAULT: API Info
        // ============================================
        return res.json({
            name: "DigiByte API",
            version: "1.0.0",
            endpoints: {
                "GET ?action=wallet": "Generate new wallet",
                "GET ?action=balance&address=ADDR": "Check wallet balance",
                "GET ?action=utxo&address=ADDR": "Get UTXO for address",
                "GET ?action=price": "Get market price",
                "GET ?action=send&privateKey=KEY&to=ADDR&amount=SAT": "Send DGB (GET)",
                "POST with body": "Send DGB (POST) - body: {action:'send',privateKey,to,amount}",
                "GET ?action=tx&txid=TXID": "Get transaction details"
            },
            notes: {
                satoshis: "1 DGB = 100,000,000 satoshis",
                fee: "Transaction fee is approximately 0.001 DGB",
                security: "Never share your private key publicly"
            }
        });

    } catch (error) {
        console.error("API Error:", error);
        return res.status(500).json({
            success: false,
            error: error.message || "Internal server error"
        });
    }
};
