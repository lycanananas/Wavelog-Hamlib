#!/usr/bin/env python3
"""Wavelog-Hamlib interface using Python and Hamlib NET rigctl bindings."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import Hamlib
import requests


CONFIG_KEYS = (
	"rigctl_host",
	"rigctl_port",
	"radio_name",
	"interval",
	"wavelog_instances",
)

RECOVERABLE_ERRORS = {
	-Hamlib.RIG_ETIMEOUT,
	-Hamlib.RIG_EIO,
	-Hamlib.RIG_EPROTO,
	-Hamlib.RIG_EPOWER,
}

FORCE_SEND_INTERVAL = 5


@dataclass(frozen=True)
class WavelogInstance:
	url: str
	api_key: str


@dataclass(frozen=True)
class AppConfig:
	rigctl_host: str
	rigctl_port: int
	radio_name: str
	interval: int
	wavelog_instances: list[WavelogInstance]


@dataclass(frozen=True)
class RadioState:
	frequency: int
	mode: str
	power: int | float | str


def eprint(*args, **kwargs) -> None:
	print(*args, file=sys.stderr, **kwargs)


def load_json_config(path: Path) -> dict[str, Any]:
	try:
		with path.open("r", encoding="utf-8") as f:
			values = json.load(f)
	except json.JSONDecodeError as exc:
		raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc

	if not isinstance(values, dict):
		raise RuntimeError(f"Top-level JSON object in {path} must be an object")

	missing = [key for key in CONFIG_KEYS if key not in values]
	if missing:
		raise RuntimeError(f"Missing config keys in {path}: {', '.join(missing)}")

	return values


def parse_wavelog_instances(raw_instances: Any) -> list[WavelogInstance]:
	if not isinstance(raw_instances, list) or not raw_instances:
		raise RuntimeError("wavelog_instances must be a non-empty list")

	instances: list[WavelogInstance] = []

	for index, item in enumerate(raw_instances):
		if not isinstance(item, dict):
			raise RuntimeError(f"wavelog_instances[{index}] must be an object")

		url = item.get("url")
		api_key = item.get("api_key")

		if not isinstance(url, str) or not url.strip():
			raise RuntimeError(f"wavelog_instances[{index}].url must be a non-empty string")

		if not isinstance(api_key, str) or not api_key.strip():
			raise RuntimeError(f"wavelog_instances[{index}].api_key must be a non-empty string")

		instances.append(
			WavelogInstance(
				url=url.strip(),
				api_key=api_key.strip(),
			)
		)

	return instances


def load_config(config_override: str | None = None) -> AppConfig:
	base_dir = Path(__file__).resolve().parent
	candidate_paths = []

	if config_override is not None:
		candidate_paths.append(Path(config_override).resolve())
	else:
		candidate_paths.append(base_dir / "config.json")

	for path in candidate_paths:
		if not path.exists():
			continue

		if path.suffix != ".json":
			raise RuntimeError(f"Unsupported config format: {path}")

		values = load_json_config(path)

		try:
			return AppConfig(
				rigctl_host=str(values["rigctl_host"]),
				rigctl_port=int(values["rigctl_port"]),
				radio_name=str(values["radio_name"]),
				interval=max(1, int(values["interval"])),
				wavelog_instances=parse_wavelog_instances(values["wavelog_instances"]),
			)
		except (TypeError, ValueError) as exc:
			raise RuntimeError(f"Invalid config values in {path}: {exc}") from exc

	raise RuntimeError("Missing config.json")


class HamlibRigClient:
	def __init__(self, host: str, port: int):
		Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE)
		self.endpoint = f"{host}:{port}"
		self.rig: Hamlib.Rig | None = None
		self.last_error_status = Hamlib.RIG_OK
		self.libhamlib = ctypes.CDLL("libhamlib.so")
		self.libhamlib.rig_power2mW.argtypes = [
			ctypes.c_void_p,
			ctypes.POINTER(ctypes.c_uint),
			ctypes.c_float,
			ctypes.c_double,
			ctypes.c_ulonglong,
		]
		self.libhamlib.rig_power2mW.restype = ctypes.c_int

	def connect(self) -> bool:
		self.close()
		self.rig = Hamlib.Rig(Hamlib.RIG_MODEL_NETRIGCTL)
		self.rig.set_conf("rig_pathname", self.endpoint)
		self.rig.set_conf("retry", "1")
		self.rig.set_conf("timeout", "2000")

		try:
			self.rig.open()
		except Exception:
			self.last_error_status = getattr(self.rig, "error_status", -Hamlib.RIG_EIO)
			self.close()
			return False

		self.last_error_status = self.rig.error_status
		return self.last_error_status >= 0

	def close(self) -> None:
		if self.rig is None:
			return

		try:
			self.rig.close()
		except Exception:
			pass

		self.rig = None

	def error_message(self) -> str:
		message = Hamlib.rigerror2(self.last_error_status)
		return message.strip() if isinstance(message, str) else str(self.last_error_status)

	def _ensure_connection(self) -> bool:
		return self.rig is not None or self.connect()

	def _call(self, func, *args):
		if not self._ensure_connection():
			return None

		assert self.rig is not None

		try:
			result = func(*args)
		except Exception:
			self.last_error_status = getattr(self.rig, "error_status", -Hamlib.RIG_EIO)
			if self.last_error_status in RECOVERABLE_ERRORS:
				self.close()
			return None

		self.last_error_status = self.rig.error_status
		if self.last_error_status < 0:
			if self.last_error_status in RECOVERABLE_ERRORS:
				self.close()
			return None

		return result

	def _is_powered_on(self) -> bool:
		assert self.rig is not None

		power_state = self._call(self.rig.get_powerstat)
		if power_state is None:
			return self.last_error_status in (-Hamlib.RIG_ENAVAIL, -Hamlib.RIG_ENIMPL)

		return power_state not in (Hamlib.RIG_POWER_OFF, Hamlib.RIG_POWER_STANDBY)

	@staticmethod
	def _normalize_frequency(frequency_hz: float) -> int:
		return (int(frequency_hz) // 10) * 10

	@staticmethod
	def _normalize_power(power_watts: float | None) -> int | float | str:
		if power_watts is None or power_watts <= 0:
			return ""

		rounded = round(power_watts, 2)
		if abs(rounded - round(rounded)) < 0.01:
			return int(round(rounded))

		return rounded

	def _relative_power_to_watts(self, relative_power: float, frequency_hz: float, mode: int) -> float | None:
		if self.rig is None or relative_power <= 0:
			return None

		milliwatts = ctypes.c_uint()
		rig_ptr = ctypes.c_void_p(int(self.rig.rig))
		result = self.libhamlib.rig_power2mW(
			rig_ptr,
			ctypes.byref(milliwatts),
			ctypes.c_float(relative_power),
			ctypes.c_double(frequency_hz),
			ctypes.c_ulonglong(mode),
		)

		if result != Hamlib.RIG_OK or milliwatts.value == 0:
			return None

		return milliwatts.value / 1000.0

	def read_state(self) -> RadioState | None:
		if not self._ensure_connection():
			return None

		assert self.rig is not None

		if not self._is_powered_on():
			if self.last_error_status in RECOVERABLE_ERRORS:
				self.close()
			return None

		frequency_hz = self._call(self.rig.get_freq, Hamlib.RIG_VFO_CURR)
		if frequency_hz is None or frequency_hz <= 0:
			return None

		mode_data = self._call(self.rig.get_mode, Hamlib.RIG_VFO_CURR)
		if mode_data is None:
			return None

		mode, _width = mode_data
		mode_name = Hamlib.rig_strrmode(mode).strip()
		if mode_name == "":
			self.close()
			return None

		relative_power = self._call(self.rig.get_level_f, Hamlib.RIG_LEVEL_RFPOWER)
		power_watts = None
		if relative_power is not None:
			power_watts = self._relative_power_to_watts(relative_power, frequency_hz, mode)

		return RadioState(
			frequency=self._normalize_frequency(frequency_hz),
			mode=mode_name,
			power=self._normalize_power(power_watts),
		)


def post_info_to_wavelog(
	session: requests.Session,
	instance: WavelogInstance,
	data: dict[str, Any],
) -> bool:
	endpoint = instance.url.rstrip("/") + "/api/radio"
	payload = dict(data)
	payload["key"] = instance.api_key

	try:
		response = session.post(endpoint, json=payload, timeout=10)
	except requests.RequestException as exc:
		eprint(f"Wavelog POST error for {instance.url}: request failed: {exc}")
		return False

	if response.status_code >= 400:
		message = f"Wavelog POST error for {instance.url}: HTTP {response.status_code} returned by server."
		if response.text:
			message += f" Response: {response.text}"
		eprint(message)
		return False

	return True


def build_payload(config: AppConfig, state: RadioState) -> dict[str, Any]:
	return {
		"radio": config.radio_name,
		"frequency": state.frequency,
		"mode": state.mode,
		"power": state.power,
	}


def run(config: AppConfig, *, dry_run: bool = False, once: bool = False) -> int:
	rig_client = HamlibRigClient(config.rigctl_host, config.rigctl_port)
	session = requests.Session()
	last_sent_state: tuple[int, str, int | float | str] | None = None
	last_sent_at = 0.0
	radio_data_unavailable = False
	next_poll_at = time.monotonic()

	try:
		while True:
			state = rig_client.read_state()
			now = time.monotonic()

			if state is None:
				if not radio_data_unavailable:
					message = "Radio data unavailable. Skipping Wavelog update."
					if rig_client.last_error_status < 0:
						message += f" Hamlib: {rig_client.error_message()}"
					eprint(message)
					radio_data_unavailable = True
					last_sent_state = None
					last_sent_at = 0.0

				if once:
					return 1
			else:
				if radio_data_unavailable:
					eprint("Radio data available again. Resuming Wavelog updates.")
					radio_data_unavailable = False

				payload = build_payload(config, state)
				current_state = (state.frequency, state.mode, state.power)

				state_changed = current_state != last_sent_state
				force_send_due = (now - last_sent_at) >= FORCE_SEND_INTERVAL
				should_send = state_changed or force_send_due or last_sent_state is None

				if should_send:
					if dry_run:
						eprint(f"Dry run payload: {payload}")
						last_sent_state = current_state
						last_sent_at = now
					else:
						all_ok = True
						for instance in config.wavelog_instances:
							if not post_info_to_wavelog(session, instance, payload):
								all_ok = False

						if all_ok:
							last_sent_state = current_state
							last_sent_at = now
							eprint(
								f"Updated info. Frequency: {state.frequency} - Mode: {state.mode} - Power: {state.power}"
							)
						else:
							eprint(
								f"Failed to update info. Frequency: {state.frequency} - Mode: {state.mode} - Power: {state.power}"
							)

			if once:
				return 0

			next_poll_at = max(next_poll_at + config.interval, time.monotonic())
			sleep_for = next_poll_at - time.monotonic()
			if sleep_for > 0:
				time.sleep(sleep_for)
	except KeyboardInterrupt:
		eprint("Stopping.")
		return 0
	finally:
		session.close()
		rig_client.close()


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Wavelog-Hamlib interface using Python and Hamlib")
	parser.add_argument("--config", help="Path to config.json")
	parser.add_argument("--dry-run", action="store_true", help="Read rig data and print payload without POSTing to Wavelog")
	parser.add_argument("--once", action="store_true", help="Read one iteration and exit")
	return parser.parse_args()


def main() -> int:
	args = parse_args()

	try:
		config = load_config(args.config)
	except Exception as exc:
		eprint(f"Configuration error: {exc}")
		return 1

	return run(config, dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
	sys.exit(main())