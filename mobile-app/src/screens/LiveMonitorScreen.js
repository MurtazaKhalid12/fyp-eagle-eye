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

    useEffect(() => {
        streamingRef.current = isStreaming;
    }, [isStreaming]);

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
});
