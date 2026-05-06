import tensorflow as tf
from tensorflow.keras import layers, models, regularizers
import pathlib
import numpy as np
import os

# --- CONFIGURATION ---
DATASET_PATH = '../datasets/Human_Detection_Dataset/Human_Detection_Dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 120
MODEL_NAME = 'tiny_human_model_color'

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Loading dataset from: {data_dir}")
    
    if not data_dir.exists():
        print(f"❌ Dataset not found at: {data_dir}")
        return

    # ============================
    # 1. LOAD DATASET
    # ============================
    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="training",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='rgb',
        shuffle=True
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
    print(f"\n📋 Classes: {class_names}")
    print(f"   Class 0 = '{class_names[0]}' (output index 0)")
    print(f"   Class 1 = '{class_names[1]}' (output index 1)")
    print(f"   ⚠️  ESP32: output->data.int8[0] = '{class_names[0]}' score\n")

    # Count samples per class
    train_count = 0
    for _, labels in train_ds:
        train_count += labels.shape[0]
    val_count = 0
    for _, labels in val_ds:
        val_count += labels.shape[0]
    print(f"📊 Training: {train_count}, Validation: {val_count}")

    # Optimize pipeline
    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.shuffle(200).cache().prefetch(AUTOTUNE)
    val_ds = val_ds.cache().prefetch(AUTOTUNE)

    # ============================
    # 2. BUILD MODEL (Proven CNN + Augmentation)
    # ============================
    # Augmentation - keep it moderate and reliable (Keras built-in layers)
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.15),
        layers.RandomZoom(0.15),
        layers.RandomContrast(0.2),
        layers.RandomBrightness(0.15),
        layers.RandomTranslation(0.1, 0.1),
    ])

    REG = regularizers.l2(0.001)

    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 3))
    x = layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = data_augmentation(x)

    # --- PROVEN ARCHITECTURE (same as original that worked) ---
    # But with slightly more filters for color images
    
    # Block 1: 48x48 -> 24x24
    x = layers.Conv2D(16, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    
    # Block 2: 24x24 -> 12x12
    x = layers.Conv2D(32, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    
    # Block 3: 12x12 -> 6x6
    x = layers.Conv2D(64, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    
    # Global Pooling
    x = layers.GlobalAveragePooling2D()(x)
    
    x = layers.Dropout(0.5)(x)
    outputs = layers.Dense(num_classes, activation='softmax', kernel_regularizer=REG)(x)

    model = models.Model(inputs, outputs)

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=['accuracy']
    )

    model.summary()

    # ============================
    # 3. TRAIN
    # ============================
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_accuracy',
            factor=0.5,
            patience=8,
            min_lr=1e-6,
            verbose=1
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor='val_accuracy',
            patience=20,
            restore_best_weights=True,
            verbose=1
        )
    ]

    print("\n🚀 Starting Training...")
    print(f"   Batch size: {BATCH_SIZE}, Epochs: {EPOCHS}\n")
    
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS,
        callbacks=callbacks
    )

    # ============================
    # 4. EVALUATE
    # ============================
    print("\n" + "=" * 60)
    print("📊 EVALUATION RESULTS")
    print("=" * 60)
    
    final_val_acc = max(history.history['val_accuracy'])
    final_train_acc = max(history.history['accuracy'])
    print(f"Best Training Accuracy:   {final_train_acc:.4f} ({final_train_acc*100:.1f}%)")
    print(f"Best Validation Accuracy: {final_val_acc:.4f} ({final_val_acc*100:.1f}%)")
    
    # Confusion Matrix
    print("\n📊 Confusion Matrix (Validation Set):")
    all_preds = []
    all_labels = []
    
    for images, labels in val_ds:
        predictions = model.predict(images, verbose=0)
        pred_classes = np.argmax(predictions, axis=1)
        all_preds.extend(pred_classes)
        all_labels.extend(labels.numpy())
    
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    cm = np.zeros((num_classes, num_classes), dtype=int)
    for true, pred in zip(all_labels, all_preds):
        cm[true][pred] += 1
    
    print(f"\n{'':>15} | Pred {class_names[0]:>10} | Pred {class_names[1]:>10}")
    print("-" * 55)
    for i, name in enumerate(class_names):
        print(f"Actual {name:>10} | {cm[i][0]:>16} | {cm[i][1]:>16}")
    
    for i, name in enumerate(class_names):
        tp = cm[i][i]
        fp = sum(cm[j][i] for j in range(num_classes)) - tp
        fn = sum(cm[i]) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        print(f"  {name}: Precision={precision:.3f} Recall={recall:.3f} F1={f1:.3f}")

    if final_val_acc < 0.65:
        print("\n⚠️  Accuracy too low. Model may not work reliably.")
        print("   But continuing with conversion anyway - test on ESP32.\n")

    # ============================
    # 5. CONVERT TO TFLITE (INT8)
    # ============================
    print("\n🔄 Converting to TFLite INT8...")
    
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

    # ============================
    # 6. TEST TFLITE MODEL (simulate ESP32)
    # ============================
    print("\n🧪 Testing INT8 TFLite model (simulating ESP32 preprocessing)...")
    tflite_interp = tf.lite.Interpreter(model_content=tflite_model)
    tflite_interp.allocate_tensors()
    
    inp_det = tflite_interp.get_input_details()
    out_det = tflite_interp.get_output_details()
    
    print(f"  Input:  shape={inp_det[0]['shape']}, dtype={inp_det[0]['dtype']}")
    print(f"  Output: shape={out_det[0]['shape']}, dtype={out_det[0]['dtype']}")
    print(f"  Input quant:  scale={inp_det[0]['quantization'][0]:.6f}, zp={inp_det[0]['quantization'][1]}")
    print(f"  Output quant: scale={out_det[0]['quantization'][0]:.6f}, zp={out_det[0]['quantization'][1]}")
    
    tflite_correct = 0
    tflite_total = 0
    scores_by_class = {name: [] for name in class_names}
    
    for images, labels in val_ds:
        for i in range(images.shape[0]):
            # ESP32 preprocessing: pixel [0,255] -> int8 [-128,127]
            img = tf.cast(images[i], tf.float32).numpy()
            img_int8 = (img - 128).astype(np.int8)
            img_int8 = np.expand_dims(img_int8, 0)
            
            tflite_interp.set_tensor(inp_det[0]['index'], img_int8)
            tflite_interp.invoke()
            
            out = tflite_interp.get_tensor(out_det[0]['index'])
            pred = np.argmax(out[0])
            actual = int(labels[i].numpy())
            
            scores_by_class[class_names[actual]].append(
                (int(out[0][0]), int(out[0][1]))
            )
            
            if pred == actual:
                tflite_correct += 1
            tflite_total += 1
    
    tflite_acc = tflite_correct / tflite_total if tflite_total > 0 else 0
    print(f"\n  TFLite INT8 Accuracy: {tflite_acc:.3f} ({tflite_acc*100:.1f}%)")
    
    # Score distribution - THIS IS THE KEY OUTPUT
    print(f"\n📊 INT8 Score Distribution:")
    print(f"  output[0] = '{class_names[0]}', output[1] = '{class_names[1]}'")
    
    for name in class_names:
        scores = scores_by_class[name]
        if scores:
            s0 = [s[0] for s in scores]
            s1 = [s[1] for s in scores]
            print(f"\n  When actual = {name}:")
            print(f"    {class_names[0]:>10} score: min={min(s0):>4}, max={max(s0):>4}, avg={np.mean(s0):>6.1f}")
            print(f"    {class_names[1]:>10} score: min={min(s1):>4}, max={max(s1):>4}, avg={np.mean(s1):>6.1f}")
    
    # Threshold recommendation
    human_idx = 0 if 'Human' in class_names[0] else 1
    human_when_present = [s[human_idx] for s in scores_by_class.get(class_names[human_idx], [])]
    human_when_absent = [s[human_idx] for s in scores_by_class.get(class_names[1-human_idx], [])]
    
    if human_when_present and human_when_absent:
        min_h = min(human_when_present)
        max_nh = max(human_when_absent)
        gap = min_h - max_nh
        threshold = (min_h + max_nh) // 2
        
        print(f"\n🎯 THRESHOLD RECOMMENDATION:")
        print(f"  Human score when human present:  min={min_h}, max={max(human_when_present)}, avg={np.mean(human_when_present):.0f}")
        print(f"  Human score when human absent:   min={min(human_when_absent)}, max={max_nh}, avg={np.mean(human_when_absent):.0f}")
        print(f"  Gap: {gap}  |  Recommended threshold: {threshold}")
        
        if gap > 30:
            print("  ✅ Good separation!")
        elif gap > 0:
            print("  ⚠️  Tight separation - may have occasional errors")
        else:
            print("  ❌ Classes overlap - model needs more data!")
    else:
        threshold = 10

    # ============================
    # 7. SAVE FILES
    # ============================
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(tflite_model)
    print(f"\n💾 Saved: {tflite_filename} ({len(tflite_model):,} bytes)")
    
    c_header = hex_to_c_array(tflite_model, "g_human_detect_model_data", class_names)
    with open("human_detect_model_data.h", "w") as f:
        f.write(c_header)
    print("💾 Saved: human_detect_model_data.h")
    
    import shutil
    target_dir = pathlib.Path('../../IOT_Project_FYP_integeration/esp32_camera_custom_tiny')
    if target_dir.exists():
        shutil.copy("human_detect_model_data.h", target_dir / "human_detect_model_data.h")
        print(f"✅ Copied to: {target_dir}")
    else:
        print(f"⚠️ Could not find: {target_dir}")

    print("\n" + "=" * 60)
    print("✅ DONE!")
    print("=" * 60)
    print(f"\nESP32 Code:")
    print(f"  int8_t human_score = output->data.int8[{human_idx}];")
    print(f"  int8_t non_human_score = output->data.int8[{1-human_idx}];")
    print(f"  bool human_detected = (human_score > non_human_score && human_score > {threshold});")
    print(f"\nUpload sketch to ESP32 and test!")


def hex_to_c_array(data, var_name, class_names):
    c_str = f"// Auto-generated - Tiny Color Model v2 (48x48 RGB)\n"
    c_str += f"// output[0] = '{class_names[0]}', output[1] = '{class_names[1]}'\n"
    c_str += f"// Model size: {len(data):,} bytes\n\n"
    c_str += f"#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
    c_str += f"extern const unsigned char {var_name}[];\n"
    c_str += f"extern const unsigned int {var_name}_len;\n\n"
    c_str += f"const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(data):
        c_str += f"0x{val:02x}, "
        if (i+1)%12==0: c_str += "\n"
    c_str += "};\n"
    c_str += f"const unsigned int {var_name}_len = {len(data)};\n#endif\n"
    return c_str


if __name__ == "__main__":
    main()
