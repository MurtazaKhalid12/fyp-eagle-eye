#include "eagleeye_inference.h"
#include "model_data.h"

// ESP-NN hardware-accelerated kernels (lib/ESP-NN).
// Including this header makes the library visible to the linker so TFLite
// Micro's ESP-NN-aware kernel implementations call the accelerated routines
// instead of the generic ANSI-C fallbacks.
#include <esp_nn.h>

// TFLite Micro headers — bundled inside lib/eagleeye_vision
#include "eagleeye-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "eagleeye-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "eagleeye-sdk/tensorflow/lite/micro/micro_error_reporter.h"
#include "eagleeye-sdk/tensorflow/lite/schema/schema_generated.h"

// Ops present in this model: Conv2D, DepthwiseConv2D, MaxPool2D,
// FullyConnected, Softmax, Reshape, Dequantize
static tflite::MicroMutableOpResolver<8> s_resolver;

static uint8_t s_arena[EAGLEEYE_ARENA_SIZE] __attribute__((aligned(16)));
static tflite::MicroInterpreter *s_interpreter = nullptr;

static bool s_initialised = false;

bool eagleeye_init()
{
    if (s_initialised) return true;

    const tflite::Model *model = tflite::GetModel(eagleeye_model_data);
    if (model->version() != TFLITE_SCHEMA_VERSION) return false;

    s_resolver.AddConv2D();
    s_resolver.AddDepthwiseConv2D();
    s_resolver.AddMaxPool2D();
    s_resolver.AddFullyConnected();
    s_resolver.AddSoftmax();
    s_resolver.AddReshape();
    s_resolver.AddDequantize();
    s_resolver.AddQuantize();

    static tflite::MicroInterpreter interp(model, s_resolver, s_arena, EAGLEEYE_ARENA_SIZE);
    s_interpreter = &interp;

    if (s_interpreter->AllocateTensors() != kTfLiteOk) {
        s_interpreter = nullptr;
        return false;
    }

    s_initialised = true;
    return true;
}

bool eagleeye_classify(const uint8_t *rgb888,
                       float *human_score_out,
                       float *nonhuman_score_out)
{
    if (!s_initialised || !s_interpreter) return false;

    TfLiteTensor *input = s_interpreter->input(0);

    // Model input is INT8: quantise RGB888 bytes → signed int8
    const float scale     = input->params.scale;
    const int   zero_pt   = input->params.zero_point;
    const int   n_pixels  = EAGLEEYE_INPUT_WIDTH * EAGLEEYE_INPUT_HEIGHT * EAGLEEYE_INPUT_CHANNELS;
    int8_t     *buf       = input->data.int8;

    for (int i = 0; i < n_pixels; i++) {
        int q = (int)((rgb888[i] / 255.0f) / scale + zero_pt + 0.5f);
        if (q < -128) q = -128;
        if (q >  127) q =  127;
        buf[i] = (int8_t)q;
    }

    if (s_interpreter->Invoke() != kTfLiteOk) return false;

    TfLiteTensor *output = s_interpreter->output(0);
    const float   os     = output->params.scale;
    const int     ozp    = output->params.zero_point;

    // Output order from flatbuffer: [human, nonhuman]
    *human_score_out    = (output->data.int8[EE_LABEL_HUMAN]    - ozp) * os;
    *nonhuman_score_out = (output->data.int8[EE_LABEL_NONHUMAN] - ozp) * os;

    return true;
}
