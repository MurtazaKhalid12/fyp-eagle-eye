import os
import win32com.client

def export_ppt_to_png(ppt_path, output_png_path):
    powerpoint = win32com.client.Dispatch("PowerPoint.Application")
    # Open presentation without showing window to keep it quiet
    try:
        ppt = powerpoint.Presentations.Open(os.path.abspath(ppt_path), ReadOnly=True, WithWindow=False)
        # Slides is 1-indexed in VBA/COM
        ppt.Slides[1].Export(os.path.abspath(output_png_path), "PNG")
        ppt.Close()
        print(f"Exported slide to image successfully at: {output_png_path}")
    except Exception as e:
        print("Error during export:", e)
    finally:
        powerpoint.Quit()

if __name__ == "__main__":
    export_ppt_to_png("C:\\fyp-eagle-eye\\esp32_architecture.pptx", "C:\\fyp-eagle-eye\\esp32_architecture_ppt_preview.png")
