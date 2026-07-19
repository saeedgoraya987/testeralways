const DigiByte = require("digibyte");
const axios = require("axios");

const EXPLORER = "https://digiexplorer.info";

module.exports = async (req, res) => {
    const action = req.query.action || req.body?.action;

    try {

        // Generate wallet
        if (action === "wallet") {
            const privateKey = new DigiByte.PrivateKey();

            return res.json({
                success: true,
                privateKey: privateKey.toWIF(),
                address: privateKey.toAddress().toString()
            });
        }

        // Balance
        if (action === "balance") {
            const address = req.query.address;

            const { data } = await axios.get(
                `${EXPLORER}/api/addr/${address}`
            );

            return res.json(data);
        }

        // UTXO
        if (action === "utxo") {
            const address = req.query.address;

            const { data } = await axios.get(
                `${EXPLORER}/api/addr/${address}/utxo`
            );

            return res.json(data);
        }

        // Send transaction
        if (action === "send") {

            const {
                privateKey,
                to,
                amount
            } = req.body;

            const pk = DigiByte.PrivateKey.fromWIF(privateKey);
            const from = pk.toAddress().toString();

            const { data: utxos } = await axios.get(
                `${EXPLORER}/api/addr/${from}/utxo`
            );

            const tx = new DigiByte.Transaction();

            utxos.forEach(u => tx.from(u));

            tx.to(to, Number(amount));
            tx.change(from);
            tx.sign(pk);

            const { data } = await axios.post(
                `${EXPLORER}/api/tx/send`,
                {
                    rawtx: tx.serialize()
                }
            );

            return res.json(data);
        }

        res.status(400).json({
            success: false,
            error: "Invalid action"
        });

    } catch (e) {
        res.status(500).json({
            success: false,
            error: e.message
        });
    }
};
