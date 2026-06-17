// ============================================================
//  SOUND TEST screen  (TEMPORARY / REMOVABLE)
// ============================================================
//  CONTINUOUS live monitoring: repeatedly records a short (~1.2 s) clip,
//  sends it to the model server (YAMNet + head), and updates the bars live
//  with smoothing — until you press Stop.
//
//  Runs in Expo Go (the model executes on the server; true on-device
//  streaming TFLite would need a custom dev build).
//
//  To REMOVE: delete this file + src/config/soundTestConfig.js, and the
//  lines marked "SOUND TEST (removable)" in App.js.
// ============================================================
import React, { useState, useRef, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import {
    useAudioRecorder,
    AudioModule,
    RecordingPresets,
    setAudioModeAsync,
} from 'expo-audio';
import { SOUND_SERVER_URL } from '../config/soundTestConfig';

const CLASSES = [
    { k: 'background', label: 'Background', c: '#38bdf8' },
    { k: 'footsteps', label: 'Footsteps', c: '#f59e0b' },
    { k: 'glass', label: 'Glass Break', c: '#22c55e' },
];
const PRETTY = { background: 'Background', footsteps: 'Footsteps', glass: 'Glass Break' };
const CLIP_MS = 1200;            // length of each rolling window
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default function SoundTestScreen() {
    const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
    const [monitoring, setMonitoring] = useState(false);
    const [status, setStatus] = useState('Tap to start live monitoring');
    const [probs, setProbs] = useState({ background: 0, footsteps: 0, glass: 0 });
    const [verdict, setVerdict] = useState('—');
    const runningRef = useRef(false);
    const emaRef = useRef(null);

    useEffect(() => () => { runningRef.current = false; }, []);   // stop loop on unmount

    const classifyOnce = async () => {
        await recorder.prepareToRecordAsync();
        recorder.record();
        await sleep(CLIP_MS);
        await recorder.stop();
        const fd = new FormData();
        fd.append('audio', { uri: recorder.uri, name: 'clip.m4a', type: 'audio/m4a' });
        const res = await fetch(`${SOUND_SERVER_URL}/predict`, { method: 'POST', body: fd });
        const d = await res.json();
        if (d.error) throw new Error(d.error);
        return d.probs;
    };

    const loop = async () => {
        while (runningRef.current) {
            try {
                const p = await classifyOnce();
                const prev = emaRef.current;
                const ema = prev ? {} : { ...p };
                if (prev) for (const k in p) ema[k] = 0.5 * prev[k] + 0.5 * p[k];
                emaRef.current = ema;
                setProbs(ema);
                const top = Object.keys(ema).reduce((a, b) => (ema[a] >= ema[b] ? a : b));
                setVerdict(`${PRETTY[top]} — ${Math.round(ema[top] * 100)}%`);
                setStatus('Listening live…');
            } catch (err) {
                setStatus('Error: ' + (err?.message || err));
                await sleep(800);   // back off on error, keep trying
            }
        }
    };

    const start = async () => {
        try {
            const perm = await AudioModule.requestRecordingPermissionsAsync();
            if (!perm.granted) { setStatus('Microphone permission denied'); return; }
            await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
            emaRef.current = null;
            runningRef.current = true;
            setMonitoring(true);
            setStatus('Listening live…');
            loop();
        } catch (e) {
            setStatus('Failed to start: ' + (e?.message || e));
        }
    };

    const stop = () => {
        runningRef.current = false;
        setMonitoring(false);
        setStatus('Stopped');
        try { recorder.stop(); } catch {}
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.title}>Sound Test</Text>
                <Text style={styles.badge}>LIVE</Text>
            </View>
            <Text style={styles.sub}>Continuously monitors the mic and classifies it (background / footsteps / glass) using the trained model on the server.</Text>

            <TouchableOpacity style={[styles.mic, monitoring && styles.micOn]} onPress={monitoring ? stop : start} activeOpacity={0.85}>
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

            <Text style={styles.foot}>Server: {SOUND_SERVER_URL}  •  window {CLIP_MS} ms</Text>
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
