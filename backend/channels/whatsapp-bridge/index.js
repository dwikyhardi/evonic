'use strict';

const express = require('express');
const pino = require('pino');
const QRCode = require('qrcode');

const PORT = parseInt(process.env.PORT || '3001', 10);
const CALLBACK_URL = process.env.CALLBACK_URL || '';
const AUTH_DIR = process.env.AUTH_DIR || './auth_info';

const logger = pino({ level: 'warn' });
const app = express();
app.use(express.json());

// Connection state
let sock = null;
let currentQR = null;
let connectionStatus = 'disconnected'; // 'disconnected' | 'qr_pending' | 'connected'
let isShuttingDown = false;

async function startBaileys() {
    const baileys = await import('@whiskeysockets/baileys');
    const {
        default: makeWASocket,
        useMultiFileAuthState,
        DisconnectReason,
        fetchLatestBaileysVersion,
        makeCacheableSignalKeyStore,
        downloadMediaMessage,
    } = baileys;
    const makeInMemoryStore = baileys.makeInMemoryStore || null;
    const { Boom } = await import('@hapi/boom');
    const fs = await import('fs');

    fs.default.mkdirSync(AUTH_DIR, { recursive: true });

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
        version,
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger),
        },
        printQRInTerminal: false,
        logger,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
        if (qr) {
            currentQR = qr;
            connectionStatus = 'qr_pending';
        }

        if (connection === 'open') {
            currentQR = null;
            connectionStatus = 'connected';
            console.log('[whatsapp-bridge] Connected to WhatsApp');
        }

        if (connection === 'close') {
            connectionStatus = 'disconnected';
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const loggedOut = statusCode === DisconnectReason.loggedOut;

            if (isShuttingDown) return;

            if (loggedOut) {
                console.log('[whatsapp-bridge] Logged out — clearing session');
                fs.default.rmSync(AUTH_DIR, { recursive: true, force: true });
            } else {
                console.log('[whatsapp-bridge] Disconnected, reconnecting...');
                setTimeout(startBaileys, 3000);
            }
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        if (!CALLBACK_URL) return;

        for (const msg of messages) {
            if (msg.key.fromMe) continue;

            const from = msg.key.remoteJid || '';

            // Use remoteJid as-is for replies (@lid JIDs are valid routable identifiers)
            const jid = from;
            const sender = from.includes('@') ? from.split('@')[0] : from;
            const messageId = msg.key.id || '';

            // Extract text
            const text =
                msg.message?.conversation ||
                msg.message?.extendedTextMessage?.text ||
                msg.message?.imageMessage?.caption ||
                msg.message?.videoMessage?.caption ||
                '';

            // Extract button reply (approval flow)
            const buttonReply = msg.message?.buttonsResponseMessage;
            if (buttonReply) {
                const buttonId = buttonReply.selectedButtonId || '';
                postCallback({ from: sender, jid, message_id: messageId, button_id: buttonId, text: '' });
                continue;
            }

            // Extract image if present
            let image = null;
            if (msg.message?.imageMessage) {
                try {
                    const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger });
                    const mimetype = msg.message.imageMessage.mimetype || 'image/jpeg';
                    image = {
                        base64: buffer.toString('base64'),
                        mimetype,
                    };
                } catch (e) {
                    console.error('[whatsapp-bridge] Failed to download image:', e.message);
                }
            }

            // Extract reply/quoted context
            let quotedText = null;
            const quoted = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
            if (quoted) {
                quotedText =
                    quoted.conversation ||
                    quoted.extendedTextMessage?.text ||
                    null;
            }

            postCallback({ from: sender, jid, message_id: messageId, text, image, quoted_text: quotedText });
        }
    });
}

function postCallback(payload) {
    const http = require('http');
    const url = new URL(CALLBACK_URL);
    const body = JSON.stringify(payload);
    const req = http.request({
        hostname: url.hostname,
        port: url.port || 80,
        path: url.pathname,
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(body),
        },
    }, (res) => {
        res.resume(); // drain
    });
    req.on('error', (e) => console.error('[whatsapp-bridge] Callback error:', e.message));
    req.write(body);
    req.end();
}

// ---- REST API ----

app.get('/status', (req, res) => {
    res.json({ status: connectionStatus });
});

app.get('/qr', async (req, res) => {
    if (connectionStatus === 'connected') {
        return res.json({ status: 'connected' });
    }
    if (!currentQR) {
        return res.json({ status: connectionStatus, qr: null });
    }
    try {
        const png = await QRCode.toDataURL(currentQR);
        res.json({ status: 'qr_pending', qr: png });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.post('/send', async (req, res) => {
    const { to, text } = req.body || {};
    if (!to || !text) return res.status(400).json({ error: 'to and text required' });
    if (!sock || connectionStatus !== 'connected') {
        return res.status(503).json({ error: 'Not connected to WhatsApp' });
    }
    // Use @lid JIDs as-is — they are valid routable identifiers in Baileys
    const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;
    await sock.sendMessage(jid, { text });
    res.json({ success: true });
});

app.post('/send-buttons', async (req, res) => {
    const { to, text, buttons } = req.body || {};
    if (!to || !text || !buttons) return res.status(400).json({ error: 'to, text, buttons required' });
    if (!sock || connectionStatus !== 'connected') {
        return res.status(503).json({ error: 'Not connected to WhatsApp' });
    }
    try {
        const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;
        const waButtons = buttons.slice(0, 3).map((b) => ({
            buttonId: b.id,
            buttonText: { displayText: b.title.slice(0, 20) },
            type: 1,
        }));
        await sock.sendMessage(jid, {
            text,
            buttons: waButtons,
            headerType: 1,
        });
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.post('/logout', async (req, res) => {
    try {
        if (sock) await sock.logout();
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ---- Start ----

app.listen(PORT, '127.0.0.1', () => {
    console.log(`[whatsapp-bridge] Listening on 127.0.0.1:${PORT}`);
    startBaileys().catch((e) => console.error('[whatsapp-bridge] Baileys start error:', e));
});

process.on('SIGTERM', async () => {
    isShuttingDown = true;
    console.log('[whatsapp-bridge] Shutting down');
    try {
        if (sock) await sock.end();
    } catch (_) {}
    process.exit(0);
});
