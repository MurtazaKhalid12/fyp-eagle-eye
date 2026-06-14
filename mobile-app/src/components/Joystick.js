// ============================================================
//  EagleEye — 2D position pad (pan / tilt aim)
// ============================================================
//  An ABSOLUTE, sticky aim pad (not a spring-return stick): the knob's
//  position maps directly to the two servo angles and STAYS where you leave
//  it, so the camera holds its aim. Touch anywhere in the circle and the knob
//  jumps to your finger and follows it.
//
//  onMove(nx, ny) fires continuously while dragging, NORMALISED to [-1, 1]:
//      nx: -1 = full left,  +1 = full right
//      ny: -1 = full up,    +1 = full down   (screen coordinates)
//  onRelease() fires when you lift off (knob stays put).
//
//  Imperative API (via ref): setNormalized(nx, ny) moves the knob (e.g. the
//  Center button springs it back to the middle).
//
//  Inside a ScrollView, onPanResponderTerminationRequest:()=>false +
//  onShouldBlockNativeResponder:()=>true are what stop the scroll view from
//  stealing the drag.
// ============================================================

import React, { useRef, forwardRef, useImperativeHandle } from 'react';
import { View, StyleSheet, PanResponder, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const Joystick = forwardRef(function Joystick(
    { size = 240, knobSize = 78, onMove, onRelease },
    ref,
) {
    const radius = size / 2;
    const maxDist = radius - knobSize / 2;            // knob center travel limit
    const pos = useRef(new Animated.ValueXY({ x: 0, y: 0 })).current;   // pixel offset, animated (no re-render)

    const clampToCircle = (dx, dy) => {
        const d = Math.hypot(dx, dy);
        if (d <= maxDist || d === 0) return { x: dx, y: dy };
        const k = maxDist / d;
        return { x: dx * k, y: dy * k };
    };

    // locationX/Y are relative to the base; center is (radius, radius).
    const setFromTouch = (e) => {
        const { x, y } = clampToCircle(
            e.nativeEvent.locationX - radius,
            e.nativeEvent.locationY - radius,
        );
        pos.setValue({ x, y });
        if (onMove) onMove(x / maxDist, y / maxDist);
    };

    useImperativeHandle(ref, () => ({
        // Move the knob to a normalised position (e.g. (0,0) = center).
        setNormalized(nx, ny) {
            Animated.spring(pos, {
                toValue: { x: nx * maxDist, y: ny * maxDist },
                useNativeDriver: false, friction: 7, tension: 100,
            }).start();
        },
    }));

    const responder = useRef(
        PanResponder.create({
            onStartShouldSetPanResponder: () => true,
            onMoveShouldSetPanResponder: () => true,
            onPanResponderTerminationRequest: () => false,   // don't yield the drag to the ScrollView
            onShouldBlockNativeResponder: () => true,
            onPanResponderGrant: setFromTouch,
            onPanResponderMove: setFromTouch,
            onPanResponderRelease: () => { if (onRelease) onRelease(); },   // sticky: knob stays put
            onPanResponderTerminate: () => { if (onRelease) onRelease(); },
        }),
    ).current;

    return (
        <View
            style={[styles.base, { width: size, height: size, borderRadius: radius }]}
            {...responder.panHandlers}
        >
            <View pointerEvents="none" style={[styles.hLine, { width: size * 0.7 }]} />
            <View pointerEvents="none" style={[styles.vLine, { height: size * 0.7 }]} />
            <Animated.View
                pointerEvents="none"
                style={[
                    styles.knob,
                    { width: knobSize, height: knobSize, borderRadius: knobSize / 2 },
                    { transform: pos.getTranslateTransform() },
                ]}
            >
                <Ionicons name="videocam" size={26} color="#FFF" />
            </Animated.View>
        </View>
    );
});

export default Joystick;

const styles = StyleSheet.create({
    base: {
        backgroundColor: '#ECEFF1', alignItems: 'center', justifyContent: 'center',
        borderWidth: 2, borderColor: '#CFD8DC', alignSelf: 'center',
    },
    hLine: { position: 'absolute', height: 2, backgroundColor: '#CFD8DC' },
    vLine: { position: 'absolute', width: 2, backgroundColor: '#CFD8DC' },
    knob: {
        backgroundColor: '#2196F3', alignItems: 'center', justifyContent: 'center',
        borderWidth: 4, borderColor: '#FFF', elevation: 5,
        shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 6, shadowOffset: { width: 0, height: 3 },
    },
});
