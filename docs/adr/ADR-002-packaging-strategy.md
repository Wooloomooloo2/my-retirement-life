# ADR-002: Packaging strategy

**Date:** 2026-05-09  
**Updated:** 2026-05-14  
**Status:** Accepted

---

## Context

My Retirement Life targets non-technical end users on Windows, macOS, and Linux. A core requirement is that users should not be required to install unfamiliar software, use a terminal, or interact with package managers in order to run the application.

The application is a local Python process (FastAPI + embedded Oxigraph) that serves a browser-based UI. The packaging approach must:
- Require no pre-installed Python, database engine, or runtime on the user's machine
- Work on Windows 10/11, macOS (Apple Silicon and Intel), and common Linux distributions
- Produce a distributable that a non-technical user can download and run
- Remain maintainable as Python and OS versions evolve

macOS was added as a target platform after initial design. Mac users are disproportionately represented in the target demographic — higher net worth individuals and people approaching retirement — making macOS support a priority alongside Windows and Linux.

### Options considered

| Option | Platform | Notes |
|--------|----------|-------|
| PyInstaller | Windows, macOS, Linux | Bundles Python interpreter and all dependencies. Produces `.exe` on Windows, `.app` on macOS, and a folder executable on Linux. Widely used and mature. |
| Docker Desktop | All | Consistent environment but requires Docker Desktop installation — crosses the complexity threshold for non-technical users. |
| AppImage | Linux only | Self-contained Linux executable. No installation, no root access required. Distribution-agnostic. |
| Flatpak / Snap | Linux only | Require a runtime to be present — adds a step for some users. |
| cx_Freeze | Windows & Linux | Alternative to PyInstaller; less widely adopted. |
| py2app | macOS only | macOS-specific alternative to PyInstaller for `.app` bundles. Less actively maintained. |

---

## Decision

**Windows: PyInstaller → `.exe`**  
**macOS: PyInstaller → `.app` bundle**  
**Linux: PyInstaller → AppImage (via appimagetool)**

PyInstaller is used as the single build toolchain across all three platforms, producing platform-appropriate output in each case. This minimises build toolchain complexity — one tool, three targets.

### Windows
PyInstaller produces a single `.exe` or a folder with a launcher `.exe`. The user double-clicks and the app opens in their default browser. No Python installation required.

### macOS
PyInstaller produces a `.app` bundle which the user drags to their Applications folder and double-clicks. The app opens in their default browser. No Python installation required.

**macOS code signing and Gatekeeper:** Apple's Gatekeeper security blocks unsigned `.app` bundles by default. Three tiers apply:

| Tier | Requirement | User experience |
|------|-------------|-----------------|
| Unsigned | None | User must right-click → Open on first launch; warning shown |
| Signed | Apple Developer account ($99/yr) | Normal double-click, no warning |
| Notarised | Apple Developer account + notarisation step | Fully trusted, no warning, recommended for public distribution |

For initial releases, the app will be distributed **unsigned**. Users who download from GitHub will see a Gatekeeper warning on first launch and must right-click → Open. This is a known limitation and will be documented clearly in the release notes. Code signing and notarisation are targeted for v1.0 public release.

### Linux
PyInstaller produces the application bundle, which is then wrapped into an AppImage using **appimagetool**. A single `.AppImage` file is downloaded, marked executable (`chmod +x`), and run directly — no package manager, no root access, no dependencies.

---

## Consequences

**Positive**
- Single build toolchain (PyInstaller) produces all three platform targets
- Zero installation friction for end users on all platforms
- No dependency on system Python version — interpreter is bundled
- AppImage requires no root access on Linux
- Build process is automatable via GitHub Actions for future CI/CD
- macOS support covers the disproportionately large share of target users on Apple hardware

**Trade-offs accepted**
- Distributable file size will be ~80–150MB due to bundled Python runtime — acceptable given modern storage and network speeds
- PyInstaller requires maintenance when major Python versions are released
- AppImage requires FUSE on Linux (standard on all mainstream distributions; may need `sudo apt install fuse` on minimal systems)
- macOS Gatekeeper warning on unsigned builds creates friction for initial users — mitigated by clear documentation
- Auto-update mechanisms are not provided; users download new versions manually
- macOS builds must be produced on a Mac; cross-compilation is not supported by PyInstaller

**macOS-specific build notes**
- PyInstaller must be run on a Mac to produce a `.app` bundle — it cannot cross-compile from Windows or Linux
- Both Apple Silicon (arm64) and Intel (x86_64) Macs should be targeted; universal binaries can be produced with PyInstaller's `--target-arch universal2` flag on Apple Silicon
- The `.app` bundle should be compressed as a `.dmg` disk image for distribution — standard macOS convention

**Not in scope for initial release**
- Code signing and notarisation (targeted for v1.0)
- System tray integration or native OS notifications
- Automatic updates
- Universal binary build pipeline (initially target the architecture of the build machine)
