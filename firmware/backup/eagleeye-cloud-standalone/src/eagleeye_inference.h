#pragma once
#include <stdint.h>
#include <stdbool.h>

// EagleEye v7.16 — standalone TFLite Micro inference wrapper.
// Uses model_data.h/.cpp; no Edge Impulse SDK needed at call site.
//
// Labels: index 0 = human, index 1 = nonhuman  (matches model output order)

#define EE_LABEL_HUMAN    0
#define EE_LABEL_NONHUMAN 1

#ifdef __cplusplus
extern "C" {
#endif

// Call once from setup(). Returns false if the model fails to load.
bool eagleeye_init();

// Run inference on a 96×96 RGB888 frame (27648 bytes, row-major, no padding).
// Scores are in [0.0, 1.0]. Returns false on interpreter error.
bool eagleeye_classify(const uint8_t *rgb888,
                       float *human_score_out,
                       float *nonhuman_score_out);

#ifdef __cplusplus
}
#endif
