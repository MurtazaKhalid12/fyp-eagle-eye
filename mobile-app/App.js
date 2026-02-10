import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import GalleryScreen from './src/screens/GalleryScreen';

import { SafeAreaProvider } from 'react-native-safe-area-context';

export default function App() {
    return (
        <SafeAreaProvider>
            <View style={styles.container}>
                <StatusBar style="auto" />
                <GalleryScreen />
            </View>
        </SafeAreaProvider>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#ebe7e7ff',
    },
});
