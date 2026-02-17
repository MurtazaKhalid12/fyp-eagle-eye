import { useEffect, useState } from 'react';
import { ref, onValue, query, orderByChild, limitToLast, remove, push } from 'firebase/database';
import { database } from '../config/firebaseConfig';

export function useAlerts() {
    const [alerts, setAlerts] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const alertsRef = ref(database, 'alerts');
        // Limit to last 50 to avoid loading too many images
        const alertsQuery = query(alertsRef, orderByChild('timestamp'), limitToLast(50));

        const unsubscribe = onValue(alertsQuery, (snapshot) => {
            const data = snapshot.val();
            if (data) {
                // Convert object to array and reverse (newest first)
                const alertsList = Object.entries(data).map(([key, value]) => ({
                    id: key,
                    ...value
                })).sort((a, b) => b.timestamp - a.timestamp);
                setAlerts(alertsList);
            } else {
                setAlerts([]);
            }
            setLoading(false);
        }, (error) => {
            console.error("Firebase Read Error:", error);
            setLoading(false);
            // Optional: You could set an error state here to show in the UI
        });

        return () => unsubscribe();
    }, []);

    const deleteAlert = async (alertId) => {
        try {
            // Find the alert in the current state to get public_id
            const alertToDelete = alerts.find(a => a.id === alertId);

            // If it has a public_id (new records), queue it for deletion from Cloudinary
            if (alertToDelete && alertToDelete.public_id) {
                const cleanupRef = ref(database, 'deletion_requests');
                await push(cleanupRef, { public_id: alertToDelete.public_id });
                console.log('Queued for Cloudinary deletion:', alertToDelete.public_id);
            }

            const alertRef = ref(database, `alerts/${alertId}`);
            await remove(alertRef);
            console.log('Alert deleted:', alertId);
        } catch (error) {
            console.error('Error deleting alert:', error);
            throw error;
        }
    };

    return { alerts, loading, deleteAlert };
}
