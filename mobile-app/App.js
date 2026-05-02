import { StatusBar } from 'expo-status-bar';
import { StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import GalleryScreen from './src/screens/GalleryScreen';
import DashboardScreen from './src/screens/DashboardScreen';
import IntrusionStatsScreen from './src/screens/IntrusionStatsScreen';
import LiveMonitorScreen from './src/screens/LiveMonitorScreen';

const Tab = createBottomTabNavigator();

export default function App() {
    return (
        <SafeAreaProvider>
            <NavigationContainer>
                <Tab.Navigator
                    screenOptions={({ route }) => ({
                        headerShown: false,
                        tabBarIcon: ({ focused, color, size }) => {
                            let iconName;

                            if (route.name === 'Dashboard') {
                                iconName = focused ? 'home' : 'home-outline';
                            } else if (route.name === 'Stats') {
                                iconName = focused ? 'stats-chart' : 'stats-chart-outline';
                            } else if (route.name === 'Gallery') {
                                iconName = focused ? 'images' : 'images-outline';
                            } else if (route.name === 'Live') {
                                iconName = focused ? 'videocam' : 'videocam-outline';
                            }

                            return <Ionicons name={iconName} size={size} color={color} />;
                        },
                        tabBarActiveTintColor: '#D32F2F',
                        tabBarInactiveTintColor: 'gray',
                    })}
                >
                    <Tab.Screen name="Dashboard" component={DashboardScreen} />
                    <Tab.Screen name="Stats" component={IntrusionStatsScreen} />
                    <Tab.Screen name="Live" component={LiveMonitorScreen} />
                    <Tab.Screen name="Gallery" component={GalleryScreen} />
                </Tab.Navigator>
            </NavigationContainer>
            <StatusBar style="auto" />
        </SafeAreaProvider>
    );
}
