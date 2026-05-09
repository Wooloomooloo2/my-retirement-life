# ADR-002: Packaging strategy

**Date:** 2026-05-09
**Status:** Accepted

---

## Context

My Retirement Life targets non-technical end users on both Windows and Linux. A core requirement is that users should not be required to install unfamiliar software, use a terminal, or interact with package managers in order to run the application.

The application is a local Python process (FastAPI + embedded Oxigraph) that serves a browser-based UI. The packaging approach must:
- Require no pre-installed Python, database engine, or runtime on the user's machine
- Work on Windows 10/11 and common Linux distributions (Ubuntu, Fedora, Mint etc.)
- Produce a distributable that a non-technical user can download and run
- Remain maintainable as Python and OS versions evolve

### Options considered

| Option | Platform | Notes |
|--------|----------|-------|
| PyInstaller | Windows & Linux | Bundles Python interpreter and all dependencies into a single executable or folder. Widely used, mature, no runtime required on the host. |
| Docker Desktop | Both | Consistent environment but requires Docker Desktop installation — crosses the complexity threshold for non-technical users. |
| AppImage | Linux | Self-contained Linux executable. No installation, no root access required. User downloads, marks executable, runs. Universally supported across distributions. |
| Flatpak / Snap | Linux | Distribution-friendly packaging formats. Require a runtime (Flatpak runtime or snapd) to be present — adds a step for some users. |
| cx_Freeze | Windows & Linux | Alternative to PyInstaller; less widely adopted, smaller community. |

---

## Decision

**Windows: PyInstaller**
**Linux: AppImage**

These two formats together achieve the goal of a one-file, no-install user experience on both platforms.

On **Windows**, PyInstaller produces a single `.exe` (or a folder with a launcher `.exe`) that bundles the Python interpreter, FastAPI, pyoxigraph, and all dependencies. The user double-clicks the executable; the application starts and opens in their default browser. No Python installation is required.

On **Linux**, AppImage is the best match for the portability requirement. A single `.AppImage` file is downloaded by the user, marked as executable (`chmod +x`), and run directly — no package manager, no root access, no dependencies to resolve. AppImage files are distribution-agnostic and run on any Linux system with FUSE support (standard on all mainstream distributions).

The build pipeline will use **PyInstaller** to produce the application bundle for both targets, with the Linux bundle then wrapped into an AppImage using **appimagetool**. This keeps a single build toolchain producing both outputs.

---

## Consequences

**Positive**
- Zero installation friction for end users on either platform
- No dependency on system Python version — the interpreter is bundled
- AppImage requires no root access and leaves no system-wide footprint
- Build process is automatable via GitHub Actions for future CI/CD

**Trade-offs accepted**
- Distributable file size will be larger than a native application (~80–150MB) due to bundled Python runtime — acceptable given modern storage and network speeds
- PyInstaller occasionally requires maintenance when major Python versions are released; this is expected ongoing build toolchain work, not a data or application architecture concern
- AppImage requires FUSE to be available on the user's Linux system; this is standard on all mainstream distributions but may require a one-line install on minimal systems (e.g. `sudo apt install fuse`)
- Auto-update mechanisms are not provided in the initial release; users will download new versions manually

**Not in scope for initial release**
- macOS packaging (can be added later via PyInstaller with a `.app` bundle)
- System tray integration or native OS notifications
- Automatic updates
