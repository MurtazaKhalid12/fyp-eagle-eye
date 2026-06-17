#pragma once
#include <stdint.h>

// EagleEye v7.16 — INT8 TFLite flatbuffer (96×96 RGB, 2-class)
#define EAGLEEYE_MODEL_VERSION   716
#define EAGLEEYE_INPUT_WIDTH     96
#define EAGLEEYE_INPUT_HEIGHT    96
#define EAGLEEYE_INPUT_CHANNELS  3
#define EAGLEEYE_LABEL_COUNT     2
#define EAGLEEYE_ARENA_SIZE      126361

extern const uint8_t  eagleeye_model_data[];
extern const uint32_t eagleeye_model_data_len;
