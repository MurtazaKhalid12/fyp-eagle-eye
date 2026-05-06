# ==========================================
# COCO Human Detection Training (Google Colab)
# ==========================================
# Instructions:
# 1. Open Google Colab (colab.research.google.com)
# 2. Create a New Notebook
# 3. Copy each section below into a separate cell
# ==========================================

# ==========================================
# CELL 1: Install Dependencies
# ==========================================
# !pip install -q fiftyone tensorflow
import fiftyone as fo
import fiftyone.zoo as foz
import os
import shutil
import tensorflow as tf
from tensorflow.keras import layers, models

print(f"TensorFlow Version: {tf.__version__}")


# ==========================================
# CELL 2: Download COCO Data (Person vs Background)
# ==========================================
# 1. Download 2000 "Person" images
print("Downloading 'Person' images...")
dataset_person = foz.load_zoo_dataset(
    "coco-2017",
    split="train",
    label_types=["detections"],
    classes=["person"],
    max_samples=2000,
    shuffle=True,
    dataset_name="coco-person"
)

# 2. Download 2000 "Background" images (Cats, Dogs, Cars, etc.)
print("Downloading 'Background' images...")
dataset_background = foz.load_zoo_dataset(
    "coco-2017",
    split="train",
    label_types=["detections"],
    classes=["cat", "dog", "car", "chair", "potted plant"],
    max_samples=2000,
    shuffle=True,
    dataset_name="coco-background"
)


# ==========================================
# CELL 3: Prepare Dataset
# ==========================================
BASE_DIR = "coco_dataset_formatted"
if os.path.exists(BASE_DIR): shutil.rmtree(BASE_DIR)
os.makedirs(f"{BASE_DIR}/person")
os.makedirs(f"{BASE_DIR}/background")

print("Organizing images...")

for sample in dataset_person:
    shutil.copy(sample.filepath, f"{BASE_DIR}/person/{os.path.basename(sample.filepath)}")

for sample in dataset_background:
    shutil.copy(sample.filepath, f"{BASE_DIR}/background/{os.path.basename(sample.filepath)}")

print(f"Dataset Ready: {len(os.listdir(f'{BASE_DIR}/person'))} Persons, {len(os.listdir(f'{BASE_DIR}/background'))} Backgrounds")


# ==========================================
# CELL 4: Load & Train MobileNetV2
# ==========================================
IMG_SIZE = 96
BATCH_SIZE = 32

train_ds = tf.keras.utils.image_dataset_from_directory(
  BASE_DIR, validation_split=0.2, subset="training", seed=123,
  image_size=(IMG_SIZE, IMG_SIZE), batch_size=BATCH_SIZE
)
val_ds = tf.keras.utils.image_dataset_from_directory(
  BASE_DIR, validation_split=0.2, subset="validation", seed=123,
  image_size=(IMG_SIZE, IMG_SIZE), batch_size=BATCH_SIZE
)

# Data Augmentation
data_augmentation = tf.keras.Sequential([
  layers.RandomFlip("horizontal"),
  layers.RandomRotation(0.2),
])

# Model: MobileNetV2 (Alpha 0.35)
base_model = tf.keras.applications.MobileNetV2(
    input_shape=(IMG_SIZE, IMG_SIZE, 3), include_top=False, alpha=0.35, weights='imagenet'
)
base_model.trainable = False

model = models.Sequential([
  layers.Input(shape=(IMG_SIZE, IMG_SIZE, 3)),
  data_augmentation,
  # [FIX] MobileNetV2 expects [-1, 1], not [0, 1]
  layers.Rescaling(1./127.5, offset=-1), 
  base_model,
  layers.GlobalAveragePooling2D(),
  layers.Dropout(0.2),
  layers.Dense(2, activation='softmax')
])

print("--- Step 1: Training Head ---")
model.compile(optimizer='adam', loss=tf.keras.losses.SparseCategoricalCrossentropy(), metrics=['accuracy'])
history = model.fit(train_ds, validation_data=val_ds, epochs=10)

print("\n--- Step 2: Fine-Tuning ---")
# Unfreeze the base model
base_model.trainable = True

# Tune specifically the top layers (optional, unfreezing everything for small models is usually okay too)
# Let's unfreeze from layer 100 onwards
fine_tune_at = 100
for layer in base_model.layers[:fine_tune_at]:
  layer.trainable = False

# Recompile with a much lower learning rate
model.compile(loss=tf.keras.losses.SparseCategoricalCrossentropy(),
              optimizer = tf.keras.optimizers.Adam(learning_rate=1e-5),
              metrics=['accuracy'])

history_fine = model.fit(train_ds, validation_data=val_ds, epochs=10, initial_epoch=history.epoch[-1])


# ==========================================
# CELL 5: Convert to ESP32 (Quantized)
# ==========================================
converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]

def representative_data_gen():
  for input_value, _ in train_ds.take(100):
    yield [tf.cast(input_value, tf.float32)]

converter.representative_dataset = representative_data_gen
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_model = converter.convert()

# Save as Header File
with open('model_data.h', 'w') as f:
    f.write('const unsigned char g_model[] = {')
    f.write(','.join([str(i) for i in tflite_model]))
    f.write('};\n')
    f.write(f'const int g_model_len = {len(tflite_model)};')

print("Done! Download 'model_data.h' from the Files tab.")
