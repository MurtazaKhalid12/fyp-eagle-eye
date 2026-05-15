import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, applications
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, f1_score

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

SKETCHBOARD = Path(__file__).resolve().parent.parent
DATASET_PATH = SKETCHBOARD / "dataset"
IMG_HEIGHT, IMG_WIDTH = 48, 48

def load_rgb_data():
    class_names = sorted(p.name for p in DATASET_PATH.iterdir() if p.is_dir())
    images, labels = [], []
    for label, class_name in enumerate(class_names):
        class_dir = DATASET_PATH / class_name
        paths = list(class_dir.glob("*.jpg")) + list(class_dir.glob("*.jpeg")) + list(class_dir.glob("*.png"))
        for p in paths:
            img_bytes = tf.io.read_file(str(p))
            img = tf.io.decode_image(img_bytes, channels=3, expand_animations=False)
            img = tf.cast(img, tf.float32)
            
            # Crop to square and resize
            shape = tf.shape(img)
            h, w = shape[0], shape[1]
            side = tf.minimum(h, w)
            offset_y, offset_x = (h - side) // 2, (w - side) // 2
            img = tf.image.crop_to_bounding_box(img, offset_y, offset_x, side, side)
            img = tf.image.resize(img, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")
            
            # MobileNetV2 expects [-1, 1] preprocessing
            img = applications.mobilenet_v2.preprocess_input(img)
            
            images.append(img.numpy())
            labels.append(label)
    return np.array(images), np.array(labels), class_names

print("Loading dataset in RGB format for MobileNetV2...")
X, y, CLASS_NAMES = load_rgb_data()
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, stratify=y, random_state=42)

print(f"Data loaded: {len(X_train)} train, {len(X_val)} validation.")

# Build Teacher Model
print("Downloading Pre-Trained MobileNetV2 (ImageNet weights)...")
base_model = applications.MobileNetV2(
    input_shape=(IMG_HEIGHT, IMG_WIDTH, 3),
    include_top=False,
    weights='imagenet'
)
base_model.trainable = False  # Freeze the 14-million image knowledge!

inputs = tf.keras.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 3))
# Data augmentation for robust feature learning
x = layers.RandomRotation(0.12)(inputs)
x = layers.RandomZoom(height_factor=0.18, width_factor=0.18)(x)

x = base_model(x, training=False)
x = layers.GlobalAveragePooling2D()(x)
x = layers.Dropout(0.3)(x)
outputs = layers.Dense(len(CLASS_NAMES), activation='softmax')(x)

teacher_model = tf.keras.Model(inputs, outputs, name="Teacher_MobileNetV2")

teacher_model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"]
)

print("\nFine-Tuning the new 2-Class head...")
teacher_model.fit(
    X_train, y_train,
    validation_data=(X_val, y_val),
    epochs=10,
    batch_size=32,
    verbose=1
)

print("\nEvaluating Teacher Model...")
y_pred_probs = teacher_model.predict(X_val)
y_pred = np.argmax(y_pred_probs, axis=1)

print("\nClassification Report:")
print(classification_report(y_val, y_pred, target_names=CLASS_NAMES))

f1 = f1_score(y_val, y_pred, average='macro')
print(f"Teacher Macro F1 Score: {f1:.4f}")

save_path = Path(__file__).resolve().parent / "teacher_mobilenetv2.keras"
teacher_model.save(str(save_path))
print(f"\n✅ Teacher model saved to {save_path.name}")
