import tensorflow as tf
from tensorflow.keras import layers, models
import pathlib
import os

# --- CONFIGURATION (V2 - Mini MobileNet) ---
DATASET_PATH = '../datasets/Human_Detection_Dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 40 
MODEL_NAME = 'tiny_human_model_v2'

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Loading dataset from: {data_dir}")

    # Load as Grayscale
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

    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.2),
        layers.RandomZoom(0.2),
        layers.RandomContrast(0.2),
        layers.RandomTranslation(0.1, 0.1)
    ])

    # --- MINI MOBILENET BLOCK ---
    def depthwise_block(x, filters, stride=1):
        # Depthwise
        x = layers.DepthwiseConv2D(3, strides=stride, padding='same', use_bias=False)(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        # Pointwise
        x = layers.Conv2D(filters, 1, strides=1, padding='same', use_bias=False)(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        return x

    # --- ARCHITECTURE ---
    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1))
    x = layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = data_augmentation(x)

    # Initial Conv (Stride 2 to shrink 48->24 immediately)
    x = layers.Conv2D(16, 3, strides=2, padding='same', use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)

    # Blocks (MobileNet Style)
    x = depthwise_block(x, 32, stride=1)
    x = depthwise_block(x, 64, stride=2)  # 24->12
    x = depthwise_block(x, 64, stride=1)
    x = depthwise_block(x, 128, stride=2) # 12->6
    x = depthwise_block(x, 128, stride=1)

    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(len(class_names), activation='softmax')(x)

    model = models.Model(inputs, outputs)

    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
                  metrics=['accuracy'])

    model.summary()

    print("Starting Training (V2)...")
    history = model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS)

    # Convert
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
    print(f"✅ Model saved: {tflite_filename}")
    
    # Header
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    with open("human_detect_model_data.h", "w") as f:
        f.write(c_header)
    print("✅ Header updated!")

def hex_to_c_array(hex_data, var_name):
    c_str = f"// Auto-generated (V2)\n#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
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
