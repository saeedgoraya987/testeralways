const DigiByte = require("digibyte");
const axios = require("axios");

const EXPLORER = "https://digiexplorer.info";
const CMC_KEYLESS = "https://pro-api.coinmarketcap.com/public-api";

// DGB CoinMarketCap ID is 109 (not 1559)
const DGB_CMC_ID = 109;

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
                
                // Get price from CoinMarketCap keyless API
                let usdValue = 0;
                let priceData = null;
                try {
                    const priceResponse = await axios.get(
                        `${CMC_KEYLESS}/v1/simple/price?ids=${DGB_CMC_ID}&convert=USD`,
                        { timeout: 5000 }
                    );
                    const dgbData = priceResponse.data.data?.[String(DGB_CMC_ID)];
                    if (dgbData && dgbData.quote?.USD) {
                        priceData = dgbData.quote.USD;
                        usdValue = (data.balance || 0) * priceData.price;
                    }
                } catch (e) {
                    console.log("Price fetch error:", e.message);
                }

                return res.json({
                    success: true,
                    address: address,
                    balance: data.balance || 0,
                    satoshis: data.balanceSat || 0,
                    usd_value: usdValue.toFixed(2),
                    price_usd: priceData ? priceData.price : null,
                    percent_change_24h: priceData ? priceData.percent_change_24h : null,
                    transactions: data.transactions ? data.transactions.length : 0
                });
            } catch (error) {
                return res.json({
                    success: true,
                    address: address,
                    balance: 0,
                    satoshis: 0,
                    usd_value: "0.00",
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
        // 4. GET MARKET PRICE - FIXED with correct ID
        // ============================================
        if (action === "price") {
            let errorMessages = [];
            
            // Try Method 1: Keyless API with correct DGB ID (109)
            try {
                console.log(`Fetching DGB price with ID: ${DGB_CMC_ID}`);
                const response = await axios.get(
                    `${CMC_KEYLESS}/v1/simple/price?ids=${DGB_CMC_ID}&convert=USD`,
                    { 
                        timeout: 10000,
                        headers: {
                            'Accept': 'application/json'
                        }
                    }
                );
                
                console.log("Keyless API Response:", JSON.stringify(response.data, null, 2));
                
                // Check if we got valid data
                if (response.data && response.data.data && response.data.data[String(DGB_CMC_ID)]) {
                    const dgbData = response.data.data[String(DGB_CMC_ID)];
                    if (dgbData.quote && dgbData.quote.USD) {
                        const usdData = dgbData.quote.USD;
                        return res.json({
                            success: true,
                            price_usd: usdData.price,
                            price_btc: usdData.price_btc || null,
                            percent_change_1h: usdData.percent_change_1h || 0,
                            percent_change_24h: usdData.percent_change_24h || 0,
                            percent_change_7d: usdData.percent_change_7d || 0,
                            percent_change_30d: usdData.percent_change_30d || 0,
                            market_cap: usdData.market_cap || 0,
                            volume_24h: usdData.volume_24h || 0,
                            last_updated: usdData.last_updated,
                            symbol: dgbData.symbol || "DGB",
                            name: dgbData.name || "DigiByte",
                            cmc_id: DGB_CMC_ID,
                            source: "CoinMarketCap Keyless API"
                        });
                    }
                }
                errorMessages.push("Keyless API returned no data for DGB");
            } catch (e) {
                console.error("Keyless API error:", e.message);
                errorMessages.push(`Keyless API: ${e.message}`);
            }

            // Try Method 2: Free API (no key required)
            try {
                const response = await axios.get(
                    "https://api.coinmarketcap.com/v1/ticker/digibyte/",
                    { timeout: 10000 }
                );
                
                if (response.data && response.data[0]) {
                    const data = response.data[0];
                    return res.json({
                        success: true,
                        price_usd: parseFloat(data.price_usd),
                        price_btc: parseFloat(data.price_btc),
                        percent_change_1h: parseFloat(data.percent_change_1h) || 0,
                        percent_change_24h: parseFloat(data.percent_change_24h) || 0,
                        percent_change_7d: parseFloat(data.percent_change_7d) || 0,
                        market_cap: parseFloat(data.market_cap_usd) || 0,
                        volume_24h: parseFloat(data.volume_24h_usd) || 0,
                        symbol: data.symbol || "DGB",
                        name: data.name || "DigiByte",
                        source: "CoinMarketCap Free API"
                    });
                }
                errorMessages.push("Free API returned no data");
            } catch (e) {
                errorMessages.push(`Free API: ${e.message}`);
            }

            // Try Method 3: Alternative API
            try {
                const response = await axios.get(
                    "https://min-api.cryptocompare.com/data/price?fsym=DGB&tsyms=USD,BTC",
                    { timeout: 10000 }
                );
                
                if (response.data && response.data.USD) {
                    return res.json({
                        success: true,
                        price_usd: response.data.USD,
                        price_btc: response.data.BTC || null,
                        source: "CryptoCompare API",
                        note: "Using alternative price source"
                    });
                }
                errorMessages.push("CryptoCompare returned no data");
            } catch (e) {
                errorMessages.push(`CryptoCompare: ${e.message}`);
            }

            // If all methods failed
            return res.status(500).json({
                success: false,
                error: "Failed to fetch DGB price from all sources",
                details: errorMessages,
                note: "Try using the balance endpoint which includes price data"
            });
        }

        // ============================================
        // 5. GET CRYPTO INFO (DGB details)
        // ============================================
        if (action === "info") {
            try {
                // Get DGB info from CoinMarketCap
                const response = await axios.get(
                    `${CMC_KEYLESS}/v2/cryptocurrency/info?id=${DGB_CMC_ID}`,
                    { timeout: 10000 }
                );
                
                const dgbData = response.data.data[String(DGB_CMC_ID)];
                
                return res.json({
                    success: true,
                    id: dgbData.id,
                    name: dgbData.name,
                    symbol: dgbData.symbol,
                    slug: dgbData.slug,
                    rank: dgbData.rank,
                    description: dgbData.description,
                    logo: dgbData.logo,
                    tags: dgbData.tags,
                    date_added: dgbData.date_added,
                    website: dgbData.website,
                    explorer: dgbData.explorer,
                    twitter: dgbData.twitter,
                    reddit: dgbData.reddit,
                    technology: dgbData.technology,
                    market_data: dgbData.market_data
                });
            } catch (error) {
                return res.status(500).json({
                    success: false,
                    error: "Failed to fetch DGB info: " + error.message
                });
            }
        }

        // ============================================
        // 6. SEND DGB
        // ============================================
        if (action === "send") {
            const privateKey = req.query.privateKey || req.body?.privateKey;
            const to = req.query.to || req.body?.to;
            const amount = req.query.amount || req.body?.amount;

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

                const utxos = Array.isArray(response.data) ? response.data : [];
                
                if (utxos.length === 0) {
                    return res.status(400).json({
                        success: false,
                        error: "No unspent transactions available. Address has no funds to send."
                    });
                }

                const totalBalance = utxos.reduce((sum, u) => sum + (u.amount || 0), 0);
                const fee = 0.001;
                const feeSatoshis = Math.round(fee * 100000000);

                if (totalBalance * 100000000 < satoshis + feeSatoshis) {
                    return res.status(400).json({
                        success: false,
                        error: `Insufficient balance. Need ${(satoshis/100000000).toFixed(8)} DGB + fee. Available: ${totalBalance.toFixed(8)} DGB`
                    });
                }

                const changePrivateKey = new DigiByte.PrivateKey();
                const changeAddress = changePrivateKey.toAddress();

                const tx = new DigiByte.Transaction();
                utxos.forEach(u => tx.from(u));
                tx.to(to, satoshis);
                tx.change(changeAddress.toString());
                tx.sign(pk);

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
        // 7. GET TRANSACTION DETAILS
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
        // 8. DEFAULT: API Info
        // ============================================
        return res.json({
            name: "DigiByte API",
            version: "3.0.0",
            description: "Complete DigiByte cryptocurrency management API with CoinMarketCap Keyless API",
            endpoints: {
                "GET ?action=wallet": "Generate new wallet",
                "GET ?action=balance&address=ADDR": "Check wallet balance with USD price",
                "GET ?action=utxo&address=ADDR": "Get UTXO for address",
                "GET ?action=price": "Get current DGB market price (Keyless CoinMarketCap)",
                "GET ?action=info": "Get DGB cryptocurrency info (ID: 109)",
                "GET ?action=send&privateKey=KEY&to=ADDR&amount=SAT": "Send DGB (GET)",
                "POST with body": "Send DGB (POST) - body: {action:'send',privateKey,to,amount}",
                "GET ?action=tx&txid=TXID": "Get transaction details"
            },
            notes: {
                satoshis: "1 DGB = 100,000,000 satoshis",
                fee: "Transaction fee is approximately 0.001 DGB",
                security: "⚠️ Never share your private key publicly!",
                change_key: "⚠️ Always save the change_private_key from send responses",
                price_source: "CoinMarketCap Keyless Public API - No API key required",
                cmc_id: "DGB CoinMarketCap ID is 109"
            },
            examples: {
                generate: "/api/dgb?action=wallet",
                balance: "/api/dgb?action=balance&address=D9Ms9hnm32q9nceN2b9jNshuZhWcobrmQm",
                price: "/api/dgb?action=price",
                info: "/api/dgb?action=info",
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
