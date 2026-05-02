import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, KeyboardAvoidingView, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { WebView } from 'react-native-webview';

export default function LiveMonitorScreen() {
    const [ipAddress, setIpAddress] = useState('192.168.100.');
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);

    const toggleStream = async () => {
        if (isStreaming) {
            setIsStreaming(false);
            return;
        }

        if (!ipAddress.trim()) {
            alert("Please enter the ESP32 Camera IP address.");
            return;
        }
        
        setIsLoading(true);
        setIsStreaming(true);
        
        // Hide loader after a brief moment assuming the stream starts loading
        setTimeout(() => setIsLoading(false), 1500);
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

            <KeyboardAvoidingView 
                behavior={Platform.OS === "ios" ? "padding" : "height"}
                style={styles.content}
            >
                {/* Video Stream Container */}
                <View style={styles.streamContainer}>
                    {isStreaming ? (
                        <>
                            {isLoading && (
                                <View style={styles.loaderContainer}>
                                    <ActivityIndicator size="large" color="#2196F3" />
                                    <Text style={styles.loaderText}>Connecting to Camera...</Text>
                                </View>
                            )}
                            <WebView 
                                source={{ html: `
                                    <html>
                                    <body style="margin:0;padding:0;background-color:black;display:flex;justify-content:center;align-items:center;">
                                        <img src="http://${ipAddress.trim()}/" style="width:100%; height:100%; object-fit:contain;" />
                                    </body>
                                    </html>
                                ` }} 
                                style={styles.streamImage}
                                scrollEnabled={false}
                                showsVerticalScrollIndicator={false}
                                showsHorizontalScrollIndicator={false}
                            />
                        </>
                    ) : (
                        <View style={styles.offlineContainer}>
                            <Ionicons name="videocam-off" size={64} color="#BDBDBD" />
                            <Text style={styles.offlineText}>Stream is currently paused.</Text>
                            <Text style={styles.offlineSubText}>Press connect to view live feed.</Text>
                        </View>
                    )}
                </View>

                {/* Controls */}
                <View style={styles.controlsCard}>
                    <Text style={styles.inputLabel}>ESP32-CAM IP Address</Text>
                    <View style={styles.inputRow}>
                        <Ionicons name="wifi" size={20} color="#757575" style={styles.inputIcon} />
                        <TextInput
                            style={styles.input}
                            placeholder="e.g., 192.168.100.15"
                            value={ipAddress}
                            onChangeText={setIpAddress}
                            keyboardType="numeric"
                            autoCapitalize="none"
                            autoCorrect={false}
                        />
                    </View>

                    <TouchableOpacity 
                        style={[styles.button, isStreaming ? styles.buttonStop : styles.buttonStart]} 
                        onPress={toggleStream}
                        activeOpacity={0.8}
                    >
                        <Ionicons name={isStreaming ? "stop" : "play"} size={20} color="#FFF" />
                        <Text style={styles.buttonText}>
                            {isStreaming ? "Stop Live View" : "Start Live View"}
                        </Text>
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
        aspectRatio: 4/3,
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
    streamImage: {
        width: '100%',
        height: '100%',
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
        marginBottom: 20,
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
    buttonText: {
        color: '#FFF',
        fontSize: 16,
        fontWeight: 'bold',
        marginLeft: 8,
    }
});
