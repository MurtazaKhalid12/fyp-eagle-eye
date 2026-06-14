import React, { useState, useEffect, useRef } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    ActivityIndicator,
    ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import Joystick from '../components/Joystick';
import {
    connectMqtt,
    onStatus,
    setPanTilt,
    startStream,
    stopStream,
    viewUrl,
} from '../services/mqttClient';
import { lanConnect, sendServoLan, onLanStatus } from '../services/lanControl';

function arrayBufferToJpegDataUri(buffer) {
    const u8 = new Uint8Array(buffer);
    const chunk = 0x8000;
    let binary = '';
    for (let i = 0; i < u8.length; i += chunk) {
        binary += String.fromCharCode.apply(null, u8.subarray(i, Math.min(i + chunk, u8.length)));
    }
    return `data:image/jpeg;base64,${btoa(binary)}`;
}

export default function LiveMonitorScreen() {
    const [isStreaming, setIsStreaming] = useState(false);
    const [connecting, setConnecting] = useState(false);
    const [wsError, setWsError] = useState(null);
    const [frameDataUri, setFrameDataUri] = useState(null);
    const [camOnline, setCamOnline] = useState(false);
    const [panDeg, setPanDeg] = useState(90);     // GPIO15
    const [tiltDeg, setTiltDeg] = useState(90);   // GPIO14
    const [lanActive, setLanActive] = useState(false);   // direct-LAN control up?
    const wsRef = useRef(null);

    // Camera online/offline + device LAN IP from the retained MQTT status (+ LWT).
    useEffect(() => {
        connectMqtt();
        const off = onStatus((s) => {
            setCamOnline(!!s?.online);
            if (s?.ip) lanConnect(s.ip, s.lan || 81);    // open the low-latency LAN socket
        });
        const offLan = onLanStatus(setLanActive);
        return () => { off(); offLan(); };
    }, []);

    // Live video: open the relay viewer socket while streaming.
    useEffect(() => {
        if (!isStreaming) {
            setFrameDataUri(null);
            return;
        }
        setConnecting(true);
        setWsError(null);

        const ws = new WebSocket(viewUrl());
        ws.binaryType = 'arraybuffer';
        wsRef.current = ws;

        ws.onmessage = (event) => {
            if (typeof event.data === 'string') return;       // control text, ignore
            try {
                setFrameDataUri(arrayBufferToJpegDataUri(event.data));
                setConnecting(false);
                setWsError(null);
            } catch {
                setWsError('Invalid JPEG frame from relay');
            }
        };
        ws.onerror = () => { setWsError('Relay connection failed.'); setConnecting(false); };
        ws.onclose = () => {};

        return () => { try { ws.close(); } catch {} };
    }, [isStreaming]);

    const toggleStream = () => {
        if (isStreaming) {
            setIsStreaming(false);
            stopStream();                                     // tell the camera to stop pushing
            setWsError(null);
            setFrameDataUri(null);
        } else {
            setWsError(null);
            setIsStreaming(true);
            startStream();                                    // tell the camera to start the relay
        }
    };

    // ---- Pan/Tilt PTZ rate control over MQTT ----
    //  The joystick reports a normalised vector [-1,1] while held. A steady
    //  ticker integrates that vector into pan/tilt angles and publishes — so
    //  push-and-hold pans/tilts at a speed set by how far you push, and
    //  releasing (vector -> 0) leaves the servos holding their position.
    // ---- Pan/Tilt ABSOLUTE aim ----
    //  The pad is sticky: the knob position maps directly to the servo angles
    //  (full 0–180° per axis) and holds. We stream the target continuously
    //  while dragging (LAN-first) and the device's smooth stepper does the
    //  motion — no rate integration, so no lurch/stutter.
    const joyRef = useRef(null);
    const panRef = useRef(90);
    const tiltRef = useRef(90);
    const lastPubRef = useRef(0);       // throttle network publishes
    const lastReadoutRef = useRef(0);   // throttle the on-screen number (avoids 60 re-renders/s)

    const sendTargets = (pan, tilt, force) => {
        const rp = Math.max(0, Math.min(180, Math.round(pan)));
        const rt = Math.max(0, Math.min(180, Math.round(tilt)));
        panRef.current = rp; tiltRef.current = rt;
        const now = Date.now();
        if (force || now - lastReadoutRef.current >= 100) {
            lastReadoutRef.current = now; setPanDeg(rp); setTiltDeg(rt);
        }
        if (force || now - lastPubRef.current >= 40) {
            lastPubRef.current = now;
            if (!sendServoLan(rp, rt)) setPanTilt(rp, rt);   // LAN first, else cloud MQTT
        }
    };

    // Knob normalised [-1,1] -> angles, matched to this rig's mounts:
    //   pan : knob left = pan 180, knob right = pan 0  (GPIO15)
    //   tilt: knob down = tilt 180, knob up = tilt 0    (GPIO14)
    const onJoyMove = (nx, ny) => sendTargets((1 - nx) / 2 * 180, (ny + 1) / 2 * 180, false);
    const onJoyEnd = () => sendTargets(panRef.current, tiltRef.current, true);   // exact final aim
    const centerServos = () => {
        joyRef.current?.setNormalized(0, 0);
        sendTargets(90, 90, true);
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.headerTitle}>Live Monitor</Text>
                <View style={[styles.statusBadge, { backgroundColor: isStreaming ? '#E8F5E9' : '#FFF3E0' }]}>
                    <View style={[styles.statusDot, { backgroundColor: isStreaming ? '#4CAF50' : '#FF9800' }]} />
                    <Text style={[styles.statusText, { color: isStreaming ? '#2E7D32' : '#F57C00' }]}>
                        {isStreaming ? 'LIVE' : 'STANDBY'}
                    </Text>
                </View>
            </View>

            <ScrollView contentContainerStyle={styles.content}>
                <View style={styles.streamContainer}>
                    {isStreaming ? (
                        <>
                            {connecting && !frameDataUri && (
                                <View style={styles.loaderContainer}>
                                    <ActivityIndicator size="large" color="#2196F3" />
                                    <Text style={styles.loaderText}>Waiting for camera stream…</Text>
                                </View>
                            )}
                            {wsError ? (
                                <View style={styles.errorBanner}>
                                    <Text style={styles.errorText}>{wsError}</Text>
                                    <Text style={styles.errorHint}>
                                        The camera must be online and the relay reachable.
                                    </Text>
                                </View>
                            ) : null}
                            {frameDataUri ? (
                                <Image
                                    source={{ uri: frameDataUri }}
                                    style={styles.liveImage}
                                    contentFit="contain"
                                    cachePolicy="none"
                                    priority="high"
                                    transition={0}
                                    allowDownscaling
                                />
                            ) : null}
                        </>
                    ) : (
                        <View style={styles.offlineContainer}>
                            <Ionicons name="videocam-off" size={64} color="#BDBDBD" />
                            <Text style={styles.offlineText}>Stream is paused.</Text>
                            <Text style={styles.offlineSubText}>Press Start to view the live feed.</Text>
                        </View>
                    )}
                </View>

                <View style={styles.controlsCard}>
                    <View style={styles.servoHeaderRow}>
                        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                            <Ionicons name={camOnline ? 'cloud-done' : 'cloud-offline'} size={20} color={camOnline ? '#2E7D32' : '#C62828'} />
                            <Text style={[styles.inputLabel, { marginBottom: 0, marginLeft: 8 }]}>
                                Camera {camOnline ? 'online' : 'offline'}
                            </Text>
                        </View>
                    </View>

                    <TouchableOpacity
                        style={[styles.button, isStreaming ? styles.buttonStop : styles.buttonStart]}
                        onPress={toggleStream}
                        activeOpacity={0.8}
                    >
                        <Ionicons name={isStreaming ? 'stop' : 'play'} size={20} color="#FFF" />
                        <Text style={styles.buttonText}>{isStreaming ? 'Stop Live View' : 'Start Live View'}</Text>
                    </TouchableOpacity>

                    <Text style={[styles.hintText, { marginTop: 12, marginBottom: 0 }]}>
                        Live video streams through the cloud relay — works from any network, no IP needed.
                    </Text>
                </View>

                {/* ---- Pan/Tilt joystick over MQTT ---- */}
                <View style={[styles.controlsCard, { marginTop: 20 }]}>
                    <View style={styles.servoHeaderRow}>
                        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                            <Ionicons name="game-controller-outline" size={20} color="#424242" />
                            <Text style={[styles.inputLabel, { marginBottom: 0, marginLeft: 8 }]}>Pan / Tilt Joystick</Text>
                        </View>
                        <View style={styles.ptReadout}>
                            <Text style={styles.ptText}>P {panDeg}°</Text>
                            <Text style={styles.ptText}>T {tiltDeg}°</Text>
                        </View>
                    </View>

                    <View style={[styles.latencyPill, { backgroundColor: lanActive ? '#E8F5E9' : '#FFF3E0' }]}>
                        <Ionicons
                            name={lanActive ? 'flash' : 'cloud-outline'}
                            size={13}
                            color={lanActive ? '#2E7D32' : '#F57C00'}
                        />
                        <Text style={[styles.latencyText, { color: lanActive ? '#2E7D32' : '#F57C00' }]}>
                            {lanActive ? 'Direct LAN — low latency' : 'Cloud (MQTT) — higher latency'}
                        </Text>
                    </View>

                    <Joystick ref={joyRef} size={240} knobSize={78} onMove={onJoyMove} onRelease={onJoyEnd} />

                    <TouchableOpacity style={[styles.servoCenterBtn, { marginTop: 18 }]} onPress={centerServos} activeOpacity={0.8}>
                        <Ionicons name="locate" size={18} color="#FFF" />
                        <Text style={styles.servoCenterText}>Center (90° / 90°)</Text>
                    </TouchableOpacity>

                    <Text style={[styles.hintText, { marginTop: 14, marginBottom: 0 }]}>
                        Drag to aim the camera — the knob position sets pan (left/right, 0–180°) and tilt
                        (up/down, 0–180°), and stays where you leave it. Pan → GPIO15, Tilt → GPIO14.
                    </Text>
                </View>
            </ScrollView>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: { flex: 1, backgroundColor: '#F7F8FA' },
    header: {
        flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
        paddingHorizontal: 20, paddingTop: 10, paddingBottom: 15,
    },
    headerTitle: { fontSize: 28, fontWeight: '800', color: '#1A1A1A' },
    statusBadge: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20 },
    statusDot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
    statusText: { fontSize: 12, fontWeight: 'bold' },
    content: { paddingHorizontal: 20, paddingBottom: 30 },
    streamContainer: {
        width: '100%', aspectRatio: 4 / 3, backgroundColor: '#000', borderRadius: 16, overflow: 'hidden',
        marginBottom: 24, shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.15,
        shadowRadius: 12, elevation: 8, justifyContent: 'center', alignItems: 'center', position: 'relative',
    },
    liveImage: { ...StyleSheet.absoluteFillObject },
    loaderContainer: { position: 'absolute', justifyContent: 'center', alignItems: 'center', zIndex: 10 },
    loaderText: { color: '#FFF', marginTop: 12, fontSize: 14, fontWeight: '500' },
    errorBanner: { ...StyleSheet.absoluteFillObject, zIndex: 5, justifyContent: 'center', padding: 16, backgroundColor: 'rgba(0,0,0,0.75)' },
    errorText: { color: '#FFCDD2', fontSize: 15, fontWeight: '600', textAlign: 'center' },
    errorHint: { color: '#B0BEC5', fontSize: 13, marginTop: 10, textAlign: 'center' },
    offlineContainer: { justifyContent: 'center', alignItems: 'center' },
    offlineText: { color: '#FFF', fontSize: 18, fontWeight: '600', marginTop: 16 },
    offlineSubText: { color: '#9E9E9E', fontSize: 14, marginTop: 8 },
    controlsCard: {
        backgroundColor: '#FFFFFF', borderRadius: 16, padding: 20, shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 10, elevation: 3,
    },
    inputLabel: { fontSize: 14, fontWeight: '600', color: '#424242', marginBottom: 8 },
    hintText: { fontSize: 12, color: '#757575', marginBottom: 16 },
    button: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: 14, borderRadius: 12 },
    buttonStart: { backgroundColor: '#2196F3' },
    buttonStop: { backgroundColor: '#F44336' },
    buttonText: { color: '#FFF', fontSize: 16, fontWeight: 'bold', marginLeft: 8 },
    // servo / joystick
    servoHeaderRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
    ptReadout: { flexDirection: 'row' },
    ptText: { fontSize: 16, fontWeight: '800', color: '#2196F3', marginLeft: 14 },
    latencyPill: { flexDirection: 'row', alignItems: 'center', alignSelf: 'center', paddingHorizontal: 12, paddingVertical: 5, borderRadius: 14, marginBottom: 16 },
    latencyText: { fontSize: 12, fontWeight: '700', marginLeft: 6 },
    servoCenterBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#2196F3', borderRadius: 12, paddingVertical: 14 },
    servoCenterText: { color: '#FFF', fontSize: 15, fontWeight: '700', marginLeft: 6 },
});
