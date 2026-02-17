import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Dimensions, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { LineChart, BarChart } from 'react-native-chart-kit';
import { ref, onValue, query, orderByChild } from 'firebase/database';
import { database } from '../config/firebaseConfig';

const screenWidth = Dimensions.get("window").width;

export default function IntrusionStatsScreen() {
    const [selectedPeriod, setSelectedPeriod] = useState('Daily'); // 'Daily', 'Weekly', 'Monthly'
    const [chartData, setChartData] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [totalIntrusions, setTotalIntrusions] = useState(0);

    useEffect(() => {
        const alertsRef = ref(database, 'alerts');
        // Fetch last 1000 alerts (should cover a month easily unless extremely high activity)
        // If query is huge, consider limitToLast or filtering serverside, but realtime DB is limited.
        // We'll fetch all sorted by timestamp locally.
        const alertsQuery = query(alertsRef, orderByChild('timestamp'));

        const unsubscribe = onValue(alertsQuery, (snapshot) => {
            if (snapshot.exists()) {
                const data = snapshot.val();
                processData(data, selectedPeriod);
            } else {
                setChartData(null);
                setTotalIntrusions(0);
                setIsLoading(false);
            }
        });

        return () => unsubscribe();
    }, [selectedPeriod]);

    const processData = (data, period) => {
        const now = new Date();
        const alerts = Object.values(data).map(alert => ({
            ...alert,
            date: new Date(alert.timestamp * 1000)
        }));

        let labels = [];
        let counts = [];
        let filteredAlerts = [];

        if (period === 'Daily') {
            // Last 24 hours stats
            // We group into 3-hour intervals: 0-3, 3-6, ... 21-24
            const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            filteredAlerts = alerts.filter(a => a.date >= startOfDay);

            const hours = Array(24).fill(0);
            filteredAlerts.forEach(a => {
                const hour = a.date.getHours();
                if (hour >= 0 && hour < 24) {
                    hours[hour]++;
                }
            });

            // Group into 3-hour blocks (8 bars total)
            const grouped = Array(8).fill(0);
            hours.forEach((count, h) => {
                // h=0,1,2 -> index 0
                // ...
                // h=21,22,23 -> index 7
                const index = Math.floor(h / 3);
                if (index < 8) grouped[index] += count;
            });
            counts = grouped;
            labels = ["00h", "03h", "06h", "09h", "12h", "15h", "18h", "21h"];

        } else if (period === 'Weekly') {
            // Last 7 days (rolling)
            const weekAgo = new Date(now);
            weekAgo.setDate(now.getDate() - 6);
            weekAgo.setHours(0, 0, 0, 0);

            filteredAlerts = alerts.filter(a => a.date >= weekAgo);

            const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            const dayCounts = Array(7).fill(0);
            const dayLabels = [];

            for (let i = 0; i < 7; i++) {
                const d = new Date(weekAgo);
                d.setDate(weekAgo.getDate() + i);
                dayLabels.push(days[d.getDay()]);

                const start = new Date(d);
                start.setHours(0, 0, 0, 0);
                const end = new Date(d);
                end.setHours(23, 59, 59, 999);

                dayCounts[i] = filteredAlerts.filter(a => a.date >= start && a.date <= end).length;
            }
            labels = dayLabels;
            counts = dayCounts;

        } else if (period === 'Monthly') {
            // Last 35 days (5 Weeks) to ensure full month coverage
            const monthAgo = new Date(now);
            monthAgo.setDate(now.getDate() - 34); // Go back 5 weeks
            monthAgo.setHours(0, 0, 0, 0);

            filteredAlerts = alerts.filter(a => a.date >= monthAgo);

            // Group by Week (5 weeks rolling)
            // Index 4 = Current Week, Index 0 = 5 weeks ago
            const weekCounts = [0, 0, 0, 0, 0];
            const weekLabels = ["Wk 1", "Wk 2", "Wk 3", "Wk 4", "Wk 5"]; // Compact labels

            filteredAlerts.forEach(a => {
                const diffTime = Math.abs(now - a.date);
                const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
                // diffDays 0-6 -> Week 5 (index 4)
                // diffDays 7-13 -> Week 4 (index 3)
                // ...
                // diffDays 28-34 -> Week 1 (index 0)

                const weekIndex = 4 - Math.floor(diffDays / 7);
                if (weekIndex >= 0 && weekIndex < 5) {
                    weekCounts[weekIndex]++;
                }
            });

            counts = weekCounts;
            labels = weekLabels;
        }

        setChartData({
            labels: labels,
            datasets: [{ data: counts }]
        });
        setTotalIntrusions(filteredAlerts.length);
        setIsLoading(false);
    };

    const renderChart = () => {
        if (!chartData) return null;

        // Dynamic width calculation:
        // Give each bar ~60px of breathing room.
        // If content is wider than screen, it becomes scrollable.
        // If content is smaller, it stretches to fit screen width (minWidth).
        const itemWidth = 60;
        const minWidth = screenWidth - 40;
        const computedWidth = chartData.labels.length * itemWidth;
        const chartWidth = Math.max(minWidth, computedWidth);

        return (
            <View style={styles.chartContainer}>
                <ScrollView
                    horizontal={true}
                    showsHorizontalScrollIndicator={false}
                    contentContainerStyle={{ paddingRight: 20 }} // Add some padding at the end
                >
                    <BarChart
                        data={chartData}
                        width={chartWidth}
                        height={220}
                        yAxisLabel=""
                        yAxisSuffix=""
                        fromZero={true}
                        chartConfig={{
                            backgroundColor: "#ffffff",
                            backgroundGradientFrom: "#ffffff",
                            backgroundGradientTo: "#ffffff",
                            decimalPlaces: 0,
                            color: (opacity = 1) => `rgba(211, 47, 47, ${opacity})`,
                            labelColor: (opacity = 1) => `rgba(0, 0, 0, ${opacity})`,
                            style: {
                                borderRadius: 16
                            },
                            barPercentage: 0.5,
                            propsForLabels: {
                                fontSize: 11, // Increased slightly for readability
                            },
                        }}
                        style={{
                            marginVertical: 8,
                            borderRadius: 16
                        }}
                        showValuesOnTopOfBars
                    />
                </ScrollView>
            </View>
        );
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.scrollContent}>
                <View style={styles.header}>
                    <Text style={styles.headerTitle}>Intrusion Analytics</Text>
                </View>

                {/* Period Selector */}
                <View style={styles.toggleContainer}>
                    {['Daily', 'Weekly', 'Monthly'].map((item) => (
                        <TouchableOpacity
                            key={item}
                            style={[
                                styles.toggleButton,
                                selectedPeriod === item && styles.toggleButtonActive
                            ]}
                            onPress={() => {
                                setIsLoading(true);
                                setSelectedPeriod(item);
                            }}
                        >
                            <Text style={[
                                styles.toggleText,
                                selectedPeriod === item && styles.toggleTextActive
                            ]}>
                                {item}
                            </Text>
                        </TouchableOpacity>
                    ))}
                </View>

                {/* Main Stats Card */}
                <View style={styles.card}>
                    <View style={styles.cardHeader}>
                        <Ionicons name="stats-chart" size={24} color="#D32F2F" />
                        <Text style={styles.cardTitle}>Overview ({selectedPeriod})</Text>
                    </View>

                    {isLoading ? (
                        <ActivityIndicator size="large" color="#D32F2F" style={{ margin: 20 }} />
                    ) : (
                        <>
                            <View style={styles.statsRow}>
                                <View style={styles.statItem}>
                                    <Text style={styles.statValue}>{totalIntrusions}</Text>
                                    <Text style={styles.statLabel}>Total Intrusions</Text>
                                </View>
                                <View style={styles.statItem}>
                                    <Text style={styles.statValue}>
                                        {chartData && chartData.datasets[0].data.length > 0
                                            ? Math.max(...chartData.datasets[0].data)
                                            : 0}
                                    </Text>
                                    <Text style={styles.statLabel}>Peak Count</Text>
                                </View>
                            </View>
                            {renderChart()}
                        </>
                    )}
                </View>

                {/* Additional Info / Legend */}
                <View style={styles.infoCard}>
                    <Ionicons name="information-circle-outline" size={24} color="#666" />
                    <Text style={styles.infoText}>
                        Data is aggregated in real-time from your sensor network.
                        {selectedPeriod === 'Daily' && " Showing activity breakdown for the last 24 hours."}
                        {selectedPeriod === 'Weekly' && " Showing activity for the last 7 days."}
                        {selectedPeriod === 'Monthly' && " Showing weekly trends for the last 30 days."}
                    </Text>
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
        marginBottom: 24,
    },
    headerTitle: {
        fontSize: 28,
        fontWeight: '800',
        color: '#1A1A1A',
    },
    toggleContainer: {
        flexDirection: 'row',
        backgroundColor: '#E0E0E0',
        borderRadius: 12,
        padding: 4,
        marginBottom: 24,
    },
    toggleButton: {
        flex: 1,
        paddingVertical: 10,
        alignItems: 'center',
        borderRadius: 10,
    },
    toggleButtonActive: {
        backgroundColor: '#FFFFFF',
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.1,
        shadowRadius: 2,
        elevation: 2,
    },
    toggleText: {
        fontSize: 14,
        fontWeight: '600',
        color: '#757575',
    },
    toggleTextActive: {
        color: '#D32F2F',
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
        marginBottom: 20,
    },
    cardTitle: {
        fontSize: 18,
        fontWeight: '600',
        color: '#333',
        marginLeft: 10,
    },
    statsRow: {
        flexDirection: 'row',
        justifyContent: 'space-around',
        marginBottom: 20,
    },
    statItem: {
        alignItems: 'center',
    },
    statValue: {
        fontSize: 32,
        fontWeight: 'bold',
        color: '#D32F2F',
    },
    statLabel: {
        fontSize: 12,
        color: '#888',
        marginTop: 4,
    },
    chartContainer: {
        alignItems: 'center',
        overflow: 'hidden', // Ensure chart doesn't bleed
    },
    infoCard: {
        flexDirection: 'row',
        backgroundColor: '#E3F2FD', // Light blue hint
        padding: 16,
        borderRadius: 12,
        alignItems: 'center',
    },
    infoText: {
        marginLeft: 12,
        color: '#1976D2',
        fontSize: 13,
        flex: 1,
        lineHeight: 18,
    },
});
