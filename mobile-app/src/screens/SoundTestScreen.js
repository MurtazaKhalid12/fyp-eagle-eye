// ============================================================
//  SOUND TEST screen  —  ON-DEVICE (no server)  (TEMPORARY / REMOVABLE)
// ============================================================
//  Runs the sound detector ENTIRELY on the phone — no Flask server, no IP,
//  no Wi-Fi/firewall. Two bundled TFLite models execute locally:
//
//     mic PCM (16 kHz mono)
//        -> yamnet_embed.tflite   (15600 samples -> 1024-d embedding)
//        -> head_int8.tflite      (1024 -> softmax [background, footsteps, glass])
//        -> bars (EMA-smoothed)
//
//  REQUIRES a custom dev build (NOT Expo Go) because it uses native modules:
//     - react-native-fast-tflite        (on-device inference)
//     - react-native-live-audio-stream  (raw 16 kHz PCM capture)
//  Build once with:  npx expo run:android   (see firmware/.. START guide)
//
//  To REMOVE: delete this file + src/config/soundTestConfig.js + assets/models/,
//  and the lines marked "SOUND TEST (removable)" in App.js.
// ============================================================
import React, { useState, useRef, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AudioModule } from 'expo-audio';                       // permission only
import LiveAudioStream from 'react-native-live-audio-stream';   // raw PCM
import { loadTensorflowModel } from 'react-native-fast-tflite'; // on-device TFLite

const CLASSES = [
    { k: 'background', label: 'Background', c: '#38bdf8' },
    { k: 'footsteps', label: 'Footsteps', c: '#f59e0b' },
    { k: 'glass', label: 'Glass Break', c: '#22c55e' },
];
const PRETTY = { background: 'Background', footsteps: 'Footsteps', glass: 'Glass Break' };

const SR = 16000;      // sample rate the models expect
const WIN = 15600;     // one YAMNet frame (~0.975 s) -> [1,1024] embedding
const HOP_MS = 500;    // how often we classify the rolling window
const KEEP = WIN + SR; // ring-buffer cap (~1 window + 1 s headroom)

// --- base64 (PCM16-LE) -> Float32 [-1,1], no external deps ---
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const REV = (() => { const r = new Int16Array(256).fill(-1); for (let i = 0; i < B64.length; i++) r[B64.charCodeAt(i)] = i; return r; })();
function b64ToFloat32(s) {
    let len = s.length;
    while (len > 0 && s[len - 1] === '=') len--;            // ignore padding
    const nbytes = (len * 3) >> 2;
    const bytes = new Uint8Array(nbytes);
    let p = 0, acc = 0, bits = 0;
    for (let i = 0; i < len; i++) {
        const v = REV[s.charCodeAt(i)];
        if (v < 0) continue;
        acc = (acc << 6) | v; bits += 6;
        if (bits >= 8) { bits -= 8; bytes[p++] = (acc >> bits) & 0xff; }
    }
    const ns = p >> 1;                                       // PCM16 -> samples
    const dv = new DataView(bytes.buffer, 0, ns * 2);
    const out = new Float32Array(ns);
    for (let i = 0; i < ns; i++) out[i] = dv.getInt16(i * 2, true) / 32768;
    return out;
}

export default function SoundTestScreen() {
    const [ready, setReady] = useState(false);
    const [monitoring, setMonitoring] = useState(false);
    const [status, setStatus] = useState('Loading models…');
    const [probs, setProbs] = useState({ background: 0, footsteps: 0, glass: 0 });
    const [verdict, setVerdict] = useState('—');

    const yamnetRef = useRef(null);
    const headRef = useRef(null);
    const bufRef = useRef([]);          // rolling Float32 samples
    const runningRef = useRef(false);
    const inferRef = useRef(false);
    const emaRef = useRef(null);
    const timerRef = useRef(null);

    // ---- load models + wire the mic stream once ----
    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const y = await loadTensorflowModel(require('../../assets/models/yamnet_embed.tflite'));
                const h = await loadTensorflowModel(require('../../assets/models/head_int8.tflite'));
                if (!alive) return;
                yamnetRef.current = y; headRef.current = h;
                setReady(true);
                setStatus('Tap to start • on-device');
            } catch (e) {
                setStatus('Model load failed: ' + (e?.message || e));
            }
        })();

        try {
            LiveAudioStream.init({
                sampleRate: SR, channels: 1, bitsPerSample: 16,
                audioSource: 1,            // Android MIC (raw, unprocessed — best for non-speech)
                bufferSize: 4096, wavFile: '',
            });
            LiveAudioStream.on('data', (b64) => {
                if (!runningRef.current) return;
                const f = b64ToFloat32(b64);
                const buf = bufRef.current;
                for (let i = 0; i < f.length; i++) buf.push(f[i]);
                if (buf.length > KEEP) buf.splice(0, buf.length - KEEP);
            });
        } catch (e) { /* native module missing in Expo Go */ }

        return () => {
            alive = false; runningRef.current = false;
            try { LiveAudioStream.stop(); } catch {}
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, []);

    // ---- classify the latest window ----
    const tick = async () => {
        if (!runningRef.current || inferRef.current) return;
        const buf = bufRef.current;
        if (buf.length < WIN) return;                       // need a full window first
        inferRef.current = true;
        try {
            const win = Float32Array.from(buf.slice(buf.length - WIN));
            const [emb] = await yamnetRef.current.run([win]);            // Float32Array(1024)
            const e = emb instanceof Float32Array ? emb : Float32Array.from(emb);
            const [out] = await headRef.current.run([e]);               // Float32Array(3) softmax
            const p = { background: out[0], footsteps: out[1], glass: out[2] };
            const prev = emaRef.current;
            const ema = prev ? {} : { ...p };
            if (prev) for (const k in p) ema[k] = 0.5 * prev[k] + 0.5 * p[k];
            emaRef.current = ema;
            setProbs(ema);
            const top = Object.keys(ema).reduce((a, b) => (ema[a] >= ema[b] ? a : b));
            setVerdict(`${PRETTY[top]} — ${Math.round(ema[top] * 100)}%`);
            setStatus('Listening live • on-device');
        } catch (err) {
            setStatus('Inference error: ' + (err?.message || err));
        } finally {
            inferRef.current = false;
        }
    };

    const start = async () => {
        try {
            if (!ready) { setStatus('Models still loading…'); return; }
            const perm = await AudioModule.requestRecordingPermissionsAsync();
            if (!perm.granted) { setStatus('Microphone permission denied'); return; }
            bufRef.current = [];
            emaRef.current = null;
            runningRef.current = true;
            setMonitoring(true);
            setStatus('Listening live • on-device');
            LiveAudioStream.start();
            timerRef.current = setInterval(tick, HOP_MS);
        } catch (e) {
            setStatus('Failed to start: ' + (e?.message || e));
        }
    };

    const stop = () => {
        runningRef.current = false;
        setMonitoring(false);
        try { LiveAudioStream.stop(); } catch {}
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        setStatus('Stopped');
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.title}>Sound Test</Text>
                <Text style={styles.badge}>ON-DEVICE</Text>
            </View>
            <Text style={styles.sub}>Listens to the mic and classifies it (background / footsteps / glass) using two TFLite models running entirely on the phone — no server.</Text>

            <TouchableOpacity style={[styles.mic, monitoring && styles.micOn, !ready && styles.micDisabled]} onPress={monitoring ? stop : start} activeOpacity={0.85} disabled={!ready}>
                <Ionicons name={monitoring ? 'stop' : 'mic'} size={44} color="#04121f" />
            </TouchableOpacity>
            <Text style={styles.status}>{status}</Text>

            <View style={styles.card}>
                <Text style={styles.verdict}>{verdict}</Text>
                {CLASSES.map(({ k, label, c }) => {
                    const pct = Math.round((probs[k] || 0) * 100);
                    return (
                        <View key={k} style={styles.row}>
                            <View style={styles.rowTop}>
                                <Text style={[styles.name, { color: c }]}>{label}</Text>
                                <Text style={styles.pct}>{pct}%</Text>
                            </View>
                            <View style={styles.bar}><View style={[styles.fill, { width: `${pct}%`, backgroundColor: c }]} /></View>
                        </View>
                    );
                })}
            </View>

            <Text style={styles.foot}>YAMNet + head TFLite • 100% on-device • window {WIN / SR}s</Text>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: { flex: 1, backgroundColor: '#0b1220', padding: 20 },
    header: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 6 },
    title: { fontSize: 28, fontWeight: '800', color: '#e7eefc' },
    badge: { color: '#04121f', backgroundColor: '#22c55e', fontWeight: '800', fontSize: 11, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8 },
    sub: { color: '#90a0c0', marginTop: 6, marginBottom: 24, fontSize: 14 },
    mic: { alignSelf: 'center', width: 120, height: 120, borderRadius: 60, backgroundColor: '#22d3ee', justifyContent: 'center', alignItems: 'center', marginTop: 6 },
    micOn: { backgroundColor: '#ef4444' },
    micDisabled: { backgroundColor: '#33415c' },
    status: { textAlign: 'center', color: '#90a0c0', marginTop: 14, minHeight: 20 },
    card: { backgroundColor: '#131c31', borderRadius: 16, padding: 20, marginTop: 22, borderWidth: 1, borderColor: '#243150' },
    verdict: { textAlign: 'center', color: '#e7eefc', fontSize: 20, fontWeight: '800', marginBottom: 16, minHeight: 26 },
    row: { marginVertical: 8 },
    rowTop: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 },
    name: { fontWeight: '700' },
    pct: { color: '#cbd5e1' },
    bar: { height: 14, backgroundColor: '#0c1426', borderRadius: 10, overflow: 'hidden', borderWidth: 1, borderColor: '#243150' },
    fill: { height: '100%', borderRadius: 10 },
    foot: { color: '#64748b', fontSize: 11, textAlign: 'center', marginTop: 18 },
});
