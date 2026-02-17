import React from 'react';
import { View, Text, StyleSheet, Dimensions, TouchableOpacity, Alert } from 'react-native';
import { Image } from 'expo-image';

const { width } = Dimensions.get('window');

export default function ImageCard({ imageUrl, timestamp, alertId, onDelete, onPress }) {
    // Format timestamp (assuming unix timestamp in seconds)
    const date = new Date(timestamp * 1000);
    const dateString = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();

    const handleDelete = () => {
        Alert.alert(
            'Delete Alert',
            'Are you sure you want to delete this alert?',
            [
                { text: 'Cancel', style: 'cancel' },
                {
                    text: 'Delete',
                    style: 'destructive',
                    onPress: () => onDelete(alertId)
                }
            ]
        );
    };

    return (
        <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.9}>
            <Image
                source={{ uri: imageUrl }}
                style={styles.image}
                contentFit="cover"
                transition={200}
                cachePolicy="disk"
            />
            <View style={styles.info}>
                <View style={styles.infoRow}>
                    <View style={styles.textContainer}>
                        <Text style={styles.timestamp}>{dateString}</Text>
                        <Text style={styles.alertText}>Human Detected</Text>
                    </View>
                    <TouchableOpacity
                        style={styles.deleteButton}
                        onPress={handleDelete}
                        activeOpacity={0.7}
                    >
                        <Text style={styles.deleteButtonText}>🗑️ Delete</Text>
                    </TouchableOpacity>
                </View>
            </View>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    card: {
        backgroundColor: 'white',
        borderRadius: 12,
        marginBottom: 16,
        overflow: 'hidden',
        elevation: 3,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
        width: width * 0.9,
        alignSelf: 'center',
    },
    image: {
        width: '100%',
        height: 250,
    },
    info: {
        padding: 12,
    },
    timestamp: {
        fontSize: 14,
        color: '#666',
    },
    alertText: {
        fontSize: 18,
        fontWeight: 'bold',
        color: '#E53935',
        marginTop: 4,
    },
    infoRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
    },
    textContainer: {
        flex: 1,
    },
    deleteButton: {
        backgroundColor: '#E53935',
        paddingHorizontal: 12,
        paddingVertical: 8,
        borderRadius: 6,
        marginLeft: 10,
    },
    deleteButtonText: {
        color: 'white',
        fontSize: 14,
        fontWeight: '600',
    },
});
