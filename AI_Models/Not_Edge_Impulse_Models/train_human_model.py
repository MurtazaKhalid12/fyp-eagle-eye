import tensorflow as tf
from tensorflow.keras import layers, models
import os
import numpy as np
import pathlib

# --- CONFIGURATION ---
DATASET_PATH = 'Human_Detection_Dataset'
IMG_HEIGHT = 96
IMG_WIDTH = 96
BATCH_SIZE = 32
EPOCHS = 20
MODEL_NAME = 'human_detection_model'

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    
    # 1. Load Dataset
    print("Loading dataset form:", data_dir)
    
    # Use grayscale for ESP32 efficiency
    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="training",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='grayscale' 
    )

    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="validation",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='grayscale'
    )

    class_names = train_ds.class_names
    print("Classes found:", class_names)
    
    # We want 'Humans' to be class 1 (or specific index), but usually alphabetical
    # Typically: Humans, NonHuman -> 0=Humans, 1=NonHuman or vice versa
    # We'll adapt in the ESP32 code based on output.

    # 2. Data Augmentation
    # Enhance specific image variations common in surveillance
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.1),
        layers.RandomZoom(0.1),
    ])

    # 3. Build a Tiny CNN Model (Optimized for ESP32)
    # Input: 96x96x1 (Grayscale)
    model = models.Sequential([
        layers.Rescaling(1./255, input_shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        data_augmentation,
        
        # Conv 1
        layers.Conv2D(8, 3, padding='same', activation='relu'),
        layers.MaxPooling2D(),
        
        # Conv 2
        layers.Conv2D(16, 3, padding='same', activation='relu'),
        layers.MaxPooling2D(),
        
        # Conv 3
        layers.Conv2D(32, 3, padding='same', activation='relu'),
        layers.MaxPooling2D(),
        
        # Dense
        layers.Flatten(),
        layers.Dense(64, activation='relu'),
        layers.Dropout(0.2),
        layers.Dense(len(class_names), activation='softmax') # multi-class output (2 classes)
    ])

    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
                  metrics=['accuracy'])

    model.summary()

    # 4. Train the Model
    print("Starting training...")
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS
    )

    # 5. Convert to TFLite (INT8 Quantization)
    print("Converting to TFLite with quantization...")
    
    def representative_data_gen():
        for images, _ in train_ds.take(100):
            # Flatten batch for yielding one by one
            for i in range(images.shape[0]):
                # Needs to be float32 for converter, even if originating as uint8
                yield [tf.cast(images[i:i+1], tf.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    
    # Ensure full integer quantization for ESP32 compatibility
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.uint8 # Input is uint8 (0-255)
    converter.inference_output_type = tf.int8 # Output is int8
    
    tflite_model = converter.convert()

    # Save .tflite file
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(tflite_model)
    print(f"✅ Model saved as {tflite_filename}")

    # 6. Generate C++ Header File
    print("Generating C++ Header...")
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    
    header_filename = "human_detect_model_data.h"
    with open(header_filename, "w") as f:
        f.write(c_header)
    
    print(f"✅ Header file generated: {header_filename}")
    print("Instructions:")
    print(f"1. Copy '{header_filename}' to your Arduino sketch folder.")
    print("2. Compile and upload your ESP32 sketch.")

def hex_to_c_array(hex_data, var_name):
    c_str = f"// Auto-generated header file\n"
    c_str += f"#ifndef {var_name.upper()}_H\n"
    c_str += f"#define {var_name.upper()}_H\n\n"
    c_str += f"extern const unsigned char {var_name}[];\n"
    c_str += f"extern const unsigned int {var_name}_len;\n\n"
    c_str += f"const unsigned char {var_name}[] = {{\n"
    
    for i, val in enumerate(hex_data):
        c_str += f"0x{val:02x}, "
        if (i + 1) % 12 == 0:
            c_str += "\n"
    
    c_str += "};\n"
    c_str += f"const unsigned int {var_name}_len = {len(hex_data)};\n"
    c_str += "#endif\n"
    return c_str

if __name__ == "__main__":
    main()
