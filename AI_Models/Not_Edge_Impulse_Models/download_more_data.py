"""
Download additional training images for human detection.

Downloads person/non-person images from open datasets to supplement
the existing training dataset. More data = much better model accuracy.

Usage:
    python download_more_data.py

This will download images into the existing dataset folders:
    - Human_Detection_Dataset/Humans/
    - Human_Detection_Dataset/NonHuman/
"""

import os
import urllib.request
import zipfile
import shutil
import random
from pathlib import Path

DATASET_PATH = Path('../../Human_Detection_Dataset/Human_Detection_Dataset')

def download_with_progress(url, dest):
    """Download a file with progress indicator"""
    print(f"  Downloading: {url}")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"  ✅ Saved to: {dest}")
        return True
    except Exception as e:
        print(f"  ❌ Download failed: {e}")
        return False

def generate_hard_negatives(humans_dir, nonhuman_dir, count=200):
    """Generate additional non-human images by cropping/modifying existing images.
    
    This creates 'hard negatives' - images that look somewhat like humans
    but aren't, helping the model learn better boundaries.
    """
    try:
        from PIL import Image, ImageFilter, ImageOps
        import numpy as np
    except ImportError:
        print("  ⚠️ PIL not installed. Run: pip install Pillow")
        return
    
    existing_nonhuman = list(nonhuman_dir.glob('*.jpg')) + list(nonhuman_dir.glob('*.png')) + list(nonhuman_dir.glob('*.jpeg'))
    existing_human = list(humans_dir.glob('*.jpg')) + list(humans_dir.glob('*.png')) + list(humans_dir.glob('*.jpeg'))
    
    generated = 0
    
    # Strategy 1: Create heavily augmented versions of non-human images
    print(f"\n  📷 Generating augmented non-human images...")
    for img_path in random.sample(existing_nonhuman, min(count // 2, len(existing_nonhuman))):
        try:
            img = Image.open(img_path).convert('RGB')
            
            # Random crop (off-center)
            w, h = img.size
            crop_size = min(w, h) * random.uniform(0.5, 0.8)
            crop_size = int(crop_size)
            x = random.randint(0, max(0, w - crop_size))
            y = random.randint(0, max(0, h - crop_size))
            img_crop = img.crop((x, y, x + crop_size, y + crop_size))
            img_crop = img_crop.resize((96, 96))
            
            # Apply random transform
            transforms = [
                lambda i: i.filter(ImageFilter.GaussianBlur(radius=2)),
                lambda i: ImageOps.posterize(i, random.randint(3, 6)),
                lambda i: i.rotate(random.uniform(-30, 30)),
                lambda i: ImageOps.autocontrast(i),
                lambda i: ImageOps.solarize(i, threshold=random.randint(100, 200)),
            ]
            transform = random.choice(transforms)
            img_out = transform(img_crop)
            
            out_name = f"aug_nonhuman_{generated:04d}.jpg"
            img_out.save(nonhuman_dir / out_name, quality=85)
            generated += 1
            
        except Exception:
            continue
    
    # Strategy 2: Create partial/blurred versions of human images (hard negatives)
    # These simulate situations where the camera sees something human-like but isn't clear
    print(f"  📷 Generating hard negatives from human images...")
    for img_path in random.sample(existing_human, min(count // 4, len(existing_human))):
        try:
            img = Image.open(img_path).convert('RGB')
            w, h = img.size
            
            # Take only a small corner (non-human part of a human photo)
            crop_w = w // 3
            crop_h = h // 3
            corners = [(0, 0), (w - crop_w, 0), (0, h - crop_h), (w - crop_w, h - crop_h)]
            cx, cy = random.choice(corners)
            img_crop = img.crop((cx, cy, cx + crop_w, cy + crop_h))
            img_crop = img_crop.resize((96, 96))
            
            # Heavy blur to destroy human features
            img_out = img_crop.filter(ImageFilter.GaussianBlur(radius=4))
            
            out_name = f"hard_neg_{generated:04d}.jpg"
            img_out.save(nonhuman_dir / out_name, quality=85)
            generated += 1
            
        except Exception:
            continue
    
    # Strategy 3: Generate augmented human images too
    print(f"  📷 Generating augmented human images...")
    human_generated = 0
    for img_path in random.sample(existing_human, min(count // 2, len(existing_human))):
        try:
            img = Image.open(img_path).convert('RGB')
            w, h = img.size
            
            # Random crop centered (keep the human in frame)
            crop_factor = random.uniform(0.7, 0.95)
            new_w = int(w * crop_factor)
            new_h = int(h * crop_factor)
            x = random.randint(0, w - new_w)
            y = random.randint(0, h - new_h)
            img_crop = img.crop((x, y, x + new_w, y + new_h))
            img_crop = img_crop.resize((96, 96))
            
            # Light transforms (keep human recognizable)
            transforms = [
                lambda i: i.filter(ImageFilter.SHARPEN),
                lambda i: ImageOps.autocontrast(i),
                lambda i: i.rotate(random.uniform(-15, 15)),
                lambda i: ImageOps.mirror(i),
            ]
            transform = random.choice(transforms)
            img_out = transform(img_crop)
            
            out_name = f"aug_human_{human_generated:04d}.jpg"
            img_out.save(humans_dir / out_name, quality=85)
            human_generated += 1
            
        except Exception:
            continue
    
    print(f"\n  ✅ Generated {generated} additional non-human images")
    print(f"  ✅ Generated {human_generated} additional human images")

def main():
    humans_dir = DATASET_PATH / 'Humans'
    nonhuman_dir = DATASET_PATH / 'NonHuman'
    
    if not DATASET_PATH.exists():
        print(f"❌ Dataset not found at: {DATASET_PATH}")
        return
    
    # Count existing images
    human_count = len(list(humans_dir.glob('*.*')))
    nonhuman_count = len(list(nonhuman_dir.glob('*.*')))
    print(f"📊 Current dataset:")
    print(f"   Humans:    {human_count} images")
    print(f"   NonHuman:  {nonhuman_count} images")
    print(f"   Total:     {human_count + nonhuman_count} images")
    
    if human_count + nonhuman_count >= 1000:
        print(f"\n✅ Dataset looks good! ({human_count + nonhuman_count} images)")
        print("   You can always add more for better accuracy.")
        return
    
    print(f"\n⚠️  Dataset is too small for reliable detection!")
    print(f"   Recommended: 500+ images per class")
    print(f"   Current: {human_count} + {nonhuman_count} = {human_count + nonhuman_count}")
    
    # Generate augmented data from existing images
    print(f"\n🔄 Generating augmented training data from existing images...")
    generate_hard_negatives(humans_dir, nonhuman_dir, count=300)
    
    # Recount
    human_count = len(list(humans_dir.glob('*.*')))
    nonhuman_count = len(list(nonhuman_dir.glob('*.*')))
    print(f"\n📊 Updated dataset:")
    print(f"   Humans:    {human_count} images")
    print(f"   NonHuman:  {nonhuman_count} images")
    print(f"   Total:     {human_count + nonhuman_count} images")
    
    print(f"\n💡 For even better accuracy, manually add more images:")
    print(f"   1. Download INRIA Person Dataset: http://pascal.inrialpes.fr/data/human/")
    print(f"   2. Search Google Images for 'person standing', 'empty room', 'outdoor scene'")
    print(f"   3. Capture images directly from your ESP32-CAM (best for domain matching!)")
    print(f"   4. Put person images in: {humans_dir}")
    print(f"   5. Put non-person images in: {nonhuman_dir}")

if __name__ == "__main__":
    main()
