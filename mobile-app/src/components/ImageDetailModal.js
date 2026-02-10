import React from 'react';
import {
    Modal,
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Dimensions,
    ActivityIndicator,
    ScrollView,
} from 'react-native';
import { Image } from 'expo-image';

const { width, height } = Dimensions.get('window');

export default function ImageDetailModal({ visible, onClose, imageUrl, timestamp }) {
    const [imageLoading, setImageLoading] = React.useState(true);

    const date = new Date(timestamp * 1000);
    const dateString = date.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
    const timeString = date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit'
    });

    return (
        <Modal
            visible={visible}
            animationType="fade"
            onRequestClose={onClose}
            statusBarTranslucent
        >
            <View style={styles.container}>
                {/* Header */}
                <View style={styles.header}>
                    <TouchableOpacity onPress={onClose} style={styles.closeButton}>
                        <Text style={styles.closeButtonText}>✕</Text>
                    </TouchableOpacity>
                    <Text style={styles.headerTitle}>Alert Details</Text>
                    <View style={styles.placeholder} />
                </View>

                {/* Image Container */}
                <ScrollView
                    contentContainerStyle={styles.scrollContent}
                    showsVerticalScrollIndicator={false}
                >
                    <View style={styles.imageContainer}>
                        {imageLoading && (
                            <ActivityIndicator
                                size="large"
                                color="#E53935"
                                style={styles.loader}
                            />
                        )}
                        <Image
                            source={{ uri: imageUrl }}
                            style={styles.image}
                            contentFit="contain"
                            transition={300}
                            onLoadStart={() => setImageLoading(true)}
                            onLoadEnd={() => setImageLoading(false)}
                            onError={(e) => {
                                console.error('Image load error:', e);
                                setImageLoading(false);
                            }}
                        />
                    </View>

                    {/* Alert Info Card */}
                    <View style={styles.infoCard}>
                        <View style={styles.alertBadge}>
                            <Text style={styles.alertBadgeText}>🚨 INTRUSION DETECTED</Text>
                        </View>

                        <View style={styles.infoRow}>
                            <Text style={styles.infoLabel}>Date</Text>
                            <Text style={styles.infoValue}>{dateString}</Text>
                        </View>

                        <View style={styles.divider} />

                        <View style={styles.infoRow}>
                            <Text style={styles.infoLabel}>Time</Text>
                            <Text style={styles.infoValue}>{timeString}</Text>
                        </View>

                        <View style={styles.divider} />

                        <View style={styles.infoRow}>
                            <Text style={styles.infoLabel}>Detection Type</Text>
                            <Text style={styles.infoValue}>Human Presence</Text>
                        </View>

                        <View style={styles.divider} />

                        <View style={styles.infoRow}>
                            <Text style={styles.infoLabel}>Status</Text>
                            <View style={styles.statusBadge}>
                                <View style={styles.statusDot} />
                                <Text style={styles.statusText}>Recorded</Text>
                            </View>
                        </View>
                    </View>
                </ScrollView>
            </View>
        </Modal>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#0a0a0a',
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingHorizontal: 20,
        paddingTop: 50,
        paddingBottom: 15,
        backgroundColor: '#1a1a1a',
        borderBottomWidth: 1,
        borderBottomColor: '#333',
    },
    closeButton: {
        width: 40,
        height: 40,
        borderRadius: 20,
        backgroundColor: '#333',
        justifyContent: 'center',
        alignItems: 'center',
    },
    closeButtonText: {
        color: '#fff',
        fontSize: 24,
        fontWeight: '300',
    },
    headerTitle: {
        color: '#fff',
        fontSize: 18,
        fontWeight: '600',
        letterSpacing: 0.5,
    },
    placeholder: {
        width: 40,
    },
    scrollContent: {
        paddingBottom: 30,
    },
    imageContainer: {
        width: width,
        height: height * 0.5,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: '#000',
    },
    image: {
        width: '100%',
        height: '100%',
    },
    loader: {
        position: 'absolute',
    },
    infoCard: {
        margin: 20,
        backgroundColor: '#1a1a1a',
        borderRadius: 16,
        padding: 20,
        borderWidth: 1,
        borderColor: '#333',
    },
    alertBadge: {
        backgroundColor: '#E53935',
        paddingHorizontal: 16,
        paddingVertical: 10,
        borderRadius: 8,
        alignSelf: 'flex-start',
        marginBottom: 20,
    },
    alertBadgeText: {
        color: '#fff',
        fontSize: 14,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    infoRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingVertical: 12,
    },
    infoLabel: {
        color: '#888',
        fontSize: 14,
        fontWeight: '500',
    },
    infoValue: {
        color: '#fff',
        fontSize: 14,
        fontWeight: '600',
        flex: 1,
        textAlign: 'right',
    },
    divider: {
        height: 1,
        backgroundColor: '#333',
    },
    statusBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#2a2a2a',
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 12,
    },
    statusDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
        backgroundColor: '#4CAF50',
        marginRight: 6,
    },
    statusText: {
        color: '#4CAF50',
        fontSize: 13,
        fontWeight: '600',
    },
});
