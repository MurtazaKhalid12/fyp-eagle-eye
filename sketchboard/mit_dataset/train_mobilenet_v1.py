import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

SKETCHBOARD = Path(__file__).resolve().parent.parent
DATASET_PATH = SKETCHBOARD / "mit_dataset" / "merged_dataset"
IMG_HEIGHT = 96
IMG_WIDTH = 96
BATCH_SIZE = 32

print(f"Loading dataset from: {DATASET_PATH}")

# 1. Load dataset as GRAYSCALE (what ESP32 actually sends)
train_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="training",
    seed=42,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)
val_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="validation",
    seed=42,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)

class_names = train_ds.class_names
print(f"Classes: {class_names}")

# 2. Normalize to [-1, 1]
normalization_layer = layers.Rescaling(1./127.5, offset=-1)
AUTOTUNE = tf.data.AUTOTUNE
train_ds = train_ds.map(lambda x, y: (normalization_layer(x), y)).cache().shuffle(2000).prefetch(buffer_size=AUTOTUNE)
val_ds   = val_ds.map(lambda x, y: (normalization_layer(x), y)).cache().prefetch(buffer_size=AUTOTUNE)

# 3. Load pretrained RGB model and STEAL its weights for grayscale
#    Strategy: load ImageNet MobileNet (3ch), average the RGB weights
#    of the first conv layer → make it work with 1-channel input directly.
#    NO WRAPPER. NO CONCATENATE. Pure grayscale model for ESP32.
print("\nLoading ImageNet weights and adapting to grayscale...")

# Load full RGB model (3-channel) to extract pretrained weights
base_rgb = tf.keras.applications.MobileNet(
    input_shape=(IMG_HEIGHT, IMG_WIDTH, 3),
    alpha=0.25,
    include_top=False,
    weights='imagenet',
    pooling='avg'
)

# Build our actual 1-channel model (no wrapper needed on ESP32!)
base_gray = tf.keras.applications.MobileNet(
    input_shape=(IMG_HEIGHT, IMG_WIDTH, 1),
    alpha=0.25,
    include_top=False,
    weights=None,
    pooling='avg'
)

# Transfer weights: first conv layer → average RGB → grayscale
print("Transferring pretrained weights to grayscale model...")
for i, (rgb_layer, gray_layer) in enumerate(zip(base_rgb.layers, base_gray.layers)):
    if rgb_layer.get_weights():
        rgb_weights = rgb_layer.get_weights()
        gray_weights = gray_layer.get_weights()
        # First conv layer: shape (k, k, 3, filters) → average to (k, k, 1, filters)
        if rgb_weights[0].shape != gray_weights[0].shape:
            adapted = [np.mean(rgb_weights[0], axis=2, keepdims=True)]
            if len(rgb_weights) > 1:
                adapted += rgb_weights[1:]
            gray_layer.set_weights(adapted)
        else:
            gray_layer.set_weights(rgb_weights)

print("Weight transfer complete!")

# Freeze for Phase 1
base_gray.trainable = False

inputs = tf.keras.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1))
x = base_gray(inputs, training=False)
x = layers.Dropout(0.3)(x)
outputs = layers.Dense(2, activation='softmax')(x)

model = tf.keras.Model(inputs, outputs, name="MobileNetV1_Grayscale_ESP32")
model.summary()

# 4. Custom callback - stop when accuracy AND precision are both good
class StopAtBest(tf.keras.callbacks.Callback):
    def __init__(self, val_ds, acc_threshold=0.94, prec_threshold=0.94):
        super().__init__()
        self.val_ds = val_ds
        self.acc_threshold = acc_threshold
        self.prec_threshold = prec_threshold

    def on_epoch_end(self, epoch, logs=None):
        from sklearn.metrics import precision_score
        val_acc = logs.get('val_accuracy', 0)
        y_true, y_pred = [], []
        for images, labels in self.val_ds:
            preds = self.model.predict(images, verbose=0)
            y_pred.extend(np.argmax(preds, axis=1))
            y_true.extend(labels.numpy())
        prec = precision_score(y_true, y_pred, average='weighted', zero_division=0)
        print(f"  [Monitor] val_accuracy={val_acc:.4f}  val_precision={prec:.4f}")
        if val_acc >= self.acc_threshold and prec >= self.prec_threshold:
            print(f"\n>>> TARGET REACHED: Acc={val_acc*100:.1f}% Precision={prec*100:.1f}% — Stopping! <<<")
            self.model.stop_training = True

# 5. Phase 1: Train top layer only (frozen base)
model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss='sparse_categorical_crossentropy',
    metrics=['accuracy']
)

es1 = tf.keras.callbacks.EarlyStopping(monitor='val_accuracy', patience=5, restore_best_weights=True, verbose=1)
print("\n=== Phase 1: Top layer only (frozen base) ===")
model.fit(train_ds, validation_data=val_ds, epochs=10, callbacks=[es1, StopAtBest(val_ds)])

# 6. Phase 2: Fine-tune whole model
print("\n=== Phase 2: Fine-tuning all layers ===")
base_gray.trainable = True
model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.0001),
    loss='sparse_categorical_crossentropy',
    metrics=['accuracy']
)
es2 = tf.keras.callbacks.EarlyStopping(monitor='val_accuracy', patience=10, restore_best_weights=True, verbose=1)
model.fit(train_ds, validation_data=val_ds, epochs=50, callbacks=[es2, StopAtBest(val_ds)])

# 7. INT8 Quantization — pure grayscale, no wrapper needed!
print("\n=== Quantizing to INT8 for ESP32 (pure grayscale) ===")

def representative_data_gen():
    for img, _ in val_ds.unbatch().batch(1).take(100):
        yield [img]

converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_data_gen
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_model_quant = converter.convert()

tflite_path = "mobilenet_v1_tiny.tflite"
with open(tflite_path, "wb") as f:
    f.write(tflite_model_quant)
print(f"TFLite model saved: {tflite_path} ({len(tflite_model_quant)//1024} KB)")

# 8. Generate C Header (proper const for ESP32 flash placement)
header_path = "mobilenet_v1_model_data.h"
with open(tflite_path, "rb") as f:
    tflite_content = f.read()

hex_array = [f"0x{b:02x}" for b in tflite_content]
with open(header_path, "w") as f:
    f.write("#ifndef MOBILENET_V1_MODEL_DATA_H\n")
    f.write("#define MOBILENET_V1_MODEL_DATA_H\n\n")
    f.write("// Model stored in FLASH (not RAM) - do not remove const\n")
    f.write("alignas(8) const unsigned char g_human_detect_model_data[] = {\n")
    for i in range(0, len(hex_array), 12):
        f.write("  " + ", ".join(hex_array[i:i+12]) + ",\n")
    f.write("};\n\n")
    f.write(f"const unsigned int g_human_detect_model_data_size = {len(tflite_content)};\n\n")
    f.write("#endif // MOBILENET_V1_MODEL_DATA_H\n")

print(f"Firmware header saved: {header_path}")
print("\n=== DONE! Pure grayscale model — no wrapper, no Concatenate, ESP32 safe! ===")
