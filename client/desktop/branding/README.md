# Nexa VPN artwork

`nexa-master-icon.png` is the original raster source used for the Nexa VPN application identity. It was created for this fork with OpenAI's built-in image generation tool and then used by `scripts/generate-brand-assets.ps1` to derive desktop, Android, iOS, macOS, Linux and store assets.

Final generation/edit prompt:

> Keep the central cyan/violet N-shaped shield mark and its polished geometric lighting. Make the midnight-navy background extend fully to every edge and corner of the square canvas. Remove all white or transparent corner triangles. Keep the image text-free, watermark-free, centered, high-contrast, premium and suitable as a VPN app-icon master.

Generated source dimensions: 1254 × 1254 PNG. Do not replace it with Amnezia logos or other third-party trademarks. Review generated derivatives visually after changing the master because adaptive/circular platform masks can crop edge content.

Regenerate platform assets on Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate-brand-assets.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-branding.ps1
```
