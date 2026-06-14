/*
 * EagleEye Vision — on-device human-detection library for the ESP32-CAM.
 *
 * Public API for the EagleEye detector: 96x96 RGB, INT8, ESP-NN accelerated.
 * The model is EagleEye's own (trained by the EagleEye team). The int8
 * inference runtime under src/edge-impulse-sdk/ is TensorFlow Lite Micro
 * (Google) + ESP-NN (Espressif); see the LICENSE files in that folder for
 * the upstream attribution.
 */

#ifndef _EAGLEEYE_VISION_H
#define _EAGLEEYE_VISION_H

// Undefine min/max macros as these conflict with C++ std min/max functions
// these are often included by Arduino cores
#include <Arduino.h>
#include <stdarg.h>
#ifdef min
#undef min
#endif // min
#ifdef max
#undef max
#endif // max
#ifdef round
#undef round
#endif // round
// Similar the ESP32 seems to define this, which is also used as an enum value in TFLite
#ifdef DEFAULT
#undef DEFAULT
#endif // DEFAULT
// Infineon core defines this, conflicts with CMSIS/DSP/Include/dsp/controller_functions.h
#ifdef A0
#undef A0
#endif // A0
#ifdef A1
#undef A1
#endif // A1
#ifdef A2
#undef A2
#endif // A2

/* Includes ---------------------------------------------------------------- */
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"
#include "edge-impulse-sdk/dsp/numpy.hpp"
#include "model-parameters/model_metadata.h"
#include "edge-impulse-sdk/classifier/ei_classifier_smooth.h"

extern void ei_printf(const char *format, ...);

#endif // _EAGLEEYE_VISION_H
