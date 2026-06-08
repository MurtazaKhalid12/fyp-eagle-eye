import tensorflow as tf
from tensorflow.keras import layers, models
import pathlib
import os

# --- CONFIGURATION ---
DATASET_PATH = r'c:\fyp-eagle-eye\sketchboard\local_mobilenet_v1\dataset'
IMG_HEIGHT = 96
IMG_WIDTH = 96
BATCH_SIZE = 16
EPOCHS = 150
MODEL_NAME = 'mobilenet_v1_96x96'  # Keep filename same for compatibility
FIRMWARE_DIR = r'c:\fyp-eagle-eye\sketchboard\local_mobilenet_v1\firmware\local_mobilenet_v1_detector'

def hex_to_c_array(hex_data, var_name):
    c_str = f"// Auto-generated local custom lightweight CNN 96x96 Grayscale INT8 model\n"
    c_str += f"#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
    c_str += f"extern const unsigned char {var_name}[];\n"
    c_str += f"extern const unsigned int {var_name}_len;\n\n"
    c_str += f"alignas(16) const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(hex_data):
        c_str += f"0x{val:02x}, "
        if (i+1)%12==0: c_str += "\n"
    c_str += "\n};\n"
    c_str += f"const unsigned int {var_name}_len = {len(hex_data)};\n#endif\n"
    return c_str

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Loading dataset from: {data_dir}")

    # Load Grayscale 96x96 images
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
    print(f"Classes: {class_names}")

    # Data Augmentation (applied in dataset map, not model layers)
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.15),
        layers.RandomZoom(0.15),
    ])

    # Apply data augmentation to training dataset only
    train_ds = train_ds.map(
        lambda x, y: (data_augmentation(x, training=True), y),
        num_parallel_calls=tf.data.AUTOTUNE
    )

    # Optimize datasets for performance
    train_ds = train_ds.cache().shuffle(1000).prefetch(buffer_size=tf.data.AUTOTUNE)
    val_ds = val_ds.cache().prefetch(buffer_size=tf.data.AUTOTUNE)

    # --- CUSTOM ULTRA-TINY ARCHITECTURE (ESP32 Optimized, 5,954 Parameters) ---
    model = models.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        layers.Rescaling(1./127.5, offset=-1),  # Rescale to [-1, 1]
        
        # Block 1
        layers.Conv2D(8, 3, strides=2, padding='same', activation='relu'), # 96x96 -> 48x48
        layers.MaxPooling2D(), # 24x24
        
        # Block 2
        layers.Conv2D(16, 3, strides=2, padding='same', activation='relu'), # 12x12
        layers.MaxPooling2D(), # 6x6
        
        # Block 3
        layers.Conv2D(32, 3, padding='same', activation='relu'),
        layers.GlobalAveragePooling2D(), # 32 features
        
        # Dense Head
        layers.Dropout(0.2),
        layers.Dense(len(class_names), activation='softmax')
    ])

    # Compile with Adam
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=['accuracy']
    )

    model.summary()

    print("\n--- Training Custom Tiny CNN (96x96 Grayscale) ---")
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor='val_accuracy', 
        patience=30,  # Increased patience for deeper convergence
        restore_best_weights=True,
        verbose=1
    )
    
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS,
        callbacks=[early_stop]
    )

    # Save float32 model
    float_path = f"{MODEL_NAME}_float.tflite"
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    float_tflite = converter.convert()
    with open(float_path, 'wb') as f:
        f.write(float_tflite)
    print(f"\n[OK] Saved Float32 TFLite model: {float_path}")

    # Convert to TFLite (INT8 quantized)
    print("\nConverting to TFLite (INT8 quantized)...")
    def representative_data_gen():
        # Yield validation images (grayscale 96x96x1) for calibration
        for images, _ in val_ds.take(25):
            for i in range(images.shape[0]):
                yield [tf.cast(images[i:i+1], tf.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()

    # Save INT8 TFLite model locally
    int8_path = f"{MODEL_NAME}_int8.tflite"
    with open(int8_path, 'wb') as f:
        f.write(tflite_model)
    print(f"[OK] Saved INT8 Quantized TFLite model: {int8_path}")

    # Generate C Header array for firmware
    print(f"\nGenerating C Header...")
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    
    # Ensure firmware output directory exists
    os.makedirs(FIRMWARE_DIR, exist_ok=True)
    header_path = os.path.join(FIRMWARE_DIR, "human_detect_model_data.h")
    with open(header_path, "w") as f:
        f.write(c_header)
    print(f"[OK] Header written to: {header_path}")

if __name__ == "__main__":
    main()
