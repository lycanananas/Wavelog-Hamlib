# Wavelog-Hamlib
Connects Wavelog to `rigctld` via Python 3 and the system Hamlib bindings.
This updates the used frequency, mode and configured TX power in Wavelog's Live QSO view.

## Requirements

Use system packages only.

On Debian or Ubuntu install:

```bash
apt install python3 python3-hamlib python3-requests
```

On Arch Linux install:

```bash
pacman -S python hamlib python-requests
```

The Python bindings are provided by the `hamlib` package itself.

## Configuration

The Python entrypoint reads `config.py`.

Example `config.py`:

```python
# rigctl-specific configuration
rigctl_host = "127.0.0.1"
rigctl_port = 4532

# Wavelog-specific parameters
wavelog_url = "https://example.wavelog.com/"
wavelog_api_key = "2137-1234-5678-9012-345678901234"

# displayed in Wavelog's Live QSO menu
radio_name = "FT-991a"

# poll interval in seconds
interval = 1
```

## Running

Start the software by running:

```bash
python rigctl_cloudlog_interface.py
```

Dry-run one iteration without POSTing to Wavelog:

```bash
python rigctl_cloudlog_interface.py --once --dry-run
```

## systemd

Example system service is available in `wavelog-hamlib.service`.
It runs the bridge as user `radio` and group `radio`.
It is configured to always restart, without systemd start-rate limiting.

Example installation:

```bash
sudo cp wavelog-hamlib.service /etc/systemd/system/
sudo chown -R radio:radio /opt/Wavelog-Hamlib
sudo chmod 640 /opt/Wavelog-Hamlib/config.py
sudo systemctl daemon-reload
sudo systemctl enable --now wavelog-hamlib.service
```

Useful commands:

```bash
sudo systemctl status wavelog-hamlib.service
sudo journalctl -u wavelog-hamlib.service -f
sudo systemctl restart wavelog-hamlib.service
```

If the `radio` user or group already exists, skip the `useradd` step.
If you keep the project in another path, update `WorkingDirectory`, `ExecStart`, and the `--config` path in `wavelog-hamlib.service`.
