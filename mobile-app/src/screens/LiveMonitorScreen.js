import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TextInput,
    TouchableOpacity,
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    Linking,
    Alert,
    PanResponder,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';

const IPV4_RE = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

/** Must match EAGLEEYE_WS_PORT in firmware eagleeye_ws.h */
const WS_PREVIEW_PORT = 81;

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
    const [ipAddress, setIpAddress] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [streamError, setStreamError] = useState(null);
    const [frameDataUri, setFrameDataUri] = useState(null);
    const streamingRef = useRef(false);

    // --- Servo pan control (camera head). Sends GET http://<ip>/servo?angle=N ---
    const [servoAngle, setServoAngle] = useState(90);
    const [servoBusy, setServoBusy] = useState(false);

    useEffect(() => {
        streamingRef.current = isStreaming;
    }, [isStreaming]);

    // Keep the latest IP in a ref so the once-created PanResponder never goes stale.
    const ipRef = useRef('');
    useEffect(() => { ipRef.current = ipAddress; }, [ipAddress]);

    // Measure the slider track in WINDOW space. We map touches with pageX (absolute),
    // not nativeEvent.locationX — locationX is relative to whatever child the finger
    // lands on, which is what made the low-angle end misread / glitch.
    const trackRef = useRef(null);
    const trackLayout = useRef({ x: 0, width: 0 });
    const measureTrack = () => {
        trackRef.current?.measureInWindow((x, y, w) => {
            if (w > 0) trackLayout.current = { x, width: w };
        });
    };
    const angleFromPageX = (pageX) => {
        const { x, width } = trackLayout.current;
        if (!width) return servoAngle;
        const rel = Math.max(0, Math.min(width, pageX - x));
        return Math.round((rel / width) * 180);
    };

    // Latest-wins sender: while dragging we keep only the newest angle in `pending`
    // and never let requests pile up — so the head follows the finger with low delay
    // and always settles on the final angle.
    const inFlightRef = useRef(false);
    const pendingRef = useRef(null);
    const flushServo = async () => {
        if (inFlightRef.current || pendingRef.current == null) return;
        const ip = ipRef.current.trim();
        if (!IPV4_RE.test(ip)) {
            pendingRef.current = null;
            setStreamError('Enter the camera IP first (same field as live view).');
            return;
        }
        inFlightRef.current = true;
        const a = pendingRef.current;
        pendingRef.current = null;
        setServoBusy(true);
        try {
            const ctrl = new AbortController();
            const t = setTimeout(() => ctrl.abort(), 2000);
            await fetch(`http://${ip}/servo?angle=${a}`, { signal: ctrl.signal });
            clearTimeout(t);
            setStreamError(null);
        } catch {
            setStreamError('Servo command failed (camera offline or wrong IP).');
        } finally {
            inFlightRef.current = false;
            setServoBusy(false);
            if (pendingRef.current != null) flushServo();   // send the newest queued angle
        }
    };
    const queueServo = (angle) => {
        const a = Math.max(0, Math.min(180, Math.round(angle)));
        setServoAngle(a);
        pendingRef.current = a;
        flushServo();
    };

    // Stable drag handler ref so the once-created PanResponder calls the latest closure.
    const onDragRef = useRef(() => {});
    onDragRef.current = (pageX) => queueServo(angleFromPageX(pageX));

    const panResponder = useRef(
        PanResponder.create({
            onStartShouldSetPanResponder: () => true,
            onMoveShouldSetPanResponder: () => true,
            onPanResponderGrant: (e) => { measureTrack(); onDragRef.current(e.nativeEvent.pageX); },
            onPanResponderMove: (e) => onDragRef.current(e.nativeEvent.pageX),
            onPanResponderRelease: (e) => onDragRef.current(e.nativeEvent.pageX),
            onPanResponderTerminate: (e) => onDragRef.current(e.nativeEvent.pageX),
        }),
    ).current;

    useEffect(() => {
        if (!isStreaming) {
            setFrameDataUri(null);
            return;
        }

        const ip = ipAddress.trim();
        if (!IPV4_RE.test(ip)) {
            return;
        }

        setIsLoading(true);
        setStreamError(null);
        setFrameDataUri(null);

        const url = `ws://${ip}:${WS_PREVIEW_PORT}`;
        const ws = new WebSocket(url);
        ws.binaryType = 'arraybuffer';

        ws.onopen = () => {
            setStreamError(null);
        };

        ws.onmessage = (event) => {
            if (typeof event.data === 'string') {
                return;
            }
            try {
                const uri = arrayBufferToJpegDataUri(event.data);
                setFrameDataUri(uri);
                setIsLoading(false);
                setStreamError(null);
            } catch {
                setStreamError('Invalid JPEG frame from camera');
            }
        };

        ws.onerror = () => {
            setStreamError(
                `WebSocket ${url} failed. Flash firmware with eagleeye_ws.h and install Arduino library "WebSockets" (Links2004).`,
            );
            setIsLoading(false);
        };

        ws.onclose = () => {
            setIsLoading(false);
            if (streamingRef.current) {
                setStreamError('WebSocket closed (camera offline or wrong IP).');
            }
        };

        return () => {
            ws.close();
        };
    }, [isStreaming, ipAddress]);

    const toggleStream = async () => {
        if (isStreaming) {
            setIsStreaming(false);
            setStreamError(null);
            setFrameDataUri(null);
            return;
        }

        const ip = ipAddress.trim();
        if (!ip) {
            alert('Enter the ESP32 IP from Serial Monitor (e.g. 192.168.137.5 on PC hotspot).');
            return;
        }
        if (!IPV4_RE.test(ip)) {
            alert('Enter a full IPv4 address, e.g. 192.168.137.5');
            return;
        }

        setStreamError(null);
        setIsStreaming(true);
    };

    const openStreamInBrowser = useCallback(async () => {
        const ip = ipAddress.trim();
        if (!IPV4_RE.test(ip)) {
            Alert.alert('Invalid IP', 'Enter the full camera IP first.');
            return;
        }
        const url = `http://${ip}/`;
        try {
            await Linking.openURL(url);
        } catch {
            Alert.alert('Could not open browser', url);
        }
    }, [ipAddress]);

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

            <KeyboardAvoidingView
                behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
                style={styles.content}
            >
                <View style={styles.streamContainer}>
                    {isStreaming ? (
                        <>
                            {isLoading && !frameDataUri && (
                                <View style={styles.loaderContainer}>
                                    <ActivityIndicator size="large" color="#2196F3" />
                                    <Text style={styles.loaderText}>WebSocket {WS_PREVIEW_PORT}…</Text>
                                </View>
                            )}
                            {streamError ? (
                                <View style={styles.errorBanner}>
                                    <Text style={styles.errorText}>{streamError}</Text>
                                    <Text style={styles.errorHint}>
                                        Same Wi‑Fi as the camera. Browser MJPEG button still works as fallback.
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
                            <Text style={styles.offlineText}>Stream is currently paused.</Text>
                            <Text style={styles.offlineSubText}>Press connect to view live feed.</Text>
                        </View>
                    )}
                </View>

                <View style={styles.controlsCard}>
                    <Text style={styles.inputLabel}>ESP32-CAM IP Address</Text>
                    <View style={styles.inputRow}>
                        <Ionicons name="wifi" size={20} color="#757575" style={styles.inputIcon} />
                        <TextInput
                            style={styles.input}
                            placeholder="e.g. 192.168.137.5 (Serial Monitor)"
                            value={ipAddress}
                            onChangeText={setIpAddress}
                            keyboardType={Platform.OS === 'ios' ? 'numbers-and-punctuation' : 'decimal-pad'}
                            autoCapitalize="none"
                            autoCorrect={false}
                        />
                    </View>

                    <Text style={styles.hintText}>
                        Live preview uses WebSocket ws://&lt;ip&gt;:{WS_PREVIEW_PORT} (binary JPEG, persistent connection —
                        faster than HTTP polling). Arduino: install library &quot;WebSockets&quot; by Markus Sattler, then
                        flash firmware.
                    </Text>

                    <TouchableOpacity
                        style={[styles.button, isStreaming ? styles.buttonStop : styles.buttonStart]}
                        onPress={toggleStream}
                        activeOpacity={0.8}
                    >
                        <Ionicons name={isStreaming ? 'stop' : 'play'} size={20} color="#FFF" />
                        <Text style={styles.buttonText}>
                            {isStreaming ? 'Stop Live View' : 'Start Live View'}
                        </Text>
                    </TouchableOpacity>

                    <TouchableOpacity
                        style={[styles.button, styles.buttonSecondary]}
                        onPress={openStreamInBrowser}
                        activeOpacity={0.8}
                    >
                        <Ionicons name="open-outline" size={20} color="#1976D2" />
                        <Text style={styles.buttonTextSecondary}>Open MJPEG stream in browser</Text>
                    </TouchableOpacity>
                </View>

                {/* ---- Camera pan (servo) control ---- */}
                <View style={styles.controlsCard}>
                    <View style={styles.servoHeaderRow}>
                        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                            <Ionicons name="sync-outline" size={20} color="#424242" />
                            <Text style={[styles.inputLabel, { marginBottom: 0, marginLeft: 8 }]}>
                                Camera Pan (Servo)
                            </Text>
                        </View>
                        <Text style={styles.servoAngleValue}>{servoAngle}°</Text>
                    </View>

                    {/* draggable slider 0–180 */}
                    <View
                        ref={trackRef}
                        style={styles.sliderTrack}
                        onLayout={measureTrack}
                        {...panResponder.panHandlers}
                    >
                        <View pointerEvents="none" style={[styles.sliderFill, { width: `${(servoAngle / 180) * 100}%` }]} />
                        <View pointerEvents="none" style={[styles.sliderThumb, { left: `${(servoAngle / 180) * 100}%` }]} />
                    </View>
                    <View style={styles.sliderScaleRow}>
                        <Text style={styles.sliderScaleText}>0°</Text>
                        <Text style={styles.sliderScaleText}>90°</Text>
                        <Text style={styles.sliderScaleText}>180°</Text>
                    </View>

                    {/* nudge + center */}
                    <View style={styles.servoButtonRow}>
                        <TouchableOpacity
                            style={styles.servoNudgeBtn}
                            onPress={() => queueServo(servoAngle - 15)}
                            activeOpacity={0.8}
                        >
                            <Ionicons name="chevron-back" size={18} color="#1976D2" />
                            <Text style={styles.servoNudgeText}>15°</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={styles.servoCenterBtn}
                            onPress={() => queueServo(90)}
                            activeOpacity={0.8}
                        >
                            <Ionicons name="locate" size={18} color="#FFF" />
                            <Text style={styles.servoCenterText}>Center</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={styles.servoNudgeBtn}
                            onPress={() => queueServo(servoAngle + 15)}
                            activeOpacity={0.8}
                        >
                            <Text style={styles.servoNudgeText}>15°</Text>
                            <Ionicons name="chevron-forward" size={18} color="#1976D2" />
                        </TouchableOpacity>
                    </View>

                    {/* presets */}
                    <View style={styles.servoPresetRow}>
                        {[0, 45, 90, 135, 180].map((a) => (
                            <TouchableOpacity
                                key={a}
                                style={[styles.servoPresetBtn, servoAngle === a && styles.servoPresetActive]}
                                onPress={() => queueServo(a)}
                                activeOpacity={0.8}
                            >
                                <Text style={[styles.servoPresetText, servoAngle === a && styles.servoPresetTextActive]}>
                                    {a}°
                                </Text>
                            </TouchableOpacity>
                        ))}
                    </View>

                    <Text style={styles.hintText}>
                        {servoBusy ? 'Sending…' : 'Drag the slider, tap a preset, or nudge ±15°. The head pans smoothly to the chosen angle.'}
                    </Text>
                </View>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#F7F8FA',
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingHorizontal: 20,
        paddingTop: 10,
        paddingBottom: 15,
    },
    headerTitle: {
        fontSize: 28,
        fontWeight: '800',
        color: '#1A1A1A',
    },
    statusBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 20,
    },
    statusDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
        marginRight: 6,
    },
    statusText: {
        fontSize: 12,
        fontWeight: 'bold',
    },
    content: {
        flex: 1,
        paddingHorizontal: 20,
    },
    streamContainer: {
        width: '100%',
        aspectRatio: 4 / 3,
        backgroundColor: '#000',
        borderRadius: 16,
        overflow: 'hidden',
        marginBottom: 24,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.15,
        shadowRadius: 12,
        elevation: 8,
        justifyContent: 'center',
        alignItems: 'center',
        position: 'relative',
    },
    liveImage: {
        ...StyleSheet.absoluteFillObject,
    },
    loaderContainer: {
        position: 'absolute',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 10,
    },
    loaderText: {
        color: '#FFF',
        marginTop: 12,
        fontSize: 14,
        fontWeight: '500',
    },
    errorBanner: {
        ...StyleSheet.absoluteFillObject,
        zIndex: 5,
        justifyContent: 'center',
        padding: 16,
        backgroundColor: 'rgba(0,0,0,0.75)',
    },
    errorText: {
        color: '#FFCDD2',
        fontSize: 15,
        fontWeight: '600',
        textAlign: 'center',
    },
    errorHint: {
        color: '#B0BEC5',
        fontSize: 13,
        marginTop: 10,
        textAlign: 'center',
    },
    offlineContainer: {
        justifyContent: 'center',
        alignItems: 'center',
    },
    offlineText: {
        color: '#FFF',
        fontSize: 18,
        fontWeight: '600',
        marginTop: 16,
    },
    offlineSubText: {
        color: '#9E9E9E',
        fontSize: 14,
        marginTop: 8,
    },
    controlsCard: {
        backgroundColor: '#FFFFFF',
        borderRadius: 16,
        padding: 20,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 10,
        elevation: 3,
    },
    inputLabel: {
        fontSize: 14,
        fontWeight: '600',
        color: '#424242',
        marginBottom: 8,
    },
    inputRow: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#F5F5F5',
        borderWidth: 1,
        borderColor: '#E0E0E0',
        borderRadius: 12,
        paddingHorizontal: 12,
        marginBottom: 8,
    },
    hintText: {
        fontSize: 12,
        color: '#757575',
        marginBottom: 16,
    },
    inputIcon: {
        marginRight: 10,
    },
    input: {
        flex: 1,
        height: 50,
        fontSize: 16,
        color: '#212121',
    },
    button: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: 14,
        borderRadius: 12,
    },
    buttonStart: {
        backgroundColor: '#2196F3',
    },
    buttonStop: {
        backgroundColor: '#F44336',
    },
    buttonSecondary: {
        backgroundColor: '#E3F2FD',
        marginTop: 12,
    },
    buttonText: {
        color: '#FFF',
        fontSize: 16,
        fontWeight: 'bold',
        marginLeft: 8,
    },
    buttonTextSecondary: {
        color: '#1976D2',
        fontSize: 16,
        fontWeight: '600',
        marginLeft: 8,
    },
    // ---- servo pan control ----
    servoHeaderRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
    },
    servoAngleValue: {
        fontSize: 20,
        fontWeight: '800',
        color: '#2196F3',
    },
    sliderTrack: {
        height: 36,
        backgroundColor: '#E0E0E0',
        borderRadius: 18,
        justifyContent: 'center',
        marginBottom: 6,
    },
    sliderFill: {
        position: 'absolute',
        left: 0,
        top: 0,
        bottom: 0,
        backgroundColor: '#BBDEFB',
        borderRadius: 18,
    },
    sliderThumb: {
        position: 'absolute',
        width: 26,
        height: 26,
        borderRadius: 13,
        backgroundColor: '#2196F3',
        marginLeft: -13,
        borderWidth: 3,
        borderColor: '#FFF',
        elevation: 3,
    },
    sliderScaleRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginBottom: 14,
    },
    sliderScaleText: {
        fontSize: 11,
        color: '#9E9E9E',
        fontWeight: '600',
    },
    servoButtonRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
    },
    servoNudgeBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#E3F2FD',
        borderRadius: 12,
        paddingVertical: 12,
        flex: 1,
    },
    servoNudgeText: {
        color: '#1976D2',
        fontSize: 15,
        fontWeight: '700',
    },
    servoCenterBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#2196F3',
        borderRadius: 12,
        paddingVertical: 12,
        flex: 1.2,
        marginHorizontal: 10,
    },
    servoCenterText: {
        color: '#FFF',
        fontSize: 15,
        fontWeight: '700',
        marginLeft: 6,
    },
    servoPresetRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginBottom: 14,
    },
    servoPresetBtn: {
        flex: 1,
        paddingVertical: 10,
        marginHorizontal: 3,
        borderRadius: 10,
        backgroundColor: '#F5F5F5',
        borderWidth: 1,
        borderColor: '#E0E0E0',
        alignItems: 'center',
    },
    servoPresetActive: {
        backgroundColor: '#2196F3',
        borderColor: '#2196F3',
    },
    servoPresetText: {
        fontSize: 13,
        fontWeight: '700',
        color: '#616161',
    },
    servoPresetTextActive: {
        color: '#FFF',
    },
});
