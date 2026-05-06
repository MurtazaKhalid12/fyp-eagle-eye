import tensorflow as tf
from tensorflow.keras import layers, models, regularizers
import pathlib
import numpy as np

# --- CONFIGURATION ---
DATASET_PATH = '../datasets/Human_Detection_Dataset/Human_Detection_Dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32       # Standard batch size for stability with BatchNorm
EPOCHS = 80           # More epochs since we have LR reduction + early stopping
MODEL_NAME = 'tiny_human_model_color'

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Loading dataset from: {data_dir}")

    # Load as RGB COLOR (3 channels)
    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="training",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='rgb',
        shuffle=True        # Ensure shuffling is on
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
    num_classes = len(class_names)
    print(f"Classes: {class_names}")

    # Count dataset sizes
    train_count = 0
    for _, labels in train_ds:
        train_count += labels.shape[0]
    val_count = 0
    for _, labels in val_ds:
        val_count += labels.shape[0]
    print(f"Training samples: {train_count}, Validation samples: {val_count}")

    # Optimize dataset pipeline - shuffle BEFORE cache for variety
    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.shuffle(buffer_size=100).cache().prefetch(buffer_size=AUTOTUNE)
    val_ds = val_ds.cache().prefetch(buffer_size=AUTOTUNE)

    # --- HEAVY AUGMENTATION (Anti-Overfitting) ---
    # Since we only have ~155 training images, we must distort them heavily
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.2),        # Strong rotation (+/- 20%)
        layers.RandomZoom(0.2),            # Strong zoom (+/- 20%)
        layers.RandomContrast(0.2),        # Strong contrast
        layers.RandomBrightness(0.2),      # Strong brightness variation
        layers.RandomTranslation(0.1, 0.1) # Move subject around
    ])

    # --- ROBUST TINY CNN v5 (Regularized) ---
    # Uses L2 Regularization to stop memorization
    
    REG = regularizers.l2(0.001)  # Strong L2 penalty
    
    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 3))
    x = layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = data_augmentation(x)

    # Layer 1: 48x48 -> 24x24
    x = layers.Conv2D(12, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x) # Help stability
    
    # Layer 2: 24x24 -> 12x12
    x = layers.Conv2D(24, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    
    # Layer 3: 12x12 -> 6x6
    x = layers.Conv2D(48, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    
    # Global Pooling
    x = layers.GlobalAveragePooling2D()(x)
    
    x = layers.Dropout(0.5)(x) # High Dropout (50%)
    outputs = layers.Dense(num_classes, activation='softmax', kernel_regularizer=REG)(x)

    model = models.Model(inputs, outputs)

    # Simple fixed learning rate - reliable with Adam
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=['accuracy']
    )

    model.summary()

    # Callbacks
    callbacks = [
        # Reduce LR when val_accuracy plateaus
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_accuracy',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1
        ),
        # Stop if no improvement for 15 epochs
        tf.keras.callbacks.EarlyStopping(
            monitor='val_accuracy', 
            patience=15,
            restore_best_weights=True,
            verbose=1
        )
    ]

    print("\nStarting Training (Tiny Color Model)...")
    print(f"Batch size: {BATCH_SIZE}, Epochs: {EPOCHS}")
    print(f"Steps/epoch: ~{train_count // BATCH_SIZE}\n")
    
    history = model.fit(
        train_ds, 
        validation_data=val_ds, 
        epochs=EPOCHS,
        callbacks=callbacks
    )

    # Print final accuracy
    final_val_acc = max(history.history['val_accuracy'])
    final_train_acc = max(history.history['accuracy'])
    print(f"\nBest Training Accuracy: {final_train_acc:.4f}")
    print(f"Best Validation Accuracy: {final_val_acc:.4f}")

    if final_val_acc < 0.55:
        print("\n⚠️  WARNING: Validation accuracy is very low!")
        print("   Consider adding more training images to your dataset.")
        print("   Recommended: at least 500+ images per class.")

    # Convert to TFLite (INT8)
    print("\nConverting to TFLite (INT8)...")
    def representative_data_gen():
        for images, _ in train_ds.take(100):
            for i in range(images.shape[0]):
                yield [tf.cast(images[i:i+1], tf.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()

    # Save .tflite file
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(tflite_model)
    print(f"Model saved: {tflite_filename} ({len(tflite_model)} bytes)")
    
    # Generate C Header for ESP32
    print("Generating Header...")
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    with open("human_detect_model_data.h", "w") as f:
        f.write(c_header)
    print("Header saved: human_detect_model_data.h")
    
    # Auto-copy to ESP32 Sketch folder
    import shutil
    target_dir = pathlib.Path('../../IOT_Project_FYP_integeration/esp32_camera_custom_tiny')
    if target_dir.exists():
        shutil.copy("human_detect_model_data.h", target_dir / "human_detect_model_data.h")
        print(f"✅ Automatically copied to: {target_dir}")
    else:
        print(f"⚠️ Could not find sketch folder: {target_dir}")
        print("Please copy human_detect_model_data.h manually.")

def hex_to_c_array(hex_data, var_name):
    c_str = f"// Auto-generated (Tiny Color Model - Robust CNN v5 48x48)\n"
    c_str += f"#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
    c_str += f"extern const unsigned char {var_name}[];\n"
    c_str += f"extern const unsigned int {var_name}_len;\n\n"
    c_str += f"const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(hex_data):
        c_str += f"0x{val:02x}, "
        if (i+1)%12==0: c_str += "\n"
    c_str += "};\n"
    c_str += f"const unsigned int {var_name}_len = {len(hex_data)};\n#endif\n"
    return c_str

if __name__ == "__main__":
    main()
