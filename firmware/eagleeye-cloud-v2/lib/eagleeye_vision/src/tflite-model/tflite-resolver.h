/* EagleEye model file -- human/non-human detection, 96x96 RGB INT8 */

#ifndef _EI_CLASSIFIER_TFLITE_RESOLVER_H_
#define _EI_CLASSIFIER_TFLITE_RESOLVER_H_

#include "edge-impulse-sdk/tensorflow/lite/micro/kernels/micro_ops.h"

#define EI_TFLITE_RESOLVER static tflite::MicroMutableOpResolver<5> resolver; \
    resolver.AddConv2D(); \
    resolver.AddFullyConnected(); \
    resolver.AddMaxPool2D(); \
    resolver.AddReshape(); \
    resolver.AddSoftmax();

#endif // _EI_CLASSIFIER_TFLITE_RESOLVER_H_
