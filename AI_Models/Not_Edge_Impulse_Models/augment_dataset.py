"""
Generate HIGH-QUALITY augmented training images from existing dataset.

Unlike simple copies, this creates REALISTIC variations that help the model:
- Different lighting (brightness/contrast)
- Different orientations (rotation/flip)  
- Different scales (zoom/crop)
- Different quality (blur/noise simulating ESP32-CAM)

Target: 193 images/class -> 1000+ images/class
"""
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import os
import random
import numpy as np
from pathlib import Path

DATASET_PATH = Path('../../Human_Detection_Dataset/Human_Detection_Dataset')
AUGMENTATIONS_PER_IMAGE = 5  # Create 5 variants of each image


def augment_image(img, idx):
    """Apply a random combination of augmentations"""
    img = img.convert('RGB')
    w, h = img.size
    
    # 1. Random horizontal flip (50%)
    if random.random() > 0.5:
        img = ImageOps.mirror(img)
    
    # 2. Random rotation (-20 to +20 degrees) 
    angle = random.uniform(-20, 20)
    img = img.rotate(angle, fillcolor=(128, 128, 128))
    
    # 3. Random crop (70-95% of image, then resize back)
    crop_factor = random.uniform(0.7, 0.95)
    crop_w = int(w * crop_factor)
    crop_h = int(h * crop_factor)
    left = random.randint(0, w - crop_w)
    top = random.randint(0, h - crop_h)
    img = img.crop((left, top, left + crop_w, top + crop_h))
    img = img.resize((w, h), Image.BILINEAR)
    
    # 4. Random brightness (0.6 - 1.4)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(random.uniform(0.6, 1.4))
    
    # 5. Random contrast (0.6 - 1.4)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(random.uniform(0.6, 1.4))
    
    # 6. Random saturation (0.5 - 1.5)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(random.uniform(0.5, 1.5))
    
    # 7. Random blur (simulates ESP32-CAM quality) - 30% chance
    if random.random() > 0.7:
        radius = random.uniform(0.5, 1.5)
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
    
    # 8. Random noise (simulates sensor noise) - 30% chance
    if random.random() > 0.7:
        img_array = np.array(img, dtype=np.float32)
        noise = np.random.normal(0, random.uniform(5, 15), img_array.shape)
        img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(img_array)
    
    return img


def process_folder(folder_path, class_name):
    """Augment all images in a folder"""
    image_files = [f for f in os.listdir(folder_path) 
                   if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))
                   and not f.startswith('aug_')]  # Skip previously augmented
    
    print(f"\n  Processing {class_name}: {len(image_files)} original images")
    
    generated = 0
    for img_file in image_files:
        try:
            img_path = os.path.join(folder_path, img_file)
            original = Image.open(img_path)
            
            for aug_idx in range(AUGMENTATIONS_PER_IMAGE):
                augmented = augment_image(original.copy(), aug_idx)
                
                # Save with unique name
                base_name = os.path.splitext(img_file)[0]
                out_name = f"aug_{base_name}_v{aug_idx}.jpg"
                out_path = os.path.join(folder_path, out_name)
                augmented.save(out_path, quality=90)
                generated += 1
                
        except Exception as e:
            print(f"  ⚠️ Error processing {img_file}: {e}")
            continue
    
    print(f"  ✅ Generated {generated} augmented images for {class_name}")
    return generated


def main():
    humans_dir = DATASET_PATH / 'Humans'
    nonhuman_dir = DATASET_PATH / 'NonHuman'
    
    if not DATASET_PATH.exists():
        print(f"❌ Dataset not found at: {DATASET_PATH}")
        return
    
    # Count existing (original only)
    human_orig = len([f for f in os.listdir(humans_dir) 
                      if not f.startswith('aug_') and f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))])
    nonhuman_orig = len([f for f in os.listdir(nonhuman_dir) 
                         if not f.startswith('aug_') and f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))])
    
    print(f"📊 Current dataset:")
    print(f"   Humans (original):    {human_orig}")
    print(f"   NonHuman (original):  {nonhuman_orig}")
    
    # Clean old augmented images first
    print(f"\n🧹 Cleaning old augmented images...")
    for folder in [humans_dir, nonhuman_dir]:
        removed = 0
        for f in os.listdir(folder):
            if f.startswith('aug_'):
                os.remove(os.path.join(folder, f))
                removed += 1
        if removed:
            print(f"   Removed {removed} old augmented images from {folder.name}")
    
    # Generate augmented images
    print(f"\n🔄 Generating {AUGMENTATIONS_PER_IMAGE} augmented versions per image...")
    
    process_folder(str(humans_dir), "Humans")
    process_folder(str(nonhuman_dir), "NonHuman")
    
    # Final count
    human_total = len([f for f in os.listdir(humans_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))])
    nonhuman_total = len([f for f in os.listdir(nonhuman_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))])
    
    print(f"\n📊 Updated dataset:")
    print(f"   Humans:    {human_orig} original + {human_total - human_orig} augmented = {human_total} total")
    print(f"   NonHuman:  {nonhuman_orig} original + {nonhuman_total - nonhuman_orig} augmented = {nonhuman_total} total")
    print(f"   Grand total: {human_total + nonhuman_total} images")
    print(f"\n✅ Dataset is now large enough for reliable training!")
    print(f"   Run: python train_best_of_n.py")


if __name__ == "__main__":
    main()
