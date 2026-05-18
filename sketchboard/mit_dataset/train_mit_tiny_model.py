import tensorflow as tf
from tensorflow.keras import layers, models
import pathlib
import os

# --- CONFIGURATION ---
DATASET_PATH = './dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 100
MODEL_NAME = 'mit_tiny_model'

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Loading MIT dataset from: {data_dir}")

    # Load as Grayscale (Much faster than RGB on ESP32)
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

    # Data Augmentation
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.1),
        layers.RandomZoom(0.1),
    ])

    # --- ULTRA-TINY ARCHITECTURE (ESP32 Optimized) ---
    
    model = models.Sequential([
        layers.Rescaling(1./127.5, offset=-1, input_shape=(IMG_HEIGHT, IMG_WIDTH, 1)), # [-1, 1]
        data_augmentation,
        
        # Block 1
        layers.Conv2D(8, 3, strides=2, padding='same', activation='relu'), # Downsample to 24x24
        layers.Dropout(0.2),
        layers.MaxPooling2D(), # 12x12
        
        # Block 2
        layers.Conv2D(16, 3, strides=2, padding='same', activation='relu'), # 6x6
        layers.Dropout(0.2),
        layers.MaxPooling2D(), # 3x3
        
        # Block 3
        layers.Conv2D(32, 3, padding='same', activation='relu'),
        layers.Dropout(0.2),
        layers.GlobalAveragePooling2D(), # 32 features
        
        layers.Dropout(0.2),
        layers.Dense(len(class_names), activation='softmax')
    ])

    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
                  metrics=['accuracy'])

    model.summary()

    early_stopping = tf.keras.callbacks.EarlyStopping(
        monitor='val_loss', 
        patience=15, 
        restore_best_weights=True,
        verbose=1
    )

    print("Starting Training (Tiny Model with Dropout)...")
    history = model.fit(
        train_ds, 
        validation_data=val_ds, 
        epochs=EPOCHS,
        callbacks=[early_stopping]
    )

    # Convert to TFLite (INT8)
    print("Converting to TFLite (INT8)...")
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

    # Save
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(tflite_model)
    print(f"Model saved: {tflite_filename}")
    
if __name__ == "__main__":
    main()
