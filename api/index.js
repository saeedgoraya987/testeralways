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
                address: privateKey.toAddress().toString(),
                warning: "⚠️ SAVE YOUR PRIVATE KEY SECURELY!"
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
                    address: address,
                    balance: data.balance || 0,
                    satoshis: data.balanceSat || 0,
                    transactions: data.transactions ? data.transactions.length : 0
                });
            } catch (error) {
                return res.json({
                    success: true,
                    address: address,
                    balance: 0,
                    satoshis: 0,
                    transactions: 0,
                    message: "Address exists but has no transactions"
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
                
                // Ensure data is an array
                const utxos = Array.isArray(data) ? data : [];
                
                const totalAmount = utxos.reduce((sum, utxo) => sum + (utxo.amount || 0), 0);
                
                return res.json({
                    success: true,
                    address: address,
                    utxos: utxos,
                    total_utxos: utxos.length,
                    total_amount: totalAmount,
                    total_satoshis: Math.round(totalAmount * 100000000)
                });
            } catch (error) {
                return res.json({
                    success: true,
                    address: address,
                    utxos: [],
                    total_utxos: 0,
                    total_amount: 0,
                    total_satoshis: 0,
                    message: "No UTXOs found"
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
        // 5. SEND DGB - FIXED
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

                // Get UTXOs
                let response;
                try {
                    response = await axios.get(
                        `${EXPLORER}/api/addr/${from}/utxo`,
                        { timeout: 10000 }
                    );
                } catch (e) {
                    return res.status(400).json({
                        success: false,
                        error: "Unable to fetch UTXOs. Address may have no funds."
                    });
                }

                // Ensure utxos is an array
                const utxos = Array.isArray(response.data) ? response.data : [];
                
                if (utxos.length === 0) {
                    return res.status(400).json({
                        success: false,
                        error: "No unspent transactions available. Address has no funds to send."
                    });
                }

                // Calculate total balance
                const totalBalance = utxos.reduce((sum, u) => sum + (u.amount || 0), 0);
                const fee = 0.001; // DGB
                const feeSatoshis = Math.round(fee * 100000000);

                if (totalBalance * 100000000 < satoshis + feeSatoshis) {
                    return res.status(400).json({
                        success: false,
                        error: `Insufficient balance. Need ${(satoshis/100000000).toFixed(8)} DGB + fee. Available: ${totalBalance.toFixed(8)} DGB`
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
                let result;
                try {
                    const sendResponse = await axios.post(
                        `${EXPLORER}/api/tx/send`,
                        {
                            rawtx: tx.serialize()
                        },
                        { timeout: 15000 }
                    );
                    result = sendResponse.data;
                } catch (e) {
                    return res.status(500).json({
                        success: false,
                        error: "Failed to send transaction: " + (e.response?.data?.message || e.message)
                    });
                }

                // Get updated balance
                let updatedBalance = 0;
                try {
                    const balanceData = await axios.get(
                        `${EXPLORER}/api/addr/${from}`,
                        { timeout: 5000 }
                    );
                    updatedBalance = balanceData.data.balance || 0;
                } catch (e) {}

                return res.json({
                    success: true,
                    transaction: {
                        txid: result.txid,
                        sent_amount_dgb: (satoshis / 100000000).toFixed(8),
                        sent_amount_satoshis: satoshis,
                        destination: to,
                        fee_dgb: fee.toFixed(3),
                        fee_satoshis: feeSatoshis,
                        from_address: from
                    },
                    updated_balance: {
                        dgb: updatedBalance,
                        satoshis: Math.round(updatedBalance * 100000000)
                    },
                    change_address: changeAddress.toString(),
                    change_private_key: changePrivateKey.toWIF(),
                    explorer_url: `https://digiexplorer.info/tx/${result.txid}`,
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
            version: "2.0.0",
            description: "Complete DigiByte cryptocurrency management API",
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
                security: "⚠️ Never share your private key publicly!",
                change_key: "⚠️ Always save the change_private_key from send responses"
            },
            examples: {
                generate: "/api/dgb?action=wallet",
                balance: "/api/dgb?action=balance&address=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm",
                send: "/api/dgb?action=send&privateKey=L1xxxxx&to=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm&amount=1000000"
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
