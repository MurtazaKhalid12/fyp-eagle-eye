import React, { useState } from 'react';
import { View, FlatList, StyleSheet, Text, ActivityIndicator, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAlerts } from '../hooks/useAlerts';
import ImageCard from '../components/ImageCard';
import ImageDetailModal from '../components/ImageDetailModal';

export default function GalleryScreen() {
    const { alerts, loading, deleteAlert } = useAlerts();
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

    if (loading) {
        return (
            <View style={styles.center}>
                <ActivityIndicator size="large" color="#E53935" />
            </View>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <Text style={styles.header}>EagleEye Alerts</Text>
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
    header: {
        fontSize: 28,
        fontWeight: 'bold',
        color: '#333',
        paddingHorizontal: 20,
        marginBottom: 20,
        marginTop: 10,
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
