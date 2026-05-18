import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
import matplotlib.pyplot as plt

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Kaggle automatically mounts datasets here
input_base = "/kaggle/input"
DATASET_PATH = None

# Bulletproof directory hunter
for root, dirs, files in os.walk(input_base):
    if "Humans" in dirs and "NonHuman" in dirs:
        DATASET_PATH = root
        break

if DATASET_PATH is None:
    raise ValueError("CRITICAL ERROR: Could not find 'Humans' and 'NonHuman' folders inside Kaggle!")

print(f"Auto-detected dataset parent path: {DATASET_PATH}")
try:
    print(f"Classes found: {os.listdir(DATASET_PATH)}")
except Exception as e:
    print(e)

WORKING_DIR = "/kaggle/working"
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32

train_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="training",
    seed=123,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)

val_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="validation",
    seed=123,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)

normalization_layer = layers.Rescaling(1./127.5, offset=-1)

AUTOTUNE = tf.data.AUTOTUNE
train_ds = train_ds.map(lambda x, y: (normalization_layer(x), y)).cache().shuffle(1000).prefetch(buffer_size=AUTOTUNE)
val_ds = val_ds.map(lambda x, y: (normalization_layer(x), y)).cache().prefetch(buffer_size=AUTOTUNE)

# Because we are on a massive GPU, we can use heavy augmentations!
data_augmentation = tf.keras.Sequential([
    layers.RandomFlip("horizontal"),
    layers.RandomRotation(0.17),
    layers.RandomZoom(0.17),
    layers.RandomContrast(0.2),
])

inputs = tf.keras.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1))
x = data_augmentation(inputs)

base_model = tf.keras.applications.MobileNet(
    input_shape=(IMG_HEIGHT, IMG_WIDTH, 1),
    alpha=0.25,
    include_top=False,
    weights=None, 
    pooling=None
)

x = base_model(x)
x = layers.GlobalAveragePooling2D()(x)
x = layers.Dropout(0.33)(x)
outputs = layers.Dense(2, activation='softmax')(x)

model = tf.keras.Model(inputs, outputs, name="MobileNetV1_Tiny_Kaggle")

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.0039),
    loss='sparse_categorical_crossentropy',
    metrics=['accuracy']
)

class StopAtOptimum(tf.keras.callbacks.Callback):
    def on_epoch_end(self, epoch, logs=None):
        acc = logs.get('accuracy')
        val_acc = logs.get('val_accuracy')
        # Stop if validation accuracy reaches 96%
        if acc >= 0.95 and val_acc >= 0.96:
            print("\nReached >96% Validation Accuracy! Stopping early to prevent overfitting.")
            self.model.stop_training = True

early_stopping = tf.keras.callbacks.EarlyStopping(
    monitor='val_loss', 
    patience=15, 
    restore_best_weights=True,
    verbose=1
)
optimum_stopper = StopAtOptimum()

print("Starting MobileNetV1 Training on Kaggle GPU...")
epochs = 100
model.fit(
    train_ds,
    validation_data=val_ds,
    epochs=epochs,
    callbacks=[early_stopping, optimum_stopper]
)

print("\nQuantizing model to INT8 for ESP32...")
def representative_data_gen():
    for input_value, _ in val_ds.unbatch().batch(1).take(100):
        yield [input_value]

converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_data_gen
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_model_quant = converter.convert()

tflite_path = os.path.join(WORKING_DIR, "mobilenet_v1_tiny.tflite")
with open(tflite_path, "wb") as f:
    f.write(tflite_model_quant)

print(f"Model saved: {tflite_path}")

header_path = os.path.join(WORKING_DIR, "mobilenet_v1_model_data.h")
with open(tflite_path, "rb") as f:
    tflite_content = f.read()

hex_array = [f"0x{b:02x}" for b in tflite_content]
with open(header_path, "w") as f:
    f.write("#ifndef MOBILENET_V1_MODEL_DATA_H\n")
    f.write("#define MOBILENET_V1_MODEL_DATA_H\n\n")
    f.write(f"unsigned const char g_mobilenet_v1_model_data[] = {{\n")
    
    for i in range(0, len(hex_array), 12):
        f.write("  " + ", ".join(hex_array[i:i+12]) + ",\n")
        
    f.write("};\n\n")
    f.write(f"unsigned int g_mobilenet_v1_model_data_size = {len(tflite_content)};\n\n")
    f.write("#endif // MOBILENET_V1_MODEL_DATA_H\n")

print("Training Pipeline Complete!")
