import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Switch, TouchableOpacity, ScrollView, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue, set, query, orderByChild, limitToLast } from 'firebase/database';
import { database } from '../config/firebaseConfig';

export default function DashboardScreen({ navigation }) {
    const [isArmed, setIsArmed] = useState(true);
    const [systemStatus, setSystemStatus] = useState('OFFLINE');
    const [latestAlert, setLatestAlert] = useState(null);

    useEffect(() => {
        // 1. Listen for System Arm Status
        const armRef = ref(database, 'config/armed');
        const unsubArm = onValue(armRef, (snapshot) => {
            setIsArmed(snapshot.exists() ? snapshot.val() : true);
        });

        // 2. Listen for System Heartbeat (determined by checking a timestamp, mock for now or real if implemented)
        // For now, we'll assume online if we can read DB. In a real app, the python bridge should write to 'status/heartbeat'
        const statusRef = ref(database, 'status/heartbeat');
        const unsubStatus = onValue(statusRef, (snapshot) => {
            if (snapshot.exists()) {
                const lastHeartbeat = snapshot.val();
                const now = Date.now() / 1000;
                // If heartbeat is within last 2 minutes, it's online
                if (now - lastHeartbeat < 120) {
                    setSystemStatus('ONLINE');
                } else {
                    setSystemStatus('OFFLINE');
                }
            }
        });

        // 3. Get Latest Alert
        const alertsRef = ref(database, 'alerts');
        const latestQuery = query(alertsRef, orderByChild('timestamp'), limitToLast(1));
        const unsubAlert = onValue(latestQuery, (snapshot) => {
            if (snapshot.exists()) {
                const data = snapshot.val();
                const key = Object.keys(data)[0];
                setLatestAlert({ id: key, ...data[key] });
            }
        });

        return () => {
            unsubArm();
            unsubStatus();
            unsubAlert();
        };
    }, []);

    const toggleArm = () => {
        const newValue = !isArmed;
        set(ref(database, 'config/armed'), newValue);
        setIsArmed(newValue);
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.scrollContent}>

                {/* Header */}
                <View style={styles.header}>
                    <Text style={styles.headerTitle}>EagleEye Control</Text>
                    <View style={[styles.statusBadge, { backgroundColor: systemStatus === 'ONLINE' ? '#E8F5E9' : '#FFEBEE' }]}>
                        <View style={[styles.statusDot, { backgroundColor: systemStatus === 'ONLINE' ? '#4CAF50' : '#F44336' }]} />
                        <Text style={[styles.statusText, { color: systemStatus === 'ONLINE' ? '#2E7D32' : '#C62828' }]}>
                            {systemStatus}
                        </Text>
                    </View>
                </View>

                {/* System Control Card */}
                <View style={styles.card}>
                    <View style={styles.cardHeader}>
                        <Ionicons name="shield-checkmark" size={24} color="#1976D2" />
                        <Text style={styles.cardTitle}>System Status</Text>
                    </View>
                    <View style={styles.controlRow}>
                        <View>
                            <Text style={styles.controlLabel}>Surveillance System</Text>
                            <Text style={styles.controlSubtext}>
                                {isArmed ? 'System is active and monitoring' : 'Monitoring is paused'}
                            </Text>
                        </View>
                        <Switch
                            trackColor={{ false: "#767577", true: "#81b0ff" }}
                            thumbColor={isArmed ? "#2196F3" : "#f4f3f4"}
                            ios_backgroundColor="#3e3e3e"
                            onValueChange={toggleArm}
                            value={isArmed}
                        />
                    </View>
                </View>

                {/* Monitoring Stats Grid */}
                <View style={styles.gridContainer}>
                    <View style={styles.gridCard}>
                        <Ionicons name="wifi" size={24} color="#666" />
                        <Text style={styles.gridValue}>2.4</Text>
                        <Text style={styles.gridLabel}>GHz WiFi</Text>
                    </View>
                    <View style={styles.gridCard}>
                        <Ionicons name="battery-charging" size={24} color="#666" />
                        <Text style={styles.gridValue}>100%</Text>
                        <Text style={styles.gridLabel}>Power</Text>
                    </View>
                    {/* Placeholder for future sensor data */}
                    <View style={styles.gridCard}>
                        <Ionicons name="thermometer" size={24} color="#666" />
                        <Text style={styles.gridValue}>--°</Text>
                        <Text style={styles.gridLabel}>Temp</Text>
                    </View>
                </View>

                {/* Latest Alert Preview */}
                <View style={styles.card}>
                    <View style={styles.cardHeader}>
                        <Ionicons name="warning" size={24} color="#E53935" />
                        <Text style={styles.cardTitle}>Latest Intrusion</Text>
                    </View>

                    {latestAlert ? (
                        <TouchableOpacity onPress={() => navigation.navigate('Gallery')}>
                            <Image
                                source={{ uri: latestAlert.image_url }}
                                style={styles.previewImage}
                                resizeMode="cover"
                            />
                            <View style={styles.alertInfo}>
                                <Text style={styles.alertTime}>
                                    {new Date(latestAlert.timestamp * 1000).toLocaleString()}
                                </Text>
                                <Text style={styles.alertType}>Human Detected</Text>
                            </View>
                        </TouchableOpacity>
                    ) : (
                        <View style={styles.emptyState}>
                            <Text style={styles.emptyText}>No recent alerts</Text>
                        </View>
                    )}
                </View>

            </ScrollView>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#F7F8FA',
    },
    scrollContent: {
        padding: 20,
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 24,
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
    card: {
        backgroundColor: '#FFFFFF',
        borderRadius: 16,
        padding: 20,
        marginBottom: 20,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 10,
        elevation: 3,
    },
    cardHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 16,
    },
    cardTitle: {
        fontSize: 18,
        fontWeight: '600',
        color: '#333',
        marginLeft: 10,
    },
    controlRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
    },
    controlLabel: {
        fontSize: 16,
        fontWeight: '600',
        color: '#333',
    },
    controlSubtext: {
        fontSize: 13,
        color: '#888',
        marginTop: 4,
    },
    gridContainer: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginBottom: 20,
    },
    gridCard: {
        backgroundColor: '#FFFFFF',
        width: '31%',
        borderRadius: 12,
        padding: 15,
        alignItems: 'center',
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.03,
        shadowRadius: 5,
        elevation: 2,
    },
    gridValue: {
        fontSize: 16,
        fontWeight: 'bold',
        color: '#333',
        marginTop: 8,
    },
    gridLabel: {
        fontSize: 12,
        color: '#888',
        marginTop: 2,
    },
    previewImage: {
        width: '100%',
        height: 180,
        borderRadius: 12,
        marginBottom: 12,
        backgroundColor: '#EEE',
    },
    alertInfo: {
        flexDirection: 'row',
        justifyContent: 'space-between',
    },
    alertTime: {
        fontSize: 14,
        color: '#555',
        fontWeight: '500',
    },
    alertType: {
        fontSize: 14,
        color: '#E53935',
        fontWeight: 'bold',
    },
    emptyState: {
        height: 100,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: '#F5F5F5',
        borderRadius: 12,
    },
    emptyText: {
        color: '#AAA',
        fontSize: 14,
    }
});
