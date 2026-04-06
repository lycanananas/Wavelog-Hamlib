# Wavelog-Hamlib
Connects Wavelog to `rigctld` via Python 3 and the system Hamlib bindings.
This updates the used frequency, mode and configured TX power in Wavelog's Live QSO view.

The bridge opens a fresh Hamlib connection for every poll cycle. If `rig_open()`, radio state
readout, or the Wavelog update fails, it waits 5 seconds and retries the loop. After a fully
successful cycle it closes the connection and starts the next cycle 1 second later.

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

The Python entrypoint reads `config.json`.

Example `config.json`:

```json
{
	"rigctl_host": "127.0.0.1",
	"rigctl_port": 4532,
	"radio_name": "FT-991A",
	"wavelog_instances": [
		{
			"url": "https://example.wavelog.com",
			"api_key": "2137-1234-5678-9012-345678901234"
		}
	]
}
```

## Running

Start the software by running:

```bash
python rigctl_cloudlog_interface.py
```

Dry-run without sending to Wavelog:

```bash
python rigctl_cloudlog_interface.py --dry-run
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
