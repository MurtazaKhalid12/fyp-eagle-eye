# EagleEye — model training scripts

Local training pipelines for the EagleEye on-device human detector. Both
reproduce the Edge Impulse "final" CNN locally and export a full-int8 TFLite
model + a C header (`model_data.h`) that the `eagleeye_local` firmware flashes.

| Script | Input | Notes |
|---|---|---|
| [`train_rgb.py`](train_rgb.py) | 96×96 **RGB** (3-ch) | EI-faithful replica. ~92.2% val acc. |
| [`train_grayscale.py`](train_grayscale.py) | 96×96 **grayscale** (1-ch) | Adds 100 pure-black frames as NonHuman negatives so an all-black frame → non-human. ~91.8% val acc. Luma = `(77R+150G+29B)>>8`. |

Both share the same architecture:
`Conv2D(8)→Pool → Conv2D(16)→Pool → Conv2D(16)→Pool → Flatten → Dense(2,softmax)`
(ops: CONV_2D, MAX_POOL_2D, RESHAPE, FULLY_CONNECTED, SOFTMAX), full int8
quantisation (input scale `1/255`, zp `-128`), class-balanced 763/763.

## Run

```bash
cd C:\fyp-eagle-eye\model-training
python train_rgb.py          # RGB model
# or
python train_grayscale.py    # grayscale + black-frame negatives
```

Each script:
1. reads the dataset from `..\sketchboard\dataset\{Humans,NonHuman}`,
2. trains + quantises to int8,
3. **overwrites** `..\sketchboard\firmware\eagleeye_local\src\model_data.h`
   (`g_model[]`) — so just re-flash `eagleeye_local` afterwards,
4. also writes the `.tflite` + `*_metrics.json` into `..\sketchboard\`.

> ⚠️ RGB and grayscale models have **different input channel counts**, so the
> `eagleeye_local` firmware must match: `train_grayscale.py` requires the
> grayscale firmware path (1-channel feed), `train_rgb.py` the RGB one. The
> firmware currently flashed is **grayscale**.

## Relationship to `sketchboard/`

These are the organised copies. The originals still live in `sketchboard/`
(`train_ei_local.py` = RGB, `train_local_gray.py` = grayscale). The only
difference here is the path anchor — these point back to `sketchboard/` for the
dataset and firmware output, so behaviour is identical.
