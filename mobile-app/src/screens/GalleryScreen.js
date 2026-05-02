import React, { useState } from 'react';
import { View, FlatList, StyleSheet, Text, ActivityIndicator, Alert, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAlerts } from '../hooks/useAlerts';
import ImageCard from '../components/ImageCard';
import ImageDetailModal from '../components/ImageDetailModal';

export default function GalleryScreen() {
    const { alerts, loading, deleteAlert, deleteAllAlerts } = useAlerts();
    const [deletingAll, setDeletingAll] = useState(false);
    const [selectedAlert, setSelectedAlert] = useState(null);
    const [modalVisible, setModalVisible] = useState(false);

    const handleDelete = async (alertId) => {
        try {
            await deleteAlert(alertId);
        } catch (error) {
            Alert.alert('Error', 'Failed to delete alert. Please try again.');
        }
    };

    const handleImagePress = (alert) => {
        setSelectedAlert(alert);
        setModalVisible(true);
    };

    const handleCloseModal = () => {
        setModalVisible(false);
        setSelectedAlert(null);
    };

    const confirmDeleteAll = () => {
        if (alerts.length === 0) return;
        Alert.alert(
            'Delete all pictures',
            `Remove all ${alerts.length} alert(s) from the app and queue Cloudinary cleanup? This cannot be undone.`,
            [
                { text: 'Cancel', style: 'cancel' },
                {
                    text: 'Delete all',
                    style: 'destructive',
                    onPress: async () => {
                        setDeletingAll(true);
                        try {
                            await deleteAllAlerts();
                            handleCloseModal();
                        } catch {
                            Alert.alert('Error', 'Could not delete all alerts. Try again.');
                        } finally {
                            setDeletingAll(false);
                        }
                    },
                },
            ],
        );
    };

    if (loading) {
        return (
            <View style={styles.center}>
                <ActivityIndicator size="large" color="#E53935" />
            </View>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.headerRow}>
                <Text style={styles.header}>EagleEye Alerts</Text>
                {alerts.length > 0 ? (
                    <TouchableOpacity
                        style={styles.deleteAllBtn}
                        onPress={confirmDeleteAll}
                        disabled={deletingAll}
                        activeOpacity={0.7}
                    >
                        {deletingAll ? (
                            <ActivityIndicator size="small" color="#C62828" />
                        ) : (
                            <>
                                <Ionicons name="trash-outline" size={20} color="#C62828" />
                                <Text style={styles.deleteAllText}>Delete all</Text>
                            </>
                        )}
                    </TouchableOpacity>
                ) : null}
            </View>
            <FlatList
                data={alerts}
                keyExtractor={(item) => item.id}
                renderItem={({ item }) => (
                    <ImageCard
                        imageUrl={item.image_url}
                        timestamp={item.timestamp}
                        alertId={item.id}
                        onDelete={handleDelete}
                        onPress={() => handleImagePress(item)}
                    />
                )}
                contentContainerStyle={styles.list}
                ListEmptyComponent={
                    <Text style={styles.emptyText}>No intrusions detected yet.</Text>
                }
            />

            {selectedAlert && (
                <ImageDetailModal
                    visible={modalVisible}
                    onClose={handleCloseModal}
                    imageUrl={selectedAlert.image_url}
                    timestamp={selectedAlert.timestamp}
                />
            )}
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#F5F5F5',
        paddingTop: 10,
    },
    headerRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: 20,
        marginBottom: 16,
        marginTop: 10,
    },
    header: {
        fontSize: 28,
        fontWeight: 'bold',
        color: '#333',
        flex: 1,
    },
    deleteAllBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: 10,
        backgroundColor: '#FFEBEE',
        borderWidth: 1,
        borderColor: '#FFCDD2',
    },
    deleteAllText: {
        color: '#C62828',
        fontSize: 14,
        fontWeight: '600',
    },
    list: {
        paddingBottom: 20,
    },
    center: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    emptyText: {
        textAlign: 'center',
        marginTop: 50,
        color: '#888',
        fontSize: 16,
    }
});
