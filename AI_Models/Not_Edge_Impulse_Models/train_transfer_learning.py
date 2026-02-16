"""
Train Human Detection Model using Transfer Learning (MobileNetV2).

WHY TRANSFER LEARNING:
  Training a CNN from scratch with only 193 images/class is unreliable.
  Sometimes it works, sometimes it doesn't (random initialization luck).
  
  MobileNetV2 was trained on 1.4 MILLION ImageNet images and already
  knows how to extract features like edges, shapes, textures, and objects.
  We only need to train the final classification layer.
  
  This is MUCH more reliable with small datasets.

OUTPUT:
  - tiny_human_model_color.tflite (INT8 quantized for ESP32)
  - human_detect_model_data.h (C header for Arduino)
"""
import tensorflow as tf
from tensorflow.keras import layers, models
import pathlib
import numpy as np

# --- CONFIGURATION ---
DATASET_PATH = '../../Human_Detection_Dataset/Human_Detection_Dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 50   # Transfer learning converges fast
MODEL_NAME = 'tiny_human_model_color'
ALPHA = 0.35  # MobileNetV2 width multiplier (0.35 = very small, good for ESP32)


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

    train_count = sum(labels.shape[0] for _, labels in train_ds)
    val_count = sum(labels.shape[0] for _, labels in val_ds)
    print(f"📊 Training: {train_count}, Validation: {val_count}")

    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.cache().shuffle(200).prefetch(AUTOTUNE)
    val_ds = val_ds.cache().prefetch(AUTOTUNE)

    # ============================
    # 2. BUILD MODEL WITH TRANSFER LEARNING
    # ============================
    print(f"\n🧠 Loading MobileNetV2 (alpha={ALPHA}) pretrained on ImageNet...")
    print("   This model already knows how to extract visual features!")
    
    # Data augmentation (inside model, only active during training)
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.15),
        layers.RandomZoom(0.15),
        layers.RandomContrast(0.2),
        layers.RandomBrightness(0.15),
        layers.RandomTranslation(0.1, 0.1),
    ])
    
    # Pre-trained MobileNetV2 backbone
    # alpha=0.35 makes it tiny enough for ESP32
    # include_top=False removes ImageNet classifier, we add our own
    base_model = tf.keras.applications.MobileNetV2(
        input_shape=(IMG_HEIGHT, IMG_WIDTH, 3),
        alpha=ALPHA,
        include_top=False,
        weights='imagenet'
    )
    
    # FREEZE the base model - don't train ImageNet features, just use them
    base_model.trainable = False
    
    print(f"   Base model parameters: {base_model.count_params():,} (FROZEN)")
    
    # Build full model
    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 3))
    
    # Preprocess: MobileNetV2 expects [-1, 1] range
    x = layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = data_augmentation(x)
    
    # Extract features using pretrained backbone
    x = base_model(x, training=False)
    
    # Classification head
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(num_classes, activation='softmax')(x)
    
    model = models.Model(inputs, outputs)
    
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    
    model.summary()
    trainable = sum(1 for v in model.trainable_variables for _ in [1])
    print(f"\n📐 Trainable parameters: {sum(v.numpy().size for v in model.trainable_variables):,}")
    print(f"   Total parameters: {model.count_params():,}")
    
    # ============================
    # 3. TRAIN (Phase 1: Frozen backbone)
    # ============================
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_accuracy', factor=0.5, patience=5, min_lr=1e-6, verbose=1
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor='val_accuracy', patience=15, restore_best_weights=True, verbose=1
        )
    ]

    print("\n🚀 Phase 1: Training classifier head (backbone frozen)...")
    history = model.fit(
        train_ds, validation_data=val_ds,
        epochs=EPOCHS, callbacks=callbacks
    )
    
    phase1_acc = max(history.history['val_accuracy'])
    print(f"   Phase 1 Best Val Accuracy: {phase1_acc:.4f}")

    # ============================
    # 4. FINE-TUNE (Phase 2: Unfreeze last few layers)
    # ============================
    print("\n🔧 Phase 2: Fine-tuning last layers of backbone...")
    
    # Unfreeze the last 20 layers of the backbone
    base_model.trainable = True
    fine_tune_from = max(0, len(base_model.layers) - 20)
    for layer in base_model.layers[:fine_tune_from]:
        layer.trainable = False
    
    # Use very low LR for fine-tuning to not destroy pretrained features
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-4),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    
    ft_trainable = sum(v.numpy().size for v in model.trainable_variables)
    print(f"   Fine-tuning {ft_trainable:,} parameters\n")
    
    history_ft = model.fit(
        train_ds, validation_data=val_ds,
        epochs=30, callbacks=callbacks
    )
    
    phase2_acc = max(history_ft.history['val_accuracy'])
    print(f"   Phase 2 Best Val Accuracy: {phase2_acc:.4f}")

    # ============================
    # 5. EVALUATE
    # ============================
    print("\n" + "=" * 60)
    print("📊 EVALUATION")
    print("=" * 60)
    
    best_val = max(phase1_acc, phase2_acc)
    print(f"Best Validation Accuracy: {best_val:.4f} ({best_val*100:.1f}%)")
    
    # Confusion Matrix
    all_preds = []
    all_labels = []
    for images, labels in val_ds:
        preds = model.predict(images, verbose=0)
        all_preds.extend(np.argmax(preds, axis=1))
        all_labels.extend(labels.numpy())
    
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    cm = np.zeros((num_classes, num_classes), dtype=int)
    for t, p in zip(all_labels, all_preds):
        cm[t][p] += 1
    
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
        print(f"  {name}: P={precision:.3f} R={recall:.3f} F1={f1:.3f}")

    # ============================
    # 6. CONVERT TO TFLITE INT8
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
    # 7. VERIFY TFLITE INT8
    # ============================
    print("\n🧪 Verifying INT8 TFLite Model...")
    interp = tf.lite.Interpreter(model_content=tflite_model)
    interp.allocate_tensors()
    
    inp_det = interp.get_input_details()
    out_det = interp.get_output_details()
    
    print(f"  Input:  {inp_det[0]['shape']}, {inp_det[0]['dtype']}")
    print(f"  Output: {out_det[0]['shape']}, {out_det[0]['dtype']}")
    print(f"  Input quant:  scale={inp_det[0]['quantization'][0]:.6f}, zp={inp_det[0]['quantization'][1]}")
    print(f"  Output quant: scale={out_det[0]['quantization'][0]:.6f}, zp={out_det[0]['quantization'][1]}")
    
    correct = 0
    total = 0
    scores = {name: [] for name in class_names}
    
    for images, labels in val_ds:
        for i in range(images.shape[0]):
            img = tf.cast(images[i], tf.float32).numpy()
            img_int8 = (img - 128).astype(np.int8)
            img_int8 = np.expand_dims(img_int8, 0)
            
            interp.set_tensor(inp_det[0]['index'], img_int8)
            interp.invoke()
            
            result = interp.get_tensor(out_det[0]['index'])
            pred = np.argmax(result[0])
            actual = int(labels[i].numpy())
            
            scores[class_names[actual]].append(
                (int(result[0][0]), int(result[0][1]))
            )
            
            if pred == actual:
                correct += 1
            total += 1
    
    tflite_acc = correct / total
    print(f"\n  TFLite INT8 Accuracy: {tflite_acc:.3f} ({tflite_acc*100:.1f}%)")
    
    # Score distribution
    print(f"\n📊 INT8 Score Distribution:")
    for name in class_names:
        s = scores[name]
        if s:
            s0 = [x[0] for x in s]
            s1 = [x[1] for x in s]
            print(f"\n  When actual = {name}:")
            print(f"    {class_names[0]:>10} score: min={min(s0):>4}, max={max(s0):>4}, avg={np.mean(s0):>6.1f}")
            print(f"    {class_names[1]:>10} score: min={min(s1):>4}, max={max(s1):>4}, avg={np.mean(s1):>6.1f}")
    
    # Threshold
    human_idx = 0 if 'Human' in class_names[0] else 1
    h_present = [s[human_idx] for s in scores[class_names[human_idx]]]
    h_absent = [s[human_idx] for s in scores[class_names[1-human_idx]]]
    
    min_h = min(h_present) if h_present else 0
    max_nh = max(h_absent) if h_absent else 0
    gap = min_h - max_nh
    threshold = (min_h + max_nh) // 2
    
    print(f"\n🎯 THRESHOLD:")
    print(f"  Human score range (human present):  {min(h_present)} to {max(h_present)}")
    print(f"  Human score range (human absent):   {min(h_absent)} to {max(h_absent)}")
    print(f"  Gap: {gap} | Threshold: {threshold}")
    
    if gap > 30: print("  ✅ Excellent separation!")
    elif gap > 10: print("  ✅ Good separation")
    elif gap > 0: print("  ⚠️ Tight separation")
    else: print("  ❌ Classes overlap!")

    # ============================
    # 8. SAVE FILES
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
    target = pathlib.Path('../../IOT_Project_FYP_integeration/esp32_camera_custom_tiny')
    if target.exists():
        shutil.copy("human_detect_model_data.h", target / "human_detect_model_data.h")
        print(f"✅ Copied to: {target}")
    
    # Check if model fits in ESP32 PSRAM
    model_kb = len(tflite_model) / 1024
    if model_kb < 200:
        print(f"\n✅ Model size ({model_kb:.0f} KB) fits well in ESP32 PSRAM")
    else:
        print(f"\n⚠️ Model size ({model_kb:.0f} KB) is large. May need TENSOR_ARENA_SIZE increase.")
    
    print(f"\n{'='*60}")
    print("✅ DONE!")
    print(f"{'='*60}")
    print(f"\nESP32 Code:")
    print(f"  int8_t human_score = output->data.int8[{human_idx}];")
    print(f"  int8_t non_human_score = output->data.int8[{1-human_idx}];")
    print(f"  bool detected = (human_score > non_human_score && human_score > {threshold});")


def hex_to_c_array(data, var_name, class_names):
    c = f"// Auto-generated - Transfer Learning Model (MobileNetV2 alpha={ALPHA})\n"
    c += f"// Input: 48x48 RGB | Output: [{class_names[0]}, {class_names[1]}]\n"
    c += f"// Model size: {len(data):,} bytes\n\n"
    c += f"#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
    c += f"extern const unsigned char {var_name}[];\n"
    c += f"extern const unsigned int {var_name}_len;\n\n"
    c += f"const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(data):
        c += f"0x{val:02x}, "
        if (i+1)%12==0: c += "\n"
    c += "};\n"
    c += f"const unsigned int {var_name}_len = {len(data)};\n#endif\n"
    return c


if __name__ == "__main__":
    main()
