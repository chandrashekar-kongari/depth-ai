# Onyx Desktop

A lightweight desktop window for a local Onyx Lite stack and Ollama.
After the first download, chat works with no network.

Built with [Tauri](https://tauri.app) for minimal bundle size (~10MB vs Electron's 150MB+).

## Features

- 🪶 **Lightweight** - Native macOS WebKit, no bundled Chromium
- ⌨️ **Keyboard Shortcuts** - Quick navigation and actions
- 🪟 **Native Feel** - macOS-style title bar with traffic lights
- 💾 **Window State** - Remembers size/position between sessions
- 🔗 **Multi-window** - Open multiple Onyx windows

## Keyboard Shortcuts

| Shortcut | Action           |
| -------- | ---------------- |
| `⌘ N`    | New Chat         |
| `⌘ ⇧ N`  | New Window       |
| `⌘ R`    | Reload           |
| `⌘ [`    | Go Back          |
| `⌘ ]`    | Go Forward       |
| `⌘ ,`    | Open Config File |
| `⌘ W`    | Close Window     |
| `⌘ Q`    | Quit             |

## Prerequisites

1. **Rust** (latest stable)

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   source $HOME/.cargo/env
   ```

2. **Bun** (1.3+)

   ```bash
   curl -fsSL https://bun.sh/install | bash
   ```

3. **Xcode Command Line Tools**
   ```bash
   xcode-select --install
   ```

## Development

Dependencies for `desktop/` are managed by the root bun workspace, so install
once at the repo root:

```bash
# From the repo root
bun install
```

Then, from `desktop/`:

```bash
# Run in development mode
bun run dev

# Run in debug mode
bun run debug
```

## Building

### Build for current architecture

```bash
bun run build
```

### Build Universal Binary (Intel + Apple Silicon)

```bash
# First, add the targets
rustup target add x86_64-apple-darwin
rustup target add aarch64-apple-darwin

# Build universal binary
bun run build:dmg
```

The built `.dmg` will be in `src-tauri/target/release/bundle/dmg/`.

### Cross-compiling for Windows

Follow [Build Windows apps on Linux and macOS](https://v2.tauri.app/distribute/windows-installer/#build-windows-apps-on-linux-and-macos).

_TIP: if facing `Error failed to build app: 'cargo-xwin' command not found.`, try `uv tool install cargo-xwin`._

Once the first-time setup is complete,

```bash
bun run build:windows
```

## Project Structure

```
onyx-desktop/
├── package.json          # Node dependencies & scripts
├── src/
│   └── index.html        # Fallback/loading page
└── src-tauri/
    ├── Cargo.toml        # Rust dependencies
    ├── tauri.conf.json   # Tauri configuration
    ├── build.rs          # Build script
    ├── icons/            # App icons
    └── src/
        └── main.rs       # Rust backend code
```

## Icons

Before building, add your app icons to `src-tauri/icons/`:

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.icns` (macOS)
- `icon.ico` (Windows, optional)

You can generate these from a 1024x1024 source image using:

```bash
# Using tauri's icon generator
bunx tauri icon path/to/your-icon.png
```

## Customization

### Local model

The app installs Docker, Ollama, and `onyx-cli` when they are missing, starts
Docker and Ollama, then opens `http://127.0.0.1`. The first launch needs a
network to pull images, the model in `local_model` (default `qwen3:8b`), and
`glm4:latest`. An admin password can be required to copy Docker or Ollama into
`/Applications`.

**Config file location:**

- macOS: `~/Library/Application Support/app.onyx.onyx-desktop/config.json`
- Linux: `~/.config/onyx-desktop/config.json` (or `$XDG_CONFIG_HOME/onyx-desktop/config.json`)
- Windows: `%APPDATA%\onyx\onyx-desktop\config\config.json`

**To choose a different model before the first successful launch:**

```json
{
  "local_model": "qwen3:8b",
  "window_title": "Onyx"
}
```

**Quick edit via terminal:**

```bash
# macOS
open -t ~/Library/Application\ Support/app.onyx.onyx-desktop/config.json

# Or use any editor
code ~/Library/Application\ Support/app.onyx.onyx-desktop/config.json
```

### Add more shortcuts

Edit `src-tauri/src/main.rs` in the `setup_shortcuts` function.

### Window appearance

Modify the window configuration in `src-tauri/tauri.conf.json`:

- `titleBarStyle`: `"Overlay"` (macOS native) or `"Visible"`
- `decorations`: Window chrome
- `transparent`: For custom backgrounds

## Troubleshooting

### The status page says Docker, Ollama, or onyx-cli is missing

Install Ollama or `onyx-cli` if the page names them, then click **Try again**.
The app installs and starts Docker. An admin password can be required.
The first launch also needs a network so it can download images and the model.

### Build fails on M1/M2 Mac

```bash
# Ensure you have the right target
rustup target add aarch64-apple-darwin
```

### Code signing for distribution

For distributing outside the App Store, you'll need to:

1. Get an Apple Developer certificate
2. Sign the app: `codesign --deep --force --sign "Developer ID" target/release/bundle/macos/Onyx.app`
3. Notarize with Apple

## License

MIT
