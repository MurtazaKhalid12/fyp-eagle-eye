import tensorflow as tf
from tensorflow.keras import layers, models, applications
import os
import pathlib
import numpy as np

# --- CONFIGURATION ---
DATASET_PATH = '../../Human_Detection_Dataset'
IMG_HEIGHT = 96
IMG_WIDTH = 96
BATCH_SIZE = 32
EPOCHS = 20
MODEL_NAME = 'mobilenet_human_model'

def main():
    data_dir = pathlib.Path(DATASET_PATH)

    # 1. Load Dataset (RGB for MobileNetV2 Transfer Learning)
    # MobileNetV2 expects 3 channels (RGB) to use pre-trained 'imagenet' weights.
    print(f"Loading dataset from: {data_dir}")
    
    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="training",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='rgb'  # Changed to RGB for Transfer Learning
    )

    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="validation",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='rgb'
    )

    class_names = train_ds.class_names
    print(f"Classes: {class_names}")

    # 2. Data Augmentation
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.2),
        layers.RandomZoom(0.2),
        layers.RandomContrast(0.2),
    ])

    # 3. Build MobileNetV2 Model (Transfer Learning)
    # alpha=0.35 is a good balance for ESP32 (fast but accurate)
    base_model = applications.MobileNetV2(
        input_shape=(IMG_HEIGHT, IMG_WIDTH, 3),
        include_top=False, 
        weights='imagenet',
        alpha=0.35
    )
    
    base_model.trainable = False # Freeze base model initially

    model = models.Sequential([
        layers.Rescaling(1./127.5, offset=-1, input_shape=(IMG_HEIGHT, IMG_WIDTH, 3)), # MobileNetV2 expects [-1, 1]
        data_augmentation,
        base_model,
        layers.GlobalAveragePooling2D(),
        layers.Dropout(0.2),
        layers.Dense(len(class_names), activation='softmax')
    ])

    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
                  metrics=['accuracy'])

    model.summary()

    # 4. Train
    print("Starting training (Transfer Learning)...")
    history = model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS)
    
    # Optional: Fine-tuning (Unfreeze some layers)
    print("\nFine-tuning...")
    base_model.trainable = True
    # Fine-tune from this layer onwards
    fine_tune_at = 100
    for layer in base_model.layers[:fine_tune_at]:
        layer.trainable = False
        
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-5), # Lower learning rate
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
                  metrics=['accuracy'])
                  
    history_fine = model.fit(train_ds, validation_data=val_ds, epochs=5) # 5 more epochs

    # 5. Convert to TFLite (INT8 Quantization)
    print("Converting to TFLite (INT8)...")
    
    def representative_data_gen():
        for images, _ in train_ds.take(100):
            for i in range(images.shape[0]):
                yield [tf.cast(images[i:i+1], tf.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8   # Standard for MobileNetV2 on TFLite Micro
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()

    # Save
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(tflite_model)
    print(f"✅ Model saved: {tflite_filename}")

    # 6. Generate C++ Header
    print("Generating C++ Header...")
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    
    header_filename = "human_detect_model_data.h"
    with open(header_filename, "w") as f:
        f.write(c_header)
    print(f"✅ Header generated: {header_filename}")

def hex_to_c_array(hex_data, var_name):
    c_str = f"// Auto-generated header file\n"
    c_str += f"#ifndef {var_name.upper()}_H\n"
    c_str += f"#define {var_name.upper()}_H\n\n"
    c_str += f"extern const unsigned char {var_name}[];\n"
    c_str += f"extern const unsigned int {var_name}_len;\n\n"
    c_str += f"const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(hex_data):
        c_str += f"0x{val:02x}, "
        if (i + 1) % 12 == 0: c_str += "\n"
    c_str += "};\n"
    c_str += f"const unsigned int {var_name}_len = {len(hex_data)};\n"
    c_str += "#endif\n"
    return c_str

if __name__ == "__main__":
    main()
